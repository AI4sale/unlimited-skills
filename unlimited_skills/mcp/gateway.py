"""The Unlimited Tools MCP gateway: front many upstream MCP servers with 3 meta-tools.

Instead of letting an agent host load every upstream tool schema into its
context window (30-200K tokens for busy MCP setups), the gateway exposes:

- ``tools_search`` -- lexical search over indexed upstream tool names and
  descriptions. Never returns input schemas and never spawns upstreams by
  itself (pass ``refresh: true`` to spawn and index everything).
- ``tools_schema`` -- lazily spawns ONE upstream and returns ONE tool's
  ``inputSchema``.
- ``tools_call`` -- routes one call to the owning upstream and relays the
  result.

Upstreams are stdio subprocesses only (no network, no OAuth in v1), spawned
lazily on first need, kept alive for reuse, and terminated on shutdown.
Env values in the config may reference environment variables (``%VAR%`` or
``$VAR``); they are expanded from ``os.environ`` and never logged.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, Iterable

from .. import __version__
from .audit import AuditLog
from .protocol import PROTOCOL_VERSION, RefusalError, StdioServer, ToolError

GATEWAY_NAME = "unlimited-tools-gateway"
MAX_SEARCH_LIMIT = 20
DEFAULT_SEARCH_LIMIT = 8
UPSTREAM_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_+.#/-]*")

# Per-upstream timeouts (seconds). Overridable per upstream or globally in
# the gateway config via startup_timeout_seconds / request_timeout_seconds.
DEFAULT_STARTUP_TIMEOUT = 20.0
DEFAULT_REQUEST_TIMEOUT = 30.0

# Gateway refusal codes (JSON-RPC error.code values; see docs/mcp-gateway.md).
UPSTREAM_START_FAILED = -32001  # upstream could not be spawned or failed its handshake
UPSTREAM_TIMEOUT = -32002  # upstream did not answer within the deadline
UPSTREAM_PROTOCOL_ERROR = -32003  # upstream returned malformed/garbage output
UPSTREAM_FAILED = -32004  # upstream returned a JSON-RPC error or died mid-call


class GatewayConfigError(RuntimeError):
    """The gateway config file is missing or malformed."""


class UpstreamError(RefusalError):
    """An upstream MCP server failed to start, answer, or stay alive.

    Carries one of the ``UPSTREAM_*`` refusal codes; surfaced to the host as
    a structured JSON-RPC error response, never as garbage relay or a crash.
    """

    def __init__(self, message: str, code: int = UPSTREAM_FAILED) -> None:
        super().__init__(code, message)


def _tokens(text: str) -> set[str]:
    """Local lexical tokenizer (same shape as cli.tokens, no vector stack)."""
    result: set[str] = set()
    for match in _WORD_RE.finditer(text or ""):
        raw = match.group(0).lower().strip("-_/")
        if len(raw) > 1:
            result.add(raw)
        for part in re.split(r"[-_/]+", raw):
            if len(part) > 1:
                result.add(part)
    return result


def score_tool(query: str, name: str, description: str) -> float:
    """Simple lexical score over a tool's name and description only."""
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    score = 3.0 * len(query_tokens & _tokens(name))
    score += 1.0 * len(query_tokens & _tokens(description))
    q_lower = query.lower().strip()
    if q_lower and q_lower in (name or "").lower():
        score += 4.0
    if q_lower and q_lower in (description or "").lower():
        score += 2.0
    return score


def load_gateway_config(path: Path) -> dict:
    """Load and validate the gateway JSON config (see mcp-gateway-config.schema.json)."""
    path = Path(path)
    if not path.is_file():
        raise GatewayConfigError(f"Gateway config not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8").lstrip("﻿"))
    except json.JSONDecodeError as exc:
        raise GatewayConfigError(f"Gateway config is not valid JSON: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("upstreams"), list):
        raise GatewayConfigError("Gateway config must be an object with an 'upstreams' list.")
    _validate_timeouts(data, "config")
    seen: set[str] = set()
    for index, spec in enumerate(data["upstreams"]):
        if not isinstance(spec, dict):
            raise GatewayConfigError(f"upstreams[{index}] must be an object.")
        name = spec.get("name")
        if not isinstance(name, str) or not UPSTREAM_NAME_RE.match(name):
            raise GatewayConfigError(f"upstreams[{index}].name must match {UPSTREAM_NAME_RE.pattern}.")
        if name in seen:
            raise GatewayConfigError(f"Duplicate upstream name: {name}")
        seen.add(name)
        command = spec.get("command")
        if not isinstance(command, str) or not command.strip():
            raise GatewayConfigError(f"upstreams[{index}].command must be a non-empty string.")
        args = spec.get("args", [])
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise GatewayConfigError(f"upstreams[{index}].args must be a list of strings.")
        env = spec.get("env", {})
        if not isinstance(env, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in env.items()
        ):
            raise GatewayConfigError(f"upstreams[{index}].env must map strings to strings.")
        tools = spec.get("tools", [])
        if not isinstance(tools, list):
            raise GatewayConfigError(f"upstreams[{index}].tools must be a list.")
        for t_index, tool in enumerate(tools):
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"]:
                raise GatewayConfigError(f"upstreams[{index}].tools[{t_index}] needs a string 'name'.")
        _validate_timeouts(spec, f"upstreams[{index}]")
    return data


def _validate_timeouts(spec: dict, label: str) -> None:
    for key in ("startup_timeout_seconds", "request_timeout_seconds"):
        if key not in spec:
            continue
        value = spec[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise GatewayConfigError(f"{label}.{key} must be a positive number of seconds.")


class UpstreamClient:
    """One lazily-spawned upstream MCP server over subprocess stdio.

    Lifecycle: not spawned until first needed; reused while alive; answers
    are read by a background thread so every request has a hard deadline;
    terminated (then killed) on gateway shutdown or after a refusal that
    leaves the stream out of sync (timeout, garbage output).
    """

    def __init__(self, spec: dict, defaults: dict | None = None) -> None:
        defaults = defaults or {}
        self.spec = spec
        self.name = str(spec["name"])
        self.process: subprocess.Popen | None = None
        self.tools: dict[str, dict] = {}
        self.indexed = False
        self.spawn_count = 0
        self._next_id = 0
        self._lines: queue.Queue | None = None
        self.startup_timeout = float(
            spec.get(
                "startup_timeout_seconds",
                defaults.get("startup_timeout_seconds", DEFAULT_STARTUP_TIMEOUT),
            )
        )
        self.request_timeout = float(
            spec.get(
                "request_timeout_seconds",
                defaults.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT),
            )
        )

    @property
    def started(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @staticmethod
    def _reader_loop(stdout: Any, lines: queue.Queue) -> None:
        try:
            for line in iter(stdout.readline, b""):
                lines.put(line)
        except (OSError, ValueError):
            pass
        lines.put(None)  # EOF sentinel

    def start(self) -> None:
        if self.started:
            return
        env = dict(os.environ)
        for key, value in (self.spec.get("env") or {}).items():
            # Values may reference %VAR% / $VAR; expanded locally, never logged.
            env[str(key)] = os.path.expandvars(str(value))
        try:
            self.process = subprocess.Popen(
                [self.spec["command"], *(self.spec.get("args") or [])],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        except OSError as exc:
            self.process = None
            raise UpstreamError(
                f"Failed to spawn upstream '{self.name}': {type(exc).__name__}",
                code=UPSTREAM_START_FAILED,
            ) from exc
        self.spawn_count += 1
        self._lines = queue.Queue()
        threading.Thread(
            target=self._reader_loop,
            args=(self.process.stdout, self._lines),
            name=f"upstream-{self.name}-reader",
            daemon=True,
        ).start()
        try:
            self.request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": GATEWAY_NAME, "version": __version__},
                },
                timeout=self.startup_timeout,
            )
            self.notify("notifications/initialized")
        except UpstreamError as exc:
            self.terminate()
            raise UpstreamError(
                f"Upstream '{self.name}' failed to start: {exc}",
                code=UPSTREAM_START_FAILED,
            ) from exc

    def ensure_indexed(self) -> None:
        self.start()
        if self.indexed:
            return
        result = self.request("tools/list", {})
        listing = result.get("tools") if isinstance(result, dict) else None
        for tool in listing if isinstance(listing, list) else []:
            if not isinstance(tool, dict):
                continue
            name = tool.get("name")
            if not isinstance(name, str) or not name:
                continue
            self.tools[name] = {
                "description": str(tool.get("description") or ""),
                "inputSchema": tool.get("inputSchema") or {"type": "object"},
            }
        self.indexed = True

    def _send(self, message: dict) -> None:
        if self.process is None or self.process.stdin is None:
            raise UpstreamError(f"Upstream '{self.name}' is not running.")
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        try:
            self.process.stdin.write(payload)
            self.process.stdin.flush()
        except OSError as exc:
            raise UpstreamError(f"Upstream '{self.name}' stdin write failed.") from exc

    def notify(self, method: str, params: dict | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            message["params"] = params
        self._send(message)

    def request(self, method: str, params: dict, timeout: float | None = None) -> dict:
        self._next_id += 1
        request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        lines = self._lines
        if self.process is None or lines is None:
            raise UpstreamError(f"Upstream '{self.name}' is not running.")
        deadline = time.monotonic() + (timeout if timeout is not None else self.request_timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.terminate()  # response stream is out of sync; do not reuse
                raise UpstreamError(
                    f"Upstream '{self.name}' timed out on '{method}'.",
                    code=UPSTREAM_TIMEOUT,
                )
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                raise UpstreamError(f"Upstream '{self.name}' closed its stdio stream.")
            stripped = line.strip()
            if not stripped:
                continue
            try:
                message = json.loads(stripped.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                self.terminate()  # garbage on the protocol stream; never relay it
                raise UpstreamError(
                    f"Upstream '{self.name}' returned a malformed (non-JSON) response.",
                    code=UPSTREAM_PROTOCOL_ERROR,
                )
            if not isinstance(message, dict):
                self.terminate()
                raise UpstreamError(
                    f"Upstream '{self.name}' returned a non-object JSON-RPC message.",
                    code=UPSTREAM_PROTOCOL_ERROR,
                )
            if message.get("id") != request_id:
                continue  # skip notifications and unrelated responses
            if "error" in message:
                error = message.get("error") or {}
                raise UpstreamError(
                    f"Upstream '{self.name}' error {error.get('code')}: {error.get('message')}",
                    code=UPSTREAM_FAILED,
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise UpstreamError(
                    f"Upstream '{self.name}' returned a non-object result for '{method}'.",
                    code=UPSTREAM_PROTOCOL_ERROR,
                )
            return result

    def terminate(self) -> None:
        process = self.process
        self.process = None
        self._lines = None
        self.tools = {}
        self.indexed = False
        if process is None:
            return
        for stream in (process.stdin, process.stdout):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


class Gateway:
    """In-memory tool index plus lazy upstream lifecycle for the meta-tools."""

    def __init__(self, config: dict, audit: AuditLog) -> None:
        self.audit = audit
        defaults = {
            "startup_timeout_seconds": config.get("startup_timeout_seconds", DEFAULT_STARTUP_TIMEOUT),
            "request_timeout_seconds": config.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT),
        }
        self.upstreams: dict[str, UpstreamClient] = {
            spec["name"]: UpstreamClient(spec, defaults) for spec in config.get("upstreams", [])
        }

    def iter_indexed_tools(self) -> Iterable[tuple[str, str, str]]:
        """Yield (upstream, tool, description) from static config plus live indexes."""
        for upstream_name, client in self.upstreams.items():
            entries: dict[str, str] = {}
            for tool in client.spec.get("tools") or []:
                if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                    entries[tool["name"]] = str(tool.get("description") or "")
            for tool_name, info in client.tools.items():
                entries[tool_name] = info["description"]
            for tool_name, description in entries.items():
                yield upstream_name, tool_name, description

    def _split_fq(self, arguments: dict) -> tuple[UpstreamClient, str]:
        fq = str(arguments.get("tool") or "").strip()
        upstream_name, _, tool_name = fq.partition(".")
        if not upstream_name or not tool_name:
            raise ToolError("tool must be fully qualified as 'upstream.tool'.")
        client = self.upstreams.get(upstream_name)
        if client is None:
            known = ", ".join(sorted(self.upstreams)) or "<none>"
            raise ToolError(f"Unknown upstream: {upstream_name}. Configured upstreams: {known}")
        return client, tool_name

    def tools_search(self, arguments: dict) -> dict:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ToolError("query is required.")
        try:
            limit = int(arguments.get("limit", DEFAULT_SEARCH_LIMIT))
        except (TypeError, ValueError) as exc:
            raise ToolError("limit must be an integer.") from exc
        limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        if bool(arguments.get("refresh")):
            for client in self.upstreams.values():
                client.ensure_indexed()
        hits = []
        for upstream_name, tool_name, description in self.iter_indexed_tools():
            score = score_tool(query, tool_name, description)
            if score <= 0.0:
                continue
            hits.append(
                {
                    "tool": f"{upstream_name}.{tool_name}",
                    "upstream": upstream_name,
                    "name": tool_name,
                    "description": description,
                    "score": round(score, 3),
                }
            )
        hits.sort(key=lambda item: (-item["score"], item["tool"]))
        return {
            "query": query,
            "hits": hits[:limit],
            "note": "Input schemas are never included here. Call tools_schema for exactly one tool.",
        }

    def tools_schema(self, arguments: dict) -> dict:
        client, tool_name = self._split_fq(arguments)
        client.ensure_indexed()
        info = client.tools.get(tool_name)
        if info is None:
            raise ToolError(f"Upstream '{client.name}' has no tool named '{tool_name}'.")
        return {
            "tool": f"{client.name}.{tool_name}",
            "description": info["description"],
            "inputSchema": info["inputSchema"],
        }

    def tools_call(self, arguments: dict) -> dict:
        client, tool_name = self._split_fq(arguments)
        call_arguments = arguments.get("arguments")
        if call_arguments is None:
            call_arguments = {}
        if not isinstance(call_arguments, dict):
            raise ToolError("arguments must be an object.")
        client.ensure_indexed()
        if tool_name not in client.tools:
            raise ToolError(f"Upstream '{client.name}' has no tool named '{tool_name}'.")
        result = client.request("tools/call", {"name": tool_name, "arguments": call_arguments})
        if "content" not in result:
            result = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "isError": False}
        return result

    def shutdown(self) -> None:
        for client in self.upstreams.values():
            client.terminate()


def _upstream_of(arguments: dict) -> str:
    fq = str(arguments.get("tool") or "")
    upstream_name, _, tool_name = fq.partition(".")
    return upstream_name if tool_name else ""


def _audited(gateway: Gateway, meta_tool: str, func) -> Any:
    def handler(arguments: dict) -> Any:
        start = time.monotonic()
        ok = False
        error = ""
        try:
            result = func(arguments)
            ok = True
            return result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            # Results are never audited -- only call shape, timing, and status.
            gateway.audit.record(
                tool=meta_tool,
                upstream=_upstream_of(arguments),
                duration_ms=(time.monotonic() - start) * 1000.0,
                ok=ok,
                arguments=arguments,
                error=error,
            )

    return handler


def build_gateway_registry(gateway: Gateway) -> dict[str, dict]:
    """Meta-tool registry for :class:`~unlimited_skills.mcp.protocol.StdioServer`."""
    return {
        "tools_search": {
            "description": (
                "Search the indexed upstream MCP tools by name and description. "
                "Returns names and descriptions only -- never input schemas. "
                "Does not spawn upstreams unless refresh=true."
            ),
            "inputSchema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_LIMIT,
                        "default": DEFAULT_SEARCH_LIMIT,
                    },
                    "refresh": {
                        "type": "boolean",
                        "default": False,
                        "description": "Spawn and index every configured upstream before searching.",
                    },
                },
            },
            "handler": _audited(gateway, "tools_search", gateway.tools_search),
        },
        "tools_schema": {
            "description": (
                "Return the inputSchema of exactly ONE upstream tool, addressed as "
                "'upstream.tool'. Spawns that upstream lazily on first need."
            ),
            "inputSchema": {
                "type": "object",
                "required": ["tool"],
                "properties": {
                    "tool": {"type": "string", "description": "Fully qualified 'upstream.tool'."},
                },
            },
            "handler": _audited(gateway, "tools_schema", gateway.tools_schema),
        },
        "tools_call": {
            "description": (
                "Call ONE upstream tool, addressed as 'upstream.tool', and relay its "
                "result. Spawns that upstream lazily on first need."
            ),
            "inputSchema": {
                "type": "object",
                "required": ["tool"],
                "properties": {
                    "tool": {"type": "string", "description": "Fully qualified 'upstream.tool'."},
                    "arguments": {"type": "object", "description": "Arguments for the upstream tool."},
                },
            },
            "handler": _audited(gateway, "tools_call", gateway.tools_call),
        },
    }


def run_gateway(
    config: dict,
    audit: AuditLog,
    reader: BinaryIO | None = None,
    writer: BinaryIO | None = None,
) -> None:
    """Run the gateway MCP server loop over stdio (blocking until EOF)."""
    gateway = Gateway(config, audit)
    server = StdioServer(
        build_gateway_registry(gateway),
        server_name=GATEWAY_NAME,
        reader=reader,
        writer=writer,
    )
    try:
        server.serve_forever()
    finally:
        gateway.shutdown()
