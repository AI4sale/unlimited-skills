"""One-command Claude Code installer for the Unlimited Tools MCP gateway.

``unlimited-skills mcp install --claude-code`` writes the gateway's server
entry into the user's Claude Code MCP configuration -- the exact same places
:mod:`unlimited_skills.mcp.savings` already reads:

- ``--project`` (the default): ``./.mcp.json`` in the current directory;
- ``--global``: the top-level ``mcpServers`` map of ``~/.claude.json``.

The written entry is host-portable and pip-install-clean -- it invokes the
``unlimited-skills`` console script from PATH and references the gateway
config as a literal ``~/...`` path (the gateway CLI ``expanduser()``s it), so
the entry never carries a machine-specific or repo-checkout path::

    "unlimited-tools": {
        "command": "unlimited-skills",
        "args": ["mcp", "gateway", "--config", "~/.unlimited-skills/gateway-config.json"]
    }

Safety contract (tests/test_mcp_install_claude_code.py):

- a timestamped backup of an existing config is written next to it before
  ANY modification, and its path is reported;
- other ``mcpServers`` entries and unrelated top-level keys are preserved
  byte-for-byte at the JSON level -- only our one entry is touched;
- idempotent: rerunning over an identical entry is "already installed",
  exit 0, no write, no new backup;
- a same-named entry with DIFFERENT content is refused without ``--force``;
- an unparseable target config is always refused (even with ``--force``) --
  the installer never silently overwrites a file it cannot understand;
- ``--dry-run`` shows the before/after diff and writes nothing;
- writes are atomic (temp file + replace) and the result is re-read and
  JSON-validated after every write;
- output (human and ``--json``) carries server names and file paths only --
  configured ``env``/``headers`` VALUES of any pre-existing entry are
  redacted in diffs and never printed.
"""

from __future__ import annotations

import difflib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

SERVER_NAME = "unlimited-tools"

# The literal, host-portable gateway config reference written into the host
# config. The gateway CLI expands `~` itself (`Path(args.config).expanduser()`
# in commands/mcp.py), so the entry works unchanged on any machine and never
# embeds a local absolute path.
GATEWAY_CONFIG_REFERENCE = "~/.unlimited-skills/gateway-config.json"

NEXT_STEP = (
    "Restart your Claude Code session to load the 'unlimited-tools' gateway, "
    f"then add your upstream MCP servers to {GATEWAY_CONFIG_REFERENCE}."
)

SCOPES = ("project", "global")

# Keys whose VALUES may carry secrets in a host config entry; values under
# these keys are redacted before any entry is rendered into a diff.
_SENSITIVE_ENTRY_KEYS = ("env", "headers")


class InstallError(RuntimeError):
    """The target host config cannot be safely modified."""


def desired_server_entry() -> dict:
    """The exact ``mcpServers`` entry the installer manages."""
    return {
        "command": "unlimited-skills",
        "args": ["mcp", "gateway", "--config", GATEWAY_CONFIG_REFERENCE],
    }


def target_config_path(scope: str, *, cwd: Path | None = None, home: Path | None = None) -> Path:
    """The host config file for a scope: ``./.mcp.json`` or ``~/.claude.json``."""
    if scope not in SCOPES:
        raise ValueError(f"unknown scope: {scope!r}")
    if scope == "project":
        return (cwd or Path.cwd()) / ".mcp.json"
    return (home or Path.home()) / ".claude.json"


def gateway_config_path(home: Path | None = None) -> Path:
    """The expanded local path the written ``~/...`` reference resolves to."""
    return (home or Path.home()) / ".unlimited-skills" / "gateway-config.json"


def load_host_config(path: Path) -> dict:
    """Read and validate the target host config.

    A missing or whitespace-only file is an empty config (``{}``). Anything
    unparseable or structurally unusable (non-object top level, non-object
    ``mcpServers``) raises :class:`InstallError` -- the installer refuses
    rather than silently overwriting a file it cannot understand.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lstrip("﻿")
    except OSError as exc:
        raise InstallError(f"cannot read {path}: {type(exc).__name__}") from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InstallError(
            f"{path} is not valid JSON (line {exc.lineno}: {exc.msg}). "
            "Fix or move the file, then rerun; this installer never overwrites "
            "a config it cannot parse."
        ) from exc
    if not isinstance(data, dict):
        raise InstallError(
            f"{path} is valid JSON but not an object; refusing to modify it."
        )
    servers = data.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise InstallError(
            f"{path} has a non-object 'mcpServers' value; refusing to modify it."
        )
    return data


def backup_config(path: Path, *, now: datetime | None = None) -> Path:
    """Copy the existing config next to itself with a timestamped name."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.backup-{stamp}")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.backup-{stamp}-{counter}")
        counter += 1
    backup.write_bytes(path.read_bytes())
    return backup


def write_host_config(path: Path, data: dict) -> None:
    """Atomically write the config and prove the result parses back."""
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    json.loads(payload)  # the document we are about to write must be valid JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    # Post-write validation: the file on disk must round-trip.
    json.loads(path.read_text(encoding="utf-8").lstrip("﻿"))


def ensure_gateway_config(home: Path | None = None) -> tuple[Path, bool]:
    """Create a minimal valid gateway config when none exists.

    Returns ``(path, created)``. An existing file is never modified.
    """
    path = gateway_config_path(home)
    if path.is_file():
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "comment": (
            "Unlimited Tools gateway config (schemas/mcp-upstream-config.schema.json). "
            "Add your upstream stdio MCP servers to 'upstreams'; see "
            "docs/unlimited-tools.md and examples/mcp/gateway-config.example.json."
        ),
        "upstreams": [],
    }
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return path, True


def _sanitize_entry(entry: object) -> object:
    """Redact env/header VALUES so an entry can be rendered into a diff."""
    if not isinstance(entry, dict):
        return entry
    safe: dict = {}
    for key, value in entry.items():
        if key in _SENSITIVE_ENTRY_KEYS and isinstance(value, dict):
            safe[key] = {str(name): "<redacted>" for name in value}
        else:
            safe[key] = value
    return safe


def render_entry_diff(
    config_path: Path,
    before_entry: object | None,
    after_entry: object | None,
    other_names: list[str],
) -> list[str]:
    """A privacy-safe unified diff of OUR entry only.

    Other servers are summarized by name (never by content); env/header
    values of a same-named pre-existing entry are redacted.
    """

    def render(entry: object | None) -> list[str]:
        document = {SERVER_NAME: _sanitize_entry(entry)} if entry is not None else {}
        return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).splitlines()

    lines = list(
        difflib.unified_diff(
            render(before_entry),
            render(after_entry),
            fromfile=f"{config_path} (before)",
            tofile=f"{config_path} (after)",
            lineterm="",
        )
    )
    if other_names:
        names = ", ".join(sorted(other_names))
        lines.append(f"(unchanged: {len(other_names)} other MCP server(s): {names})")
    return lines


def _other_server_names(servers: dict) -> list[str]:
    return sorted(str(name) for name in servers if name != SERVER_NAME)


def install_claude_code(
    scope: str = "project",
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    """Install the gateway entry. Returns the machine-readable report."""
    path = target_config_path(scope, cwd=cwd, home=home)
    entry = desired_server_entry()
    report = {
        "action": "install",
        "status": "",
        "scope": scope,
        "config_path": str(path),
        "server_name": SERVER_NAME,
        "entry": entry,
        "backup_path": "",
        "gateway_config_path": str(gateway_config_path(home)),
        "gateway_config_created": False,
        "replaced_existing": False,
        "other_servers": [],
        "diff": [],
        "reason": "",
        "next_step": NEXT_STEP,
        "exit_code": 0,
    }
    try:
        data = load_host_config(path)
    except InstallError as exc:
        report.update(status="refused", reason=str(exc), exit_code=1)
        return report
    servers = data.get("mcpServers") or {}
    report["other_servers"] = _other_server_names(servers)
    existing = servers.get(SERVER_NAME)
    if existing == entry:
        report["status"] = "already_installed"
        return report
    if existing is not None and not force:
        report.update(
            status="refused",
            reason=(
                f"a different '{SERVER_NAME}' entry already exists in {path}; "
                "rerun with --force to replace it (a timestamped backup is "
                "written first)"
            ),
            exit_code=1,
        )
        return report
    report["replaced_existing"] = existing is not None
    report["diff"] = render_entry_diff(path, existing, entry, report["other_servers"])
    if dry_run:
        report["status"] = "would_install"
        return report
    if path.exists():
        report["backup_path"] = str(backup_config(path, now=now))
    merged_servers = dict(servers)
    merged_servers[SERVER_NAME] = entry
    data["mcpServers"] = merged_servers
    write_host_config(path, data)
    _, created = ensure_gateway_config(home)
    report["gateway_config_created"] = created
    report["status"] = "installed"
    return report


def uninstall_claude_code(
    scope: str = "project",
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    """Remove ONLY our gateway entry. Returns the machine-readable report."""
    path = target_config_path(scope, cwd=cwd, home=home)
    report = {
        "action": "uninstall",
        "status": "",
        "scope": scope,
        "config_path": str(path),
        "server_name": SERVER_NAME,
        "backup_path": "",
        "other_servers": [],
        "diff": [],
        "reason": "",
        "exit_code": 0,
    }
    try:
        data = load_host_config(path)
    except InstallError as exc:
        report.update(status="refused", reason=str(exc), exit_code=1)
        return report
    servers = data.get("mcpServers") or {}
    report["other_servers"] = _other_server_names(servers)
    if SERVER_NAME not in servers:
        report["status"] = "not_installed"
        return report
    existing = servers[SERVER_NAME]
    report["diff"] = render_entry_diff(path, existing, None, report["other_servers"])
    if dry_run:
        report["status"] = "would_uninstall"
        return report
    report["backup_path"] = str(backup_config(path, now=now))
    remaining = {name: spec for name, spec in servers.items() if name != SERVER_NAME}
    data["mcpServers"] = remaining
    write_host_config(path, data)
    report["status"] = "uninstalled"
    return report


def install_status(*, cwd: Path | None = None, home: Path | None = None) -> dict:
    """Report where the gateway entry is registered. Never writes anything."""
    entry = desired_server_entry()
    locations = []
    for scope in SCOPES:
        path = target_config_path(scope, cwd=cwd, home=home)
        location = {
            "scope": scope,
            "config_path": str(path),
            "config_exists": path.exists(),
            "config_valid": True,
            "installed": False,
            "matches_current": False,
        }
        try:
            data = load_host_config(path)
        except InstallError:
            location["config_valid"] = False
            locations.append(location)
            continue
        servers = data.get("mcpServers") or {}
        if SERVER_NAME in servers:
            location["installed"] = True
            location["matches_current"] = servers[SERVER_NAME] == entry
        locations.append(location)
    installed = any(location["installed"] for location in locations)
    return {
        "action": "install-status",
        "server_name": SERVER_NAME,
        "installed": installed,
        "locations": locations,
        "exit_code": 0 if installed else 1,
    }


# ---------------------------------------------------------------------------
# Human-readable rendering


def format_install_text(report: dict) -> str:
    path = report["config_path"]
    scope = report["scope"]
    lines: list[str] = []
    status = report["status"]
    if status == "refused":
        lines.append(f"mcp install refused: {report['reason']}")
        return "\n".join(lines)
    if status == "already_installed":
        lines.append(
            f"'{SERVER_NAME}' is already installed in {path} ({scope} scope); nothing changed."
        )
        return "\n".join(lines)
    if status == "would_install":
        lines.append(f"Dry run: would install '{SERVER_NAME}' into {path} ({scope} scope).")
        lines.extend(report["diff"])
        lines.append("(dry run: nothing was written)")
        return "\n".join(lines)
    verb = "Replaced the existing entry and installed" if report["replaced_existing"] else "Installed"
    lines.append(f"{verb} '{SERVER_NAME}' into {path} ({scope} scope).")
    if report["backup_path"]:
        lines.append(f"Backup of the previous config: {report['backup_path']}")
    if report["gateway_config_created"]:
        lines.append(
            f"Created a minimal gateway config (no upstreams yet): {report['gateway_config_path']}"
        )
    if report["other_servers"]:
        names = ", ".join(report["other_servers"])
        lines.append(f"Other MCP servers preserved untouched: {names}")
    lines.append("")
    lines.append(f"Next step: {report['next_step']}")
    return "\n".join(lines)


def format_uninstall_text(report: dict) -> str:
    path = report["config_path"]
    scope = report["scope"]
    status = report["status"]
    if status == "refused":
        return f"mcp uninstall refused: {report['reason']}"
    if status == "not_installed":
        return f"'{SERVER_NAME}' is not installed in {path} ({scope} scope); nothing to do."
    if status == "would_uninstall":
        lines = [f"Dry run: would remove '{SERVER_NAME}' from {path} ({scope} scope)."]
        lines.extend(report["diff"])
        lines.append("(dry run: nothing was written)")
        return "\n".join(lines)
    lines = [f"Removed '{SERVER_NAME}' from {path} ({scope} scope)."]
    if report["backup_path"]:
        lines.append(f"Backup of the previous config: {report['backup_path']}")
    if report["other_servers"]:
        names = ", ".join(report["other_servers"])
        lines.append(f"Other MCP servers preserved untouched: {names}")
    lines.append("Restart your Claude Code session to apply the change.")
    return "\n".join(lines)


def format_status_text(report: dict) -> str:
    lines = [f"'{SERVER_NAME}' MCP gateway registration:"]
    for location in report["locations"]:
        path = location["config_path"]
        scope = location["scope"]
        if not location["config_valid"]:
            state = "config is not valid JSON"
        elif not location["config_exists"]:
            state = "not installed (config file does not exist)"
        elif not location["installed"]:
            state = "not installed"
        elif location["matches_current"]:
            state = "installed"
        else:
            state = "installed (entry differs from the current command; rerun: unlimited-skills mcp install --claude-code --force)"
        lines.append(f"  {scope:<8} {path}: {state}")
    lines.append("")
    if report["installed"]:
        lines.append("Status: installed.")
    else:
        lines.append("Status: not installed. Run: unlimited-skills mcp install --claude-code")
    return "\n".join(lines)
