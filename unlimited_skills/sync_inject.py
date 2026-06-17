"""Refresh every installed agent's router inject to the current contract.

Root-cause fix for "the inject did not get patched on update": each agent's
behavioural inject (the Claude Code ``CLAUDE.md`` managed block, the Codex /
OpenClaw ``AGENTS.md`` managed block, and the Hermes router ``SKILL.md`` block)
is only (re)written by the installer, but ``pip install --upgrade`` never
re-runs the installer, so a marked inject keeps its stale contract forever.
``sync-inject`` re-applies the current managed block — rendered from in-package
functions, so it works from the installed package alone — to whichever agents
are installed. Idempotent, with a backup; the BEGIN/END markers are replaced in
place (never duplicated), and a missing target is created.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .agents_patch import CONTRACT_VERSION, agents_block, parse_contract_version
from .installers.claude_code import ROUTER_NAME, apply_claude_block, router_block_lines
from .launchers import (
    LAUNCHER_CONTRACT_VERSION,
    parse_launcher_contract,
    render_ps_launcher,
    render_sh_launcher,
    resolve_launch_pythonpath,
)


@dataclass
class InjectFileResult:
    agent: str
    path: str
    existed: bool
    from_contract: int | None
    to_contract: int
    changed: bool
    backup: str = ""


@dataclass
class LauncherFileResult:
    agent: str
    kind: str  # "sh" or "ps"
    path: str
    existed: bool
    from_contract: int | None
    to_contract: int
    changed: bool
    backup: str = ""


@dataclass
class SyncInjectReport:
    contract_version: int
    agents_present: list[str] = field(default_factory=list)
    files: list[InjectFileResult] = field(default_factory=list)
    launchers: list[LauncherFileResult] = field(default_factory=list)
    launcher_contract_version: int = LAUNCHER_CONTRACT_VERSION
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.agents_present)

    def format_text(self) -> str:
        lines = [
            "Unlimited Skills inject sync",
            "",
            f"Current contract version: {self.contract_version}",
            f"Agents with a router installed: {', '.join(self.agents_present) or '<none>'}",
            "",
            "Files:",
        ]
        if self.files:
            for item in self.files:
                state = ("refreshed" if item.changed else "already current") if item.existed else "created"
                frm = "none" if item.from_contract is None else f"v{item.from_contract}"
                lines.append(f"  - [{item.agent}] {item.path}: {state} ({frm} -> v{item.to_contract})")
                if item.backup:
                    lines.append(f"    backup: {item.backup}")
        else:
            lines.append("  - <none>")
        if self.launchers:
            lines.extend(["", f"Launchers (contract v{self.launcher_contract_version}):"])
            for item in self.launchers:
                state = ("refreshed" if item.changed else "already current") if item.existed else "created"
                frm = "none" if item.from_contract is None else f"v{item.from_contract}"
                lines.append(f"  - [{item.agent}] {item.kind}: {item.path}: {state} ({frm} -> v{item.to_contract})")
                if item.backup:
                    lines.append(f"    backup: {item.backup}")
        if self.messages:
            lines.extend(["", "Messages:"])
            lines.extend(f"  - {message}" for message in self.messages)
        return "\n".join(lines)


def _router_home(home: Path) -> Path:
    return home / "skills" / ROUTER_NAME


def _router_present(home: Path) -> bool:
    return (_router_home(home) / "SKILL.md").is_file()


def _launchers(home: Path) -> tuple[str, str]:
    scripts = _router_home(home) / "scripts"
    return (scripts / "unlimited-skills.sh").as_posix(), (scripts / "unlimited-skills.ps1").as_posix()


def _backup_path(path: Path, timestamp: str) -> Path:
    backup = path.with_name(f"{path.name}.{timestamp}.back")
    index = 2
    while backup.exists():
        backup = path.with_name(f"{path.name}.{timestamp}_{index}.back")
        index += 1
    return backup


def _refresh_one(agent: str, path: Path, block: str, *, backup: bool, timestamp: str) -> InjectFileResult:
    existed = path.is_file()
    old_text = path.read_text(encoding="utf-8", errors="replace") if existed else ""
    from_contract = parse_contract_version(old_text)
    new_text = apply_claude_block(old_text, block)
    changed = new_text != old_text
    backup_file = ""
    if changed:
        if backup and existed:
            dest = _backup_path(path, timestamp)
            shutil.copy2(path, dest)
            backup_file = str(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
    return InjectFileResult(
        agent=agent,
        path=str(path),
        existed=existed,
        from_contract=from_contract,
        to_contract=CONTRACT_VERSION,
        changed=changed,
        backup=backup_file,
    )


def _heal_one_launcher(
    agent: str,
    kind: str,
    path: Path,
    new_text: str,
    *,
    executable: bool,
    backup: bool,
    timestamp: str,
) -> LauncherFileResult:
    existed = path.is_file()
    old_text = path.read_text(encoding="utf-8", errors="replace") if existed else ""
    from_contract = parse_launcher_contract(old_text) if existed else None
    changed = new_text != old_text
    backup_file = ""
    if changed:
        if backup and existed:
            dest = _backup_path(path, timestamp)
            shutil.copy2(path, dest)
            backup_file = str(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
        if executable:
            try:
                path.chmod(0o755)
            except OSError:
                pass
    return LauncherFileResult(
        agent=agent,
        kind=kind,
        path=str(path),
        existed=existed,
        from_contract=from_contract,
        to_contract=LAUNCHER_CONTRACT_VERSION,
        changed=changed,
        backup=backup_file,
    )


def _heal_launchers_for(
    agent: str,
    scripts_dir: Path,
    *,
    python_executable: str,
    library_root: Path,
    project_root: Path | None,
    pythonpath_fallback: str | None,
    backup: bool,
    timestamp: str,
) -> list[LauncherFileResult]:
    """Regenerate an agent's launcher(s) from the shared templates.

    Always refreshes the ``.sh`` launcher; refreshes a ``.ps1`` launcher only when
    one already exists (Claude/Hermes write it; Codex/OpenClaw do not, and heal
    must not fabricate a launcher the installer never created). This is the
    durable repair for a launcher left behind by an older install (the legacy
    ``PYTHONPATH=<repo>`` form), regardless of which installer wrote it.
    """
    results: list[LauncherFileResult] = []
    sh_text = render_sh_launcher(
        python_executable, library_root, project_root=project_root, pythonpath_fallback=pythonpath_fallback
    )
    results.append(
        _heal_one_launcher(
            agent, "sh", scripts_dir / "unlimited-skills.sh", sh_text, executable=True, backup=backup, timestamp=timestamp
        )
    )
    ps_path = scripts_dir / "unlimited-skills.ps1"
    if ps_path.is_file():
        ps_text = render_ps_launcher(
            python_executable, library_root, project_root=project_root, pythonpath_fallback=pythonpath_fallback
        )
        results.append(
            _heal_one_launcher(agent, "ps", ps_path, ps_text, executable=False, backup=backup, timestamp=timestamp)
        )
    return results


def refresh_injects(
    *,
    claude_home: Path,
    codex_home: Path,
    hermes_home: Path,
    project_root: Path,
    openclaw_home: Path | None = None,
    openclaw_workspace: Path | None = None,
    agents: set[str] | None = None,
    patch_global: bool = True,
    patch_project: bool = True,
    backup: bool = True,
    timestamp: str | None = None,
    heal_launchers: bool = False,
    python_executable: str = sys.executable,
    library_root: Path | None = None,
    repo_root: Path | None = None,
) -> SyncInjectReport:
    """Refresh the router inject for every installed (and requested) agent.

    Each agent is refreshed only when its router is installed under
    ``<home>/skills/unlimited-skills``. ``agents`` optionally restricts the set
    (default: all of claude-code, codex, openclaw, hermes). The managed block is
    rendered from in-package functions and applied with the BEGIN/END markers, so
    a stale block is upgraded in place rather than duplicated.
    """
    claude_home = Path(claude_home).expanduser()
    codex_home = Path(codex_home).expanduser()
    hermes_home = Path(hermes_home).expanduser()
    project_root = Path(project_root).expanduser()
    openclaw_home = Path(openclaw_home).expanduser() if openclaw_home is not None else Path.home() / ".openclaw"
    openclaw_workspace = (
        Path(openclaw_workspace).expanduser() if openclaw_workspace is not None else openclaw_home / "workspace"
    )
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    wanted = agents or {"claude-code", "codex", "openclaw", "hermes"}

    report = SyncInjectReport(contract_version=CONTRACT_VERSION)

    # Launcher healing: regenerate stale launchers (the legacy PYTHONPATH=<repo>
    # form) from the shared templates so the router runs the INSTALLED package. The
    # fallback is resolved once for the recorded interpreter; on the normal
    # pip/editable install it is None (a clean launcher).
    if heal_launchers:
        if library_root is None:
            from .registration import unlimited_skills_home

            library_root = unlimited_skills_home() / "library"
        else:
            library_root = Path(library_root).expanduser()
        pythonpath_fallback = resolve_launch_pythonpath(python_executable, repo_root)

    def _heal(agent: str, home: Path, *, agent_project_root: Path | None) -> None:
        if not heal_launchers:
            return
        report.launchers.extend(
            _heal_launchers_for(
                agent,
                _router_home(home) / "scripts",
                python_executable=python_executable,
                library_root=library_root,
                project_root=agent_project_root,
                pythonpath_fallback=pythonpath_fallback,
                backup=backup,
                timestamp=stamp,
            )
        )

    # Claude Code: global + project CLAUDE.md managed block (sh + ps launchers).
    if "claude-code" in wanted and _router_present(claude_home):
        report.agents_present.append("claude-code")
        sh, ps = _launchers(claude_home)
        block = "\n".join(router_block_lines(sh, ps))
        targets: list[Path] = []
        if patch_global:
            targets.append(claude_home / "CLAUDE.md")
        if patch_project:
            proj = project_root / "CLAUDE.md"
            if not any(proj.resolve() == t.resolve() for t in targets):
                targets.append(proj)
        for target in targets:
            report.files.append(_refresh_one("claude-code", target, block, backup=backup, timestamp=stamp))
        _heal("claude-code", claude_home, agent_project_root=project_root)

    # Codex: project AGENTS.md managed block (single launcher).
    if "codex" in wanted and _router_present(codex_home):
        report.agents_present.append("codex")
        sh, _ = _launchers(codex_home)
        block = agents_block(sh)
        if patch_project:
            report.files.append(_refresh_one("codex", project_root / "AGENTS.md", block, backup=backup, timestamp=stamp))
        _heal("codex", codex_home, agent_project_root=None)

    # OpenClaw: workspace AGENTS.md managed block (single launcher).
    if "openclaw" in wanted and _router_present(openclaw_workspace):
        report.agents_present.append("openclaw")
        sh, _ = _launchers(openclaw_workspace)
        block = agents_block(sh)
        if patch_project:
            report.files.append(
                _refresh_one("openclaw", openclaw_workspace / "AGENTS.md", block, backup=backup, timestamp=stamp)
            )
        _heal("openclaw", openclaw_workspace, agent_project_root=None)

    # Hermes: the contract block embedded in the visible router SKILL.md.
    if "hermes" in wanted and _router_present(hermes_home):
        report.agents_present.append("hermes")
        sh, ps = _launchers(hermes_home)
        block = "\n".join(router_block_lines(sh, ps))
        report.files.append(
            _refresh_one("hermes", _router_home(hermes_home) / "SKILL.md", block, backup=backup, timestamp=stamp)
        )
        _heal("hermes", hermes_home, agent_project_root=None)

    if not report.agents_present:
        report.messages.append(
            "No Unlimited Skills router found under ~/.claude, ~/.codex, ~/.openclaw/workspace, or ~/.hermes; "
            "run the installer first. No inject was refreshed."
        )
    return report


def report_as_dict(report: SyncInjectReport) -> dict:
    return asdict(report)
