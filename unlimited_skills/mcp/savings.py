"""Measure the standing MCP context cost of the user's real Claude Code setup.

``unlimited-skills mcp savings`` answers one question with the user's own
numbers: how many bytes/tokens of upstream MCP tool schemas load into EVERY
session right now, and what would the same session cost behind the Unlimited
Tools gateway (3 meta-tools)?

How it works:

1. Discover configured MCP servers from the user's Claude Code configuration:
   the top-level ``mcpServers`` map in ``~/.claude.json``, every per-project
   ``mcpServers`` section in the same file, and each project's ``.mcp.json``
   when the project directory is reachable.
2. For each stdio server, spawn it exactly the way the host would (same
   command, args, and configured env), run the MCP ``initialize`` handshake,
   request ``tools/list``, and measure the full listing payload in bytes --
   that payload (names + descriptions + complete input schemas) is what the
   host pays at session start. The stdio client is the gateway's own
   :class:`~unlimited_skills.mcp.gateway.UpstreamClient`.
3. Compare the summed standing cost against the gateway's own measured
   ``tools/list`` (only the 3 meta-tool schemas), recomputed live.

Token estimate heuristic: ``est_tokens = bytes // 4`` -- roughly 4 bytes per
token for English JSON payloads. It is an estimate for orientation, not an
exact tokenizer count.

Privacy boundary: everything runs locally and nothing is uploaded. The
report contains only server names, tool counts, byte sizes, and fixed status
strings -- never schema contents, never spawn commands or args, never env
names or values. Configured env values are forwarded to the measured child
process exactly like the host forwards them, and are never logged or
printed. A snapshot of the numbers is appended to the local learning log
(``<root>/.learning/events.jsonl``).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .gateway import SHELL_COMMANDS, UpstreamClient

# ~4 bytes per token for English JSON payloads (see module docstring).
TOKEN_BYTES = 4

# Per-server measurement deadline (seconds): spawn + handshake and the
# tools/list round-trip each get this budget. An unreachable or slow server
# becomes a "skipped (not reachable)" row, never a failure.
DEFAULT_SERVER_TIMEOUT = 12.0

# Lab benchmark fallback (docs/unlimited-tools.md, tests/test_mcp_context_budget.py):
# 40 fake tools with realistic ~2 KB schemas vs the gateway's 3 meta-tools.
LAB_FULL_DUMP_BYTES = 90_420
LAB_GATEWAY_BYTES = 1_268

STATUS_OK = "ok"
STATUS_NOT_REACHABLE = "skipped (not reachable)"
STATUS_REMOTE = "skipped (remote server; not measured)"
STATUS_UNSUPPORTED = "skipped (unsupported command)"


@dataclass
class DiscoveredServer:
    """One MCP server entry from the user's own host configuration."""

    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"
    source: str = "user config"


class MeasurementSkip(RuntimeError):
    """The server cannot be measured; carries a fixed privacy-safe status."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def _server_entries(block: dict, source: str) -> list[DiscoveredServer]:
    servers: list[DiscoveredServer] = []
    if not isinstance(block, dict):
        return servers
    for name, spec in block.items():
        if not isinstance(name, str) or not name or not isinstance(spec, dict):
            continue
        transport = str(spec.get("type") or spec.get("transport") or "stdio").lower()
        env = spec.get("env")
        servers.append(
            DiscoveredServer(
                name=name,
                command=str(spec.get("command") or ""),
                args=[str(item) for item in spec.get("args") or [] if isinstance(item, (str, int, float))],
                env={
                    str(key): str(value)
                    for key, value in (env.items() if isinstance(env, dict) else [])
                },
                transport=transport,
                source=source,
            )
        )
    return servers


def discover_mcp_servers(
    claude_json_path: Path | None = None,
    *,
    home: Path | None = None,
) -> list[DiscoveredServer]:
    """Discover MCP servers from the user's real Claude Code configuration.

    Reads the top-level ``mcpServers`` of ``~/.claude.json``, each
    per-project ``mcpServers`` section, and each known project's ``.mcp.json``
    when that file exists. First occurrence of a server name wins (top-level
    user config beats project sections). A missing or malformed config file
    is simply zero servers, never an error.
    """
    home = home or Path.home()
    path = claude_json_path or home / ".claude.json"
    servers: list[DiscoveredServer] = []
    seen: set[str] = set()

    def add(entries: list[DiscoveredServer]) -> None:
        for entry in entries:
            if entry.name in seen:
                continue
            seen.add(entry.name)
            servers.append(entry)

    data: dict = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8", errors="replace").lstrip("﻿"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, json.JSONDecodeError):
        data = {}

    add(_server_entries(data.get("mcpServers") or {}, "user config"))

    projects = data.get("projects")
    project_dirs: list[Path] = []
    if isinstance(projects, dict):
        for project_path, project_spec in projects.items():
            if isinstance(project_path, str) and project_path:
                project_dirs.append(Path(project_path))
            if isinstance(project_spec, dict):
                add(_server_entries(project_spec.get("mcpServers") or {}, "project config"))

    for project_dir in project_dirs:
        mcp_json = project_dir / ".mcp.json"
        try:
            if not mcp_json.is_file():
                continue
            loaded = json.loads(
                mcp_json.read_text(encoding="utf-8", errors="replace").lstrip("﻿")
            )
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(loaded, dict):
            add(_server_entries(loaded.get("mcpServers") or {}, "project .mcp.json"))

    return servers


def resolve_spawn(command: str, args: list[str]) -> tuple[str, list[str]]:
    """Normalize a host config command into a directly spawnable argv head.

    - ``cmd /c X ...`` wrappers (common in Windows Claude Code configs) are
      unwrapped to ``X ...``;
    - shell invocations that cannot be unwrapped are refused
      (:data:`STATUS_UNSUPPORTED`) -- a measurement never runs a shell string;
    - bare command names are resolved through PATH (``shutil.which``);
    - an unresolvable command is :data:`STATUS_NOT_REACHABLE`.
    """
    command = str(command or "").strip()
    if not command:
        raise MeasurementSkip(STATUS_NOT_REACHABLE)
    base = os.path.basename(command).lower()
    if base in SHELL_COMMANDS or base.removesuffix(".exe") in SHELL_COMMANDS:
        # `cmd /c X args...` keeps a tokenized argv, so the wrapped command
        # can be spawned directly. POSIX `sh -c "one opaque string"` cannot
        # be decomposed safely and is never run.
        flag = args[0].strip().lower() if args else ""
        inner = args[1] if len(args) >= 2 else ""
        inner_base = os.path.basename(inner).lower()
        # One argv token that is itself a command: an absolute path (which may
        # contain spaces) or a single bare name. Anything that smells like an
        # opaque shell string (metacharacters, spaced non-path strings) or a
        # nested shell is refused.
        single_command = bool(inner) and (os.path.isabs(inner) or " " not in inner)
        has_metachars = any(ch in inner for ch in "|&<>^;\"'")
        if (
            flag == "/c"
            and single_command
            and not has_metachars
            and inner_base not in SHELL_COMMANDS
            and inner_base.removesuffix(".exe") not in SHELL_COMMANDS
        ):
            return resolve_spawn(inner, list(args[2:]))
        raise MeasurementSkip(STATUS_UNSUPPORTED)
    if os.path.isabs(command):
        return command, list(args)
    if "/" in command or "\\" in command:
        # Relative paths depend on an unknowable host cwd; not measurable.
        raise MeasurementSkip(STATUS_UNSUPPORTED)
    resolved = shutil.which(command)
    if not resolved:
        raise MeasurementSkip(STATUS_NOT_REACHABLE)
    return resolved, list(args)


class _MeasurementClient(UpstreamClient):
    """The gateway's stdio client, adapted to reproduce the host's spawn.

    Two deliberate differences from gateway enforcement, both safe because
    the measured command and env come from the user's OWN host config -- the
    exact process the host itself starts at every session:

    - the command was pre-resolved by :func:`resolve_spawn` (PATH lookup is
      allowed for any binary the host would run, shells stay refused);
    - the literal configured ``env`` map is forwarded to the child like the
      host forwards it. Values are never logged or printed anywhere.
    """

    def __init__(self, spec: dict, configured_env: dict[str, str], defaults: dict) -> None:
        super().__init__(spec, defaults)
        self._configured_env = dict(configured_env)

    def _validate_command(self) -> str:  # pre-validated by resolve_spawn
        return str(self.spec.get("command") or "")

    def _build_env(self) -> dict[str, str]:
        env = super()._build_env()
        env.update(self._configured_env)
        return env


def payload_bytes(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def estimate_tokens(size_bytes: int) -> int:
    return int(size_bytes) // TOKEN_BYTES


def measure_server(server: DiscoveredServer, *, timeout: float = DEFAULT_SERVER_TIMEOUT) -> dict:
    """Measure one configured server's full ``tools/list`` payload.

    Returns a privacy-safe row: name, status, tool count, bytes, est tokens.
    Never raises for an unreachable server.
    """

    def row(status: str, tools_count: int = 0, schema_bytes: int = 0) -> dict:
        return {
            "name": server.name,
            "status": status,
            "tools_count": tools_count,
            "schema_bytes": schema_bytes,
            "est_tokens": estimate_tokens(schema_bytes),
        }

    if server.transport not in {"stdio", ""}:
        return row(STATUS_REMOTE)
    try:
        command, args = resolve_spawn(server.command, server.args)
    except MeasurementSkip as skip:
        return row(skip.status)

    spec = {
        "name": server.name,
        "command": command,
        "args": args,
        "trust_level": "local-trusted",
        # Measurement must see the full listing; the ceilings still apply.
        "max_schema_bytes": 1024 * 1024,
        "max_response_bytes": 8 * 1024 * 1024,
    }
    defaults = {
        "startup_timeout_seconds": timeout,
        "request_timeout_seconds": timeout,
        "scratch_root": Path(tempfile.gettempdir()) / "unlimited-skills-savings-scratch",
    }
    client = _MeasurementClient(spec, server.env, defaults)
    try:
        client.start()
        result = client.request("tools/list", {}, timeout=timeout)
        listing = result.get("tools") if isinstance(result, dict) else None
        tools = [tool for tool in listing if isinstance(tool, dict)] if isinstance(listing, list) else []
        return row(STATUS_OK, tools_count=len(tools), schema_bytes=payload_bytes(tools))
    except Exception:
        # Spawn failure, handshake refusal, timeout, garbage output: the
        # server is simply not measurable right now.
        return row(STATUS_NOT_REACHABLE)
    finally:
        client.terminate()


def measure_gateway_standing_cost() -> int:
    """Recompute the gateway's standing context cost (3 meta-tools) live."""
    from .audit import AuditLog
    from .gateway import Gateway, build_gateway_registry
    from .protocol import StdioServer

    # No upstreams, no profile: nothing spawns and the audit log is never
    # written to (no calls happen) -- this only sizes the meta-tool listing.
    audit_path = Path(tempfile.gettempdir()) / "unlimited-skills-savings-audit-never-written.jsonl"
    gateway = Gateway({"upstreams": []}, AuditLog(audit_path))
    server = StdioServer(build_gateway_registry(gateway), server_name="unlimited-tools-gateway")
    return payload_bytes(server.list_tools())


def build_savings_report(
    servers: list[DiscoveredServer],
    *,
    timeout: float = DEFAULT_SERVER_TIMEOUT,
    measure_fn: Callable[..., dict] | None = None,
    gateway_bytes: int | None = None,
) -> dict:
    """Build the machine-readable savings report (the ``--json`` document)."""
    measure = measure_fn or measure_server
    rows = [measure(server, timeout=timeout) for server in servers]
    total_bytes = sum(row["schema_bytes"] for row in rows if row["status"] == STATUS_OK)
    if gateway_bytes is None:
        gateway_bytes = measure_gateway_standing_cost()
    measured = sum(1 for row in rows if row["status"] == STATUS_OK)
    savings_bytes = total_bytes - gateway_bytes if measured else 0
    savings_pct = round(savings_bytes / total_bytes * 100.0, 1) if total_bytes else 0.0
    report = {
        "servers": rows,
        "measured_servers": measured,
        "skipped_servers": len(rows) - measured,
        "total_bytes": total_bytes,
        "total_est_tokens": estimate_tokens(total_bytes),
        "gateway_bytes": gateway_bytes,
        "gateway_est_tokens": estimate_tokens(gateway_bytes),
        "savings_bytes": savings_bytes,
        "savings_pct": savings_pct,
        "token_heuristic": f"est_tokens = bytes / {TOKEN_BYTES} (approximate)",
    }
    if not measured:
        report["benchmark"] = {
            "note": (
                "lab benchmark: 40 upstream tools with realistic ~2 KB schemas "
                "(docs/unlimited-tools.md)"
            ),
            "full_dump_bytes": LAB_FULL_DUMP_BYTES,
            "gateway_bytes": LAB_GATEWAY_BYTES,
            "savings_pct": round((LAB_FULL_DUMP_BYTES - LAB_GATEWAY_BYTES) / LAB_FULL_DUMP_BYTES * 100.0, 1),
        }
    return report


def event_snapshot(report: dict) -> dict:
    """The numbers-only snapshot appended to the local learning events log."""
    return {
        "servers": [
            {
                "name": row["name"],
                "status": row["status"],
                "tools_count": row["tools_count"],
                "schema_bytes": row["schema_bytes"],
            }
            for row in report["servers"]
        ],
        "total_bytes": report["total_bytes"],
        "total_est_tokens": report["total_est_tokens"],
        "gateway_bytes": report["gateway_bytes"],
        "savings_bytes": report["savings_bytes"],
        "savings_pct": report["savings_pct"],
    }


def format_savings_text(report: dict) -> str:
    """Human-readable savings report. Local-only; nothing here is uploaded."""
    lines = [
        "MCP context savings (measured locally; nothing is uploaded)",
        "",
        "This runs your configured MCP servers locally to measure tool schemas.",
        "Nothing is uploaded. Unreachable servers are skipped.",
        "Use --json for a machine-readable local report.",
        "",
    ]
    rows = report["servers"]
    if not rows:
        benchmark = report.get("benchmark") or {}
        lines.extend(
            [
                "No MCP servers configured in your Claude Code config -- here's the lab benchmark:",
                f"  full all-schemas dump: {benchmark.get('full_dump_bytes', LAB_FULL_DUMP_BYTES):,} bytes",
                f"  gateway (3 meta-tools): {benchmark.get('gateway_bytes', LAB_GATEWAY_BYTES):,} bytes",
                f"  savings: {benchmark.get('savings_pct', 98.6)}%",
                "",
                "Once you add MCP servers, rerun `unlimited-skills mcp savings` for your own numbers.",
            ]
        )
        return "\n".join(lines)
    lines.append("Configured MCP servers:")
    name_width = max(len(row["name"]) for row in rows)
    for row in rows:
        if row["status"] == STATUS_OK:
            lines.append(
                f"  {row['name']:<{name_width}}  {row['tools_count']:>3} tools  "
                f"{row['schema_bytes']:>9,} bytes  (~{row['est_tokens']:,} tokens)"
            )
        else:
            lines.append(f"  {row['name']:<{name_width}}  {row['status']}")
    lines.append("")
    if report["measured_servers"]:
        lines.extend(
            [
                f"Right now: ~{report['total_est_tokens']:,} tokens of MCP tool schemas load into every session.",
                f"With the Unlimited Tools gateway: ~{report['gateway_est_tokens']:,} tokens (3 meta-tools).",
                f"Savings: ~{max(report['savings_bytes'], 0) // TOKEN_BYTES:,} tokens per session ({report['savings_pct']}%).",
                "",
                f"Token estimate: {report['token_heuristic']}.",
            ]
        )
        if report["savings_bytes"] <= 0:
            lines.append(
                "Note: with this few measured tools the gateway's 3 meta-tools cost about the same; "
                "savings grow with every additional server."
            )
    else:
        benchmark = report.get("benchmark") or {}
        lines.extend(
            [
                "No server could be measured right now (see statuses above) -- lab benchmark instead:",
                f"  full all-schemas dump: {benchmark.get('full_dump_bytes', LAB_FULL_DUMP_BYTES):,} bytes",
                f"  gateway (3 meta-tools): {benchmark.get('gateway_bytes', LAB_GATEWAY_BYTES):,} bytes",
                f"  savings: {benchmark.get('savings_pct', 98.6)}%",
            ]
        )
    lines.extend(
        [
            "",
            "Next step -- put the gateway in front of these servers:",
            "  unlimited-skills mcp gateway --config ~/.unlimited-skills/gateway-config.json",
            "See docs/unlimited-tools.md for the Claude Code .mcp.json registration example.",
        ]
    )
    return "\n".join(lines)
