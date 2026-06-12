"""Claude Code MCP gateway installer helpers.

This module edits Claude Code MCP configuration files, not Claude Code skills.
It is intentionally conservative: existing MCP servers remain active and are
never moved into the gateway config automatically because the gateway's v1
security model stores only env variable names, never literal env values.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .audit import scrub_paths

SERVER_NAME = "unlimited-tools"
PROJECT_CONFIG_NAME = ".mcp.json"
PROJECT_GATEWAY_CONFIG = Path(".unlimited-skills") / "mcp" / "claude-code-gateway.json"
GLOBAL_GATEWAY_CONFIG = Path(".unlimited-skills") / "mcp" / "claude-code-gateway.json"

_GATEWAY_ARGS_PREFIX = ["mcp", "gateway", "--config"]
_HIDDEN_ENTRY = "(existing entry, content hidden)"


@dataclass(frozen=True)
class ClaudeCodeMcpOptions:
    scope: str
    project_root: Path
    claude_config: Path
    gateway_config: Path | None = None
    dry_run: bool = False
    force: bool = False
    json_output: bool = False


class ClaudeCodeMcpError(RuntimeError):
    """A safe user-facing refusal for MCP config edits."""


def default_claude_config(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".claude.json"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8").lstrip("\ufeff"))
    except json.JSONDecodeError as exc:
        raise ClaudeCodeMcpError(f"{path.name} is not valid JSON; refusing to modify it") from exc
    if not isinstance(payload, dict):
        raise ClaudeCodeMcpError(f"{path.name} must contain a JSON object")
    return payload


def _dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = _dump_json(payload)
    json.loads(rendered)
    tmp = path.with_name(f".{path.name}.{_timestamp()}.tmp")
    tmp.write_text(rendered, encoding="utf-8")
    os.replace(tmp, path)


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stem = f"{path.name}.{_timestamp()}"
    backup = path.with_name(f"{stem}.back")
    suffix = 1
    while backup.exists():
        backup = path.with_name(f"{stem}-{suffix}.back")
        suffix += 1
    shutil.copy2(path, backup)
    return backup


def _is_gateway_entry(entry: Any) -> bool:
    """True only for the exact entry shape this installer generates.

    Anything else -- including a same-named entry with extra keys, a foreign
    command, or non-string args -- is treated as foreign content and never
    rendered into the diff.
    """
    return (
        isinstance(entry, dict)
        and set(entry) == {"command", "args"}
        and entry.get("command") == "unlimited-skills"
        and isinstance(entry.get("args"), list)
        and len(entry["args"]) == len(_GATEWAY_ARGS_PREFIX) + 1
        and entry["args"][: len(_GATEWAY_ARGS_PREFIX)] == _GATEWAY_ARGS_PREFIX
        and isinstance(entry["args"][len(_GATEWAY_ARGS_PREFIX)], str)
    )


def _render_entry_lines(entry: Any) -> list[str]:
    """Render ONLY our server entry as JSON lines for the diff.

    Our generated entry contains no secrets by construction; its single free
    string (the gateway config path) is still path-scrubbed. Any entry that
    is not byte-for-byte our shape is replaced by a placeholder so foreign
    content never reaches the output under any key.
    """
    if entry is None:
        return _dump_json({}).splitlines()
    if _is_gateway_entry(entry):
        rendered: Any = {
            "command": entry["command"],
            "args": entry["args"][:-1] + [scrub_paths(entry["args"][-1])],
        }
    else:
        rendered = _HIDDEN_ENTRY
    return _dump_json({SERVER_NAME: rendered}).splitlines()


def _safe_diff(before: dict[str, Any], after: dict[str, Any], *, fromfile: str, tofile: str) -> str:
    """A privacy-safe unified diff of OUR entry only.

    Other MCP servers are summarized by name, never by content, so secrets
    in foreign server definitions (args, env, headers, anything) can not
    leak into human or --json output.
    """
    before_servers = before.get("mcpServers") if isinstance(before.get("mcpServers"), dict) else {}
    after_servers = after.get("mcpServers") if isinstance(after.get("mcpServers"), dict) else {}
    lines = list(
        difflib.unified_diff(
            _render_entry_lines(before_servers.get(SERVER_NAME)),
            _render_entry_lines(after_servers.get(SERVER_NAME)),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )
    other_names = sorted(
        str(name) for name in {**before_servers, **after_servers} if name != SERVER_NAME
    )
    if other_names:
        lines.append(
            f"(unchanged, hidden: {len(other_names)} other MCP server(s): {', '.join(other_names)})"
        )
    return "\n".join(lines)


def _resolve_paths(options: ClaudeCodeMcpOptions) -> tuple[Path, Path, str]:
    project_root = options.project_root.expanduser().resolve()
    if options.scope == "global":
        config_path = options.claude_config.expanduser().resolve()
        if options.gateway_config is not None:
            gateway_path = options.gateway_config.expanduser().resolve()
            gateway_arg = str(gateway_path)
        else:
            # Keep the global entry portable: write a "~/..." literal instead
            # of this machine's absolute home path. The gateway CLI and
            # load_gateway_config() both expanduser() the --config argument.
            gateway_path = (Path.home() / GLOBAL_GATEWAY_CONFIG).resolve()
            gateway_arg = "~/" + GLOBAL_GATEWAY_CONFIG.as_posix()
    else:
        config_path = project_root / PROJECT_CONFIG_NAME
        gateway_path = (options.gateway_config or (project_root / PROJECT_GATEWAY_CONFIG)).expanduser().resolve()
        try:
            gateway_arg = str(gateway_path.relative_to(project_root)).replace("\\", "/")
        except ValueError:
            gateway_arg = str(gateway_path)
    return config_path, gateway_path, gateway_arg


def _gateway_server(gateway_arg: str) -> dict[str, Any]:
    return {
        "command": "unlimited-skills",
        "args": ["mcp", "gateway", "--config", gateway_arg],
    }


def _ensure_gateway_config_payload(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return {"schema_version": 1, "upstreams": []}, True
    payload = _load_json_file(path)
    if "schema_version" not in payload:
        payload["schema_version"] = 1
    if "upstreams" not in payload:
        payload["upstreams"] = []
    if not isinstance(payload.get("upstreams"), list):
        raise ClaudeCodeMcpError("gateway config upstreams must be a list")
    return payload, False


def install_claude_code_gateway(options: ClaudeCodeMcpOptions) -> dict[str, Any]:
    config_path, gateway_path, gateway_arg = _resolve_paths(options)
    before = _load_json_file(config_path)
    after = copy.deepcopy(before)
    servers = after.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ClaudeCodeMcpError(f"{config_path.name} mcpServers must be an object")

    desired = _gateway_server(gateway_arg)
    existing = servers.get(SERVER_NAME)
    if existing == desired:
        changed = False
    elif existing is not None and not options.force:
        raise ClaudeCodeMcpError(
            f"{SERVER_NAME} already exists with different settings; rerun with --force to replace only that server"
        )
    else:
        servers[SERVER_NAME] = desired
        changed = True

    gateway_payload, gateway_created = _ensure_gateway_config_payload(gateway_path)
    config_diff = _safe_diff(before, after, fromfile="before", tofile="after") if changed else ""

    report = {
        "action": "install",
        "scope": options.scope,
        "target": "global .claude.json" if options.scope == "global" else "project .mcp.json",
        "server_name": SERVER_NAME,
        "changed": changed,
        "idempotent": not changed and not gateway_created,
        "dry_run": options.dry_run,
        "backup_created": False,
        "backup_file": None,
        "backup_path": None,
        "gateway_config_created": gateway_created,
        "diff": config_diff,
        "next_steps": [
            "Restart Claude Code so it reloads MCP servers.",
            "Run `unlimited-skills mcp savings` to compare standing context cost.",
            "Add upstreams to the gateway config manually or with a future migration command; env values are never copied automatically.",
        ],
    }
    if options.dry_run:
        return report

    backup = _backup(config_path) if config_path.exists() and changed else None
    if changed:
        _atomic_write_json(config_path, after)
    if gateway_created:
        _atomic_write_json(gateway_path, gateway_payload)
    report["backup_created"] = backup is not None
    report["backup_file"] = backup.name if backup is not None else None
    report["backup_path"] = str(backup) if backup is not None else None
    return report


def uninstall_claude_code_gateway(options: ClaudeCodeMcpOptions) -> dict[str, Any]:
    config_path, _gateway_path, _gateway_arg = _resolve_paths(options)
    before = _load_json_file(config_path)
    after = copy.deepcopy(before)
    servers = after.get("mcpServers")
    if servers is None:
        changed = False
    elif not isinstance(servers, dict):
        raise ClaudeCodeMcpError(f"{config_path.name} mcpServers must be an object")
    else:
        changed = SERVER_NAME in servers
        servers.pop(SERVER_NAME, None)

    report = {
        "action": "uninstall",
        "scope": options.scope,
        "target": "global .claude.json" if options.scope == "global" else "project .mcp.json",
        "server_name": SERVER_NAME,
        "changed": changed,
        "idempotent": not changed,
        "dry_run": options.dry_run,
        "backup_created": False,
        "backup_file": None,
        "backup_path": None,
        "diff": _safe_diff(before, after, fromfile="before", tofile="after") if changed else "",
        "next_steps": ["Restart Claude Code so it reloads MCP servers."],
    }
    if options.dry_run:
        return report
    backup = _backup(config_path) if config_path.exists() and changed else None
    if changed:
        _atomic_write_json(config_path, after)
    report["backup_created"] = backup is not None
    report["backup_file"] = backup.name if backup is not None else None
    report["backup_path"] = str(backup) if backup is not None else None
    return report


def claude_code_gateway_status(options: ClaudeCodeMcpOptions) -> dict[str, Any]:
    project_options = ClaudeCodeMcpOptions(
        scope="project",
        project_root=options.project_root,
        claude_config=options.claude_config,
        gateway_config=options.gateway_config,
    )
    global_options = ClaudeCodeMcpOptions(
        scope="global",
        project_root=options.project_root,
        claude_config=options.claude_config,
        gateway_config=options.gateway_config if options.scope == "global" else None,
    )
    entries = []
    for item in (project_options, global_options):
        config_path, gateway_path, _gateway_arg = _resolve_paths(item)
        configured = False
        valid = True
        try:
            payload = _load_json_file(config_path)
            servers = payload.get("mcpServers") or {}
            configured = isinstance(servers, dict) and SERVER_NAME in servers
        except ClaudeCodeMcpError:
            valid = False
        entries.append(
            {
                "scope": item.scope,
                "target": "global .claude.json" if item.scope == "global" else "project .mcp.json",
                "config_exists": config_path.exists(),
                "config_valid_json": valid,
                "configured": configured,
                "gateway_config_exists": gateway_path.exists(),
            }
        )
    return {"action": "status", "server_name": SERVER_NAME, "entries": entries}


def format_claude_code_gateway_report(report: dict[str, Any]) -> str:
    if report.get("action") == "status":
        lines = [f"Claude Code MCP gateway status ({SERVER_NAME}):"]
        for entry in report["entries"]:
            state = "configured" if entry["configured"] else "not configured"
            valid = "valid" if entry["config_valid_json"] else "invalid JSON"
            lines.append(
                f"- {entry['scope']}: {state}; config={entry['config_exists']} ({valid}); "
                f"gateway_config={entry['gateway_config_exists']}"
            )
        return "\n".join(lines)

    changed = "changed" if report["changed"] else "already up to date"
    if report["dry_run"]:
        changed = "would change" if report["changed"] else "would leave unchanged"
    lines = [
        f"Claude Code MCP gateway {report['action']}: {changed}",
        f"- scope: {report['scope']}",
        f"- target: {report['target']}",
        f"- server: {report['server_name']}",
        f"- backup created: {report['backup_created']}",
    ]
    if report.get("backup_file"):
        lines.append(f"- backup file: {report.get('backup_path') or report['backup_file']}")
    if report["action"] == "install":
        lines.append(f"- gateway config created: {report['gateway_config_created']}")
    if report.get("diff"):
        lines.extend(["", "Redacted dry-run diff:" if report["dry_run"] else "Redacted diff:", report["diff"]])
    if report.get("next_steps"):
        lines.append("")
        lines.append("Next steps:")
        lines.extend(f"- {item}" for item in report["next_steps"])
    return "\n".join(lines)
