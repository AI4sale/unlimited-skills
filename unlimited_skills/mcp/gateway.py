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

Upstreams are stdio subprocesses only (no network, no OAuth), spawned lazily
on first need, kept alive for reuse, and terminated on shutdown. Every
upstream is governed by the security model in
docs/mcp-upstream-security-model.md: a per-upstream trust level, a no-shell
command allowlist, a forward-nothing environment policy with a names-only
``env_allowlist`` (the v1 literal ``env`` map is gone), bounded timeouts,
and schema/response size caps that refuse -- never truncate.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import tempfile
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
# the gateway config via startup_timeout_seconds / request_timeout_seconds,
# but never above the hard bounds: a config cannot disable deadlines.
DEFAULT_STARTUP_TIMEOUT = 20.0
DEFAULT_REQUEST_TIMEOUT = 30.0
MAX_STARTUP_TIMEOUT = 120.0
MAX_REQUEST_TIMEOUT = 300.0

# Trust levels (docs/mcp-upstream-security-model.md). The default is the most
# restrictive level under which a correctly packaged local upstream still runs.
TRUST_DISABLED = "disabled"
TRUST_LOCAL_RESTRICTED = "local-restricted"
TRUST_LOCAL_TRUSTED = "local-trusted"
TRUST_FUTURE_REMOTE = "future-remote-placeholder"
TRUST_LEVELS = frozenset(
    {TRUST_DISABLED, TRUST_LOCAL_RESTRICTED, TRUST_LOCAL_TRUSTED, TRUST_FUTURE_REMOTE}
)
DEFAULT_TRUST_LEVEL = TRUST_LOCAL_RESTRICTED

# Bare command names resolvable via PATH at local-trusted ONLY. Fixed in code,
# never extensible from config: a tampered config cannot promote a shell into
# a "known binary". Everything else requires an absolute path.
KNOWN_RUNNERS = frozenset({"node", "npx", "bunx", "deno", "python", "python3", "uv", "uvx"})

# Shell binaries are never valid upstream commands at any trust level.
SHELL_COMMANDS = frozenset(
    {"sh", "bash", "zsh", "cmd", "cmd.exe", "powershell", "pwsh", "powershell.exe"}
)

# Minimal base environment forwarded to every upstream: the variables a child
# process needs to run at all, copied from the gateway's environment when
# present. Fixed in code; never includes credential-shaped variables.
# COMSPEC is deliberately excluded -- an upstream never gets a shell.
BASE_ENV_VARS = (
    "PATH",
    "HOME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    # Windows process essentials:
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PATHEXT",
    "NUMBER_OF_PROCESSORS",
)
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_ENV_ALLOWLIST = 32

# Size limits (bytes): refusal on exceed, never truncation. Trust-level
# ceilings clamp config values; the restricted ceilings are the floor model.
MIN_LIMIT_BYTES = 1024
DEFAULT_MAX_SCHEMA_BYTES = 64 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 256 * 1024
RESTRICTED_MAX_SCHEMA_BYTES = 256 * 1024
RESTRICTED_MAX_RESPONSE_BYTES = 1024 * 1024
TRUSTED_MAX_SCHEMA_BYTES = 1024 * 1024
TRUSTED_MAX_RESPONSE_BYTES = 8 * 1024 * 1024

# Audit rotation bounds (the defaults live in audit.py).
MIN_AUDIT_MAX_BYTES = 64 * 1024
MAX_AUDIT_MAX_BYTES = 100 * 1024 * 1024
MIN_AUDIT_MAX_FILES = 1
MAX_AUDIT_MAX_FILES = 20
AUDIT_LEVELS = frozenset({"minimal", "standard"})

# Gateway refusal codes (JSON-RPC error.code values; see
# docs/mcp-upstream-security-model.md "Refusal codes").
UPSTREAM_START_FAILED = -32001  # upstream could not be spawned or failed its handshake
UPSTREAM_TIMEOUT = -32002  # upstream did not answer within the deadline
UPSTREAM_PROTOCOL_ERROR = -32003  # upstream returned malformed/garbage output
UPSTREAM_FAILED = -32004  # upstream returned a JSON-RPC error or died mid-call
UPSTREAM_DISABLED = -32005  # upstream is configured but disabled
COMMAND_NOT_ALLOWED = -32006  # command violates the allowlist policy for its trust level
ENV_FORWARDING_DENIED = -32007  # forwarding beyond the names-only allowlist was attempted
SCHEMA_TOO_LARGE = -32008  # one tool's inputSchema exceeds max_schema_bytes
RESPONSE_TOO_LARGE = -32009  # one tools/call result exceeds max_response_bytes
TRUST_LEVEL_VIOLATION = -32010  # operation not permitted at the upstream's trust level


class GatewayConfigError(RuntimeError):
    """The gateway config file is missing or malformed."""


class UpstreamError(RefusalError):
    """An upstream MCP server failed, or a security policy refused the call.

    Carries one of the refusal codes above; surfaced to the host as a
    structured JSON-RPC error response, never as garbage relay or a crash.
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


def trust_ceilings(trust_level: str) -> tuple[int, int]:
    """(max_schema_bytes, max_response_bytes) ceilings for a trust level.

    Only local-trusted gets the higher ceilings; every other level (including
    the never-spawned disabled / future-remote-placeholder) uses the
    restricted ceilings as a defensive floor.
    """
    if trust_level == TRUST_LOCAL_TRUSTED:
        return TRUSTED_MAX_SCHEMA_BYTES, TRUSTED_MAX_RESPONSE_BYTES
    return RESTRICTED_MAX_SCHEMA_BYTES, RESTRICTED_MAX_RESPONSE_BYTES


def _payload_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def load_gateway_config(path: Path) -> dict:
    """Load and validate the gateway JSON config.

    Format: schemas/mcp-upstream-config.schema.json (the E07 security model).
    Violations of the semantic rules (trust-level ceilings, timeout hard
    bounds, the removed v1 ``env`` map) are :class:`GatewayConfigError` here,
    before any process is spawned.
    """
    path = Path(path)
    if not path.is_file():
        raise GatewayConfigError(f"Gateway config not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8").lstrip("﻿"))
    except json.JSONDecodeError as exc:
        raise GatewayConfigError(f"Gateway config is not valid JSON: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("upstreams"), list):
        raise GatewayConfigError("Gateway config must be an object with an 'upstreams' list.")
    if "schema_version" in data and data["schema_version"] != 1:
        raise GatewayConfigError("Gateway config schema_version must be 1.")
    _validate_timeouts(data, "config")
    _validate_audit_settings(data)
    seen: set[str] = set()
    for index, spec in enumerate(data["upstreams"]):
        label = f"upstreams[{index}]"
        if not isinstance(spec, dict):
            raise GatewayConfigError(f"{label} must be an object.")
        name = spec.get("name")
        if not isinstance(name, str) or not UPSTREAM_NAME_RE.match(name):
            raise GatewayConfigError(f"{label}.name must match {UPSTREAM_NAME_RE.pattern}.")
        if name in seen:
            raise GatewayConfigError(f"Duplicate upstream name: {name}")
        seen.add(name)
        if "env" in spec:
            raise GatewayConfigError(
                f"{label}.env is not supported: the v1 literal env map was removed by the "
                "upstream security model. Use env_allowlist (a list of variable NAMES copied "
                "from the local environment -- never values). "
                "See docs/mcp-upstream-security-model.md."
            )
        command = spec.get("command")
        if not isinstance(command, str) or not command.strip():
            raise GatewayConfigError(f"{label}.command must be a non-empty string.")
        args = spec.get("args", [])
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise GatewayConfigError(f"{label}.args must be a list of strings.")
        enabled = spec.get("enabled", True)
        if not isinstance(enabled, bool):
            raise GatewayConfigError(f"{label}.enabled must be a boolean.")
        trust_level = spec.get("trust_level", DEFAULT_TRUST_LEVEL)
        if trust_level not in TRUST_LEVELS:
            raise GatewayConfigError(
                f"{label}.trust_level must be one of: {', '.join(sorted(TRUST_LEVELS))}."
            )
        _validate_env_allowlist(spec, label)
        cwd = spec.get("cwd")
        if cwd is not None:
            if not isinstance(cwd, str) or not os.path.isabs(cwd):
                raise GatewayConfigError(
                    f"{label}.cwd must be an absolute path (relative paths are refused)."
                )
            if not Path(cwd).is_dir():
                raise GatewayConfigError(f"{label}.cwd must be an existing directory.")
        _validate_size_limits(spec, trust_level, label)
        _validate_timeouts(spec, label)
        audit_level = spec.get("audit_level", "standard")
        if audit_level not in AUDIT_LEVELS:
            raise GatewayConfigError(
                f"{label}.audit_level must be 'minimal' or 'standard' (there is no 'off')."
            )
        tools = spec.get("tools", [])
        if not isinstance(tools, list):
            raise GatewayConfigError(f"{label}.tools must be a list.")
        for t_index, tool in enumerate(tools):
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"]:
                raise GatewayConfigError(f"{label}.tools[{t_index}] needs a string 'name'.")
    return data


def _validate_timeouts(spec: dict, label: str) -> None:
    bounds = {
        "startup_timeout_seconds": MAX_STARTUP_TIMEOUT,
        "request_timeout_seconds": MAX_REQUEST_TIMEOUT,
    }
    for key, bound in bounds.items():
        if key not in spec:
            continue
        value = spec[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise GatewayConfigError(f"{label}.{key} must be a positive number of seconds.")
        if value > bound:
            raise GatewayConfigError(
                f"{label}.{key} must be <= {bound:g} seconds (hard bound: deadlines "
                "cannot be effectively disabled by config)."
            )


def _validate_audit_settings(data: dict) -> None:
    if "audit_max_bytes" in data:
        value = data["audit_max_bytes"]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not MIN_AUDIT_MAX_BYTES <= value <= MAX_AUDIT_MAX_BYTES
        ):
            raise GatewayConfigError(
                f"config.audit_max_bytes must be an integer between {MIN_AUDIT_MAX_BYTES} "
                f"and {MAX_AUDIT_MAX_BYTES}."
            )
    if "audit_max_files" in data:
        value = data["audit_max_files"]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not MIN_AUDIT_MAX_FILES <= value <= MAX_AUDIT_MAX_FILES
        ):
            raise GatewayConfigError(
                f"config.audit_max_files must be an integer between {MIN_AUDIT_MAX_FILES} "
                f"and {MAX_AUDIT_MAX_FILES}."
            )


def _validate_env_allowlist(spec: dict, label: str) -> None:
    allowlist = spec.get("env_allowlist", [])
    if not isinstance(allowlist, list):
        raise GatewayConfigError(f"{label}.env_allowlist must be a list of variable names.")
    if len(allowlist) > MAX_ENV_ALLOWLIST:
        raise GatewayConfigError(
            f"{label}.env_allowlist has more than {MAX_ENV_ALLOWLIST} entries."
        )
    if len(set(allowlist)) != len(allowlist):
        raise GatewayConfigError(f"{label}.env_allowlist entries must be unique.")
    for entry in allowlist:
        if not isinstance(entry, str) or not ENV_NAME_RE.match(entry):
            raise GatewayConfigError(
                f"{label}.env_allowlist entries must be plain environment variable NAMES "
                f"matching {ENV_NAME_RE.pattern} -- never wildcards, never values."
            )


def _validate_size_limits(spec: dict, trust_level: str, label: str) -> None:
    schema_ceiling, response_ceiling = trust_ceilings(trust_level)
    for key, ceiling in (
        ("max_schema_bytes", schema_ceiling),
        ("max_response_bytes", response_ceiling),
    ):
        if key not in spec:
            continue
        value = spec[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < MIN_LIMIT_BYTES:
            raise GatewayConfigError(f"{label}.{key} must be an integer >= {MIN_LIMIT_BYTES}.")
        if trust_level in (TRUST_LOCAL_RESTRICTED, TRUST_LOCAL_TRUSTED) and value > ceiling:
            raise GatewayConfigError(
                f"{label}.{key} {value} exceeds the {trust_level} ceiling of {ceiling} bytes."
            )


def _under_temp_dir(command: str) -> bool:
    """True when a command path resolves under a world-writable temp root."""
    roots = {tempfile.gettempdir(), "/tmp", "/var/tmp", "/dev/shm"}
    try:
        resolved = Path(command).resolve()
    except OSError:
        return False
    for root in roots:
        try:
            if resolved.is_relative_to(Path(root).resolve()):
                return True
        except (OSError, ValueError):
            continue
    return False


class UpstreamClient:
    """One lazily-spawned upstream MCP server over subprocess stdio.

    Lifecycle: not spawned until first needed; reused while alive; answers
    are read by a background thread so every request has a hard deadline;
    terminated (then killed) on gateway shutdown or after a refusal that
    leaves the stream out of sync (timeout, garbage output).

    Security enforcement (docs/mcp-upstream-security-model.md): trust level
    and command allowlist checked before every spawn; the child environment
    is built from scratch (minimal base set + ``env_allowlist`` names only);
    the gateway's cwd is never inherited; size limits are clamped to the
    trust-level ceilings and timeouts to the hard bounds.
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
        enabled = spec.get("enabled", True)
        declared = str(spec.get("trust_level") or DEFAULT_TRUST_LEVEL)
        # enabled:false forces disabled semantics regardless of trust_level.
        self.trust_level = TRUST_DISABLED if enabled is False else declared
        schema_ceiling, response_ceiling = trust_ceilings(self.trust_level)
        self.max_schema_bytes = min(
            int(spec.get("max_schema_bytes", DEFAULT_MAX_SCHEMA_BYTES)), schema_ceiling
        )
        self.max_response_bytes = min(
            int(spec.get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES)), response_ceiling
        )
        self.startup_timeout = min(
            float(
                spec.get(
                    "startup_timeout_seconds",
                    defaults.get("startup_timeout_seconds", DEFAULT_STARTUP_TIMEOUT),
                )
            ),
            MAX_STARTUP_TIMEOUT,
        )
        self.request_timeout = min(
            float(
                spec.get(
                    "request_timeout_seconds",
                    defaults.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT),
                )
            ),
            MAX_REQUEST_TIMEOUT,
        )
        scratch_root = defaults.get("scratch_root")
        self.scratch_root = (
            Path(scratch_root)
            if scratch_root
            else Path(tempfile.gettempdir()) / "unlimited-tools-scratch"
        )

    @property
    def started(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def spawnable(self) -> bool:
        """True when the trust level permits spawning (and indexing) at all."""
        return self.trust_level in (TRUST_LOCAL_RESTRICTED, TRUST_LOCAL_TRUSTED)

    def ensure_available(self) -> None:
        """Refuse any operation that addresses a non-operable upstream."""
        if self.trust_level == TRUST_DISABLED:
            raise UpstreamError(
                f"Upstream '{self.name}' is disabled in the gateway config; "
                "enable it (enabled: true and a non-disabled trust_level) to use it.",
                code=UPSTREAM_DISABLED,
            )
        if not self.spawnable:
            raise UpstreamError(
                f"Upstream '{self.name}' has trust level '{self.trust_level}': all I/O is "
                "refused until the OAuth/remote gate (Gate A, "
                "docs/mcp-upstream-security-model.md) opens.",
                code=TRUST_LEVEL_VIOLATION,
            )

    def _validate_command(self) -> str:
        """Apply the command allowlist policy; return the command to spawn."""

        def refuse(reason: str) -> None:
            raise UpstreamError(
                f"Upstream '{self.name}' command not allowed: {reason}",
                code=COMMAND_NOT_ALLOWED,
            )

        command = str(self.spec.get("command") or "").strip()
        if not command:
            refuse("empty command.")
        base = os.path.basename(command).lower()
        if base in SHELL_COMMANDS or base.removesuffix(".exe") in SHELL_COMMANDS:
            refuse("an MCP upstream is never a shell.")
        if os.path.isabs(command):
            if self.trust_level == TRUST_LOCAL_RESTRICTED and _under_temp_dir(command):
                refuse(
                    "commands under world-writable temp directories are refused at "
                    "local-restricted."
                )
            return command
        if "/" in command or "\\" in command:
            refuse("relative paths are refused at every trust level; use an absolute path.")
        # Bare name: PATH lookup is allowed only for the fixed known-runner
        # list (in code, never config-extensible) at local-trusted.
        if self.trust_level != TRUST_LOCAL_TRUSTED:
            refuse(
                "bare command names require trust_level 'local-trusted'; "
                "use an absolute path."
            )
        if command.lower() not in KNOWN_RUNNERS:
            refuse(
                f"'{command}' is not in the built-in known-runner list "
                f"({', '.join(sorted(KNOWN_RUNNERS))}); use an absolute path."
            )
        return command

    def _build_env(self) -> dict[str, str]:
        """Child environment: minimal base set plus env_allowlist names only.

        Values are copied from the gateway's own environment and never logged.
        Names listed but unset in the parent environment are skipped silently.
        """
        allowlist = self.spec.get("env_allowlist") or []
        if not isinstance(allowlist, list) or len(allowlist) > MAX_ENV_ALLOWLIST:
            raise UpstreamError(
                f"Upstream '{self.name}' env_allowlist must be a list of at most "
                f"{MAX_ENV_ALLOWLIST} variable names.",
                code=ENV_FORWARDING_DENIED,
            )
        names: list[str] = []
        for entry in allowlist:
            if not isinstance(entry, str) or not ENV_NAME_RE.match(entry):
                raise UpstreamError(
                    f"Upstream '{self.name}' env_allowlist contains an entry that is not a "
                    "plain environment variable name; wildcards and literal values are "
                    "never forwarded.",
                    code=ENV_FORWARDING_DENIED,
                )
            names.append(entry)
        env: dict[str, str] = {}
        for name in (*BASE_ENV_VARS, *names):
            value = os.environ.get(name)
            if value is not None:
                env[name] = value
        return env

    def _resolve_cwd(self) -> Path:
        """Explicit absolute cwd, or a managed per-upstream scratch directory.

        The gateway's own working directory is never inherited, so a hostile
        upstream cannot discover the user's project location via getcwd().
        """
        explicit = self.spec.get("cwd")
        if explicit:
            path = Path(str(explicit))
            if not path.is_absolute() or not path.is_dir():
                raise UpstreamError(
                    f"Upstream '{self.name}' cwd must be an absolute path to an existing "
                    "directory.",
                    code=COMMAND_NOT_ALLOWED,
                )
            return path
        scratch = self.scratch_root / self.name
        scratch.mkdir(parents=True, exist_ok=True)
        return scratch

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
        self.ensure_available()
        command = self._validate_command()
        env = self._build_env()
        cwd = self._resolve_cwd()
        try:
            self.process = subprocess.Popen(
                # argv vector only: no shell, no string interpolation, ever.
                [command, *(self.spec.get("args") or [])],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                cwd=str(cwd),
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
            schema = tool.get("inputSchema") or {"type": "object"}
            schema_bytes = _payload_bytes(schema)
            entry: dict[str, Any] = {"description": str(tool.get("description") or "")}
            if schema_bytes > self.max_schema_bytes:
                # Indexed by name/description only and marked oversized: search
                # still finds it, but the schema can only ever be refused.
                entry["schema_oversized"] = True
                entry["schema_bytes"] = schema_bytes
            else:
                entry["inputSchema"] = schema
            self.tools[name] = entry
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
        if "audit_max_bytes" in config:
            audit.max_bytes = int(config["audit_max_bytes"])
        if "audit_max_files" in config:
            audit.max_files = int(config["audit_max_files"])
        defaults = {
            "startup_timeout_seconds": config.get("startup_timeout_seconds", DEFAULT_STARTUP_TIMEOUT),
            "request_timeout_seconds": config.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT),
            # Per-upstream scratch cwd lives next to the audit log (the
            # library runtime dir by default); the gateway cwd is never used.
            "scratch_root": Path(audit.path).parent / "mcp-scratch",
        }
        self.upstreams: dict[str, UpstreamClient] = {
            spec["name"]: UpstreamClient(spec, defaults) for spec in config.get("upstreams", [])
        }

    def audit_level_for(self, upstream_name: str) -> str:
        client = self.upstreams.get(upstream_name)
        if client is None:
            return "standard"
        level = str(client.spec.get("audit_level") or "standard")
        return level if level in AUDIT_LEVELS else "standard"

    def iter_indexed_tools(self) -> Iterable[tuple[str, str, str]]:
        """Yield (upstream, tool, description) from static config plus live indexes.

        Disabled and future-remote-placeholder upstreams are never indexed and
        never appear -- including their pre-declared ``tools`` entries.
        """
        for upstream_name, client in self.upstreams.items():
            if not client.spawnable:
                continue
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
                if client.spawnable:  # disabled/placeholder upstreams are never spawned
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
        client.ensure_available()
        client.ensure_indexed()
        info = client.tools.get(tool_name)
        if info is None:
            raise ToolError(f"Upstream '{client.name}' has no tool named '{tool_name}'.")
        if info.get("schema_oversized") or "inputSchema" not in info:
            actual = info.get("schema_bytes", "unknown")
            raise UpstreamError(
                f"Schema for '{client.name}.{tool_name}' is {actual} bytes, over the "
                f"{client.max_schema_bytes} byte limit for this upstream; refused, "
                "never truncated.",
                code=SCHEMA_TOO_LARGE,
            )
        schema = info["inputSchema"]
        schema_bytes = _payload_bytes(schema)
        if schema_bytes > client.max_schema_bytes:  # defense in depth for live indexes
            raise UpstreamError(
                f"Schema for '{client.name}.{tool_name}' is {schema_bytes} bytes, over the "
                f"{client.max_schema_bytes} byte limit for this upstream; refused, "
                "never truncated.",
                code=SCHEMA_TOO_LARGE,
            )
        return {
            "tool": f"{client.name}.{tool_name}",
            "description": info["description"],
            "inputSchema": schema,
        }

    def tools_call(self, arguments: dict) -> dict:
        client, tool_name = self._split_fq(arguments)
        call_arguments = arguments.get("arguments")
        if call_arguments is None:
            call_arguments = {}
        if not isinstance(call_arguments, dict):
            raise ToolError("arguments must be an object.")
        client.ensure_available()
        client.ensure_indexed()
        if tool_name not in client.tools:
            raise ToolError(f"Upstream '{client.name}' has no tool named '{tool_name}'.")
        result = client.request("tools/call", {"name": tool_name, "arguments": call_arguments})
        result_bytes = _payload_bytes(result)
        if result_bytes > client.max_response_bytes:
            # The result is dropped, never trimmed: half a result is worse
            # than no result, and the refusal message never embeds content.
            raise UpstreamError(
                f"Result from '{client.name}.{tool_name}' is {result_bytes} bytes, over the "
                f"{client.max_response_bytes} byte limit for this upstream; dropped, "
                "never truncated.",
                code=RESPONSE_TOO_LARGE,
            )
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
            # At audit_level 'minimal' even the redacted args shape and the
            # error string are dropped: ts/tool/upstream/duration_ms/ok only.
            upstream = _upstream_of(arguments)
            minimal = gateway.audit_level_for(upstream) == "minimal"
            gateway.audit.record(
                tool=meta_tool,
                upstream=upstream,
                duration_ms=(time.monotonic() - start) * 1000.0,
                ok=ok,
                arguments=None if minimal else arguments,
                error="" if minimal else error,
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
