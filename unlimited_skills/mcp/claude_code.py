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
import re
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

SENSITIVE_KEY_RE = re.compile(
    r"(token|secret|key|password|proof|auth|credential|cookie|session|signature|cert|private|env)",
    re.IGNORECASE,
)


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
    backup = path.with_name(f"{path.name}.{_timestamp()}.back")
    shutil.copy2(path, backup)
    return backup


def _redact_for_output(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if SENSITIVE_KEY_RE.search(key_text):
                if isinstance(item, dict):
                    redacted[key_text] = {str(child): "[redacted]" for child in item}
                elif isinstance(item, list):
                    redacted[key_text] = ["[redacted]" for _ in item]
                else:
                    redacted[key_text] = "[redacted]"
            else:
                redacted[key_text] = _redact_for_output(item, parent_key=key_text)
        return redacted
    if isinstance(value, list):
        return [_redact_for_output(item, parent_key=parent_key) for item in value]
    if isinstance(value, str):
        if SENSITIVE_KEY_RE.search(parent_key):
            return "[redacted]"
        return scrub_paths(value)
    return value


def _safe_diff(before: dict[str, Any], after: dict[str, Any], *, fromfile: str, tofile: str) -> str:
    before_text = _dump_json(_redact_for_output(before)).splitlines()
    after_text = _dump_json(_redact_for_output(after)).splitlines()
    return "\n".join(
        difflib.unified_diff(before_text, after_text, fromfile=fromfile, tofile=tofile, lineterm="")
    )


def _resolve_paths(options: ClaudeCodeMcpOptions) -> tuple[Path, Path, str]:
    project_root = options.project_root.expanduser().resolve()
    if options.scope == "global":
        config_path = options.claude_config.expanduser().resolve()
        gateway_path = (options.gateway_config or (Path.home() / GLOBAL_GATEWAY_CONFIG)).expanduser().resolve()
        gateway_arg = str(gateway_path)
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
        "diff": _safe_diff(before, after, fromfile="before", tofile="after") if changed else "",
        "next_steps": ["Restart Claude Code so it reloads MCP servers."],
    }
    if options.dry_run:
        return report
    backup = _backup(config_path) if config_path.exists() and changed else None
    if changed:
        _atomic_write_json(config_path, after)
    report["backup_created"] = backup is not None
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
    if report["action"] == "install":
        lines.append(f"- gateway config created: {report['gateway_config_created']}")
    if report.get("diff"):
        lines.extend(["", "Redacted dry-run diff:" if report["dry_run"] else "Redacted diff:", report["diff"]])
    if report.get("next_steps"):
        lines.append("")
        lines.append("Next steps:")
        lines.extend(f"- {item}" for item in report["next_steps"])
    return "\n".join(lines)
