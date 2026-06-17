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
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .agents_patch import CONTRACT_VERSION, agents_block, parse_contract_version
from .installers.claude_code import ROUTER_NAME, apply_claude_block, router_block_lines


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
class SyncInjectReport:
    contract_version: int
    agents_present: list[str] = field(default_factory=list)
    files: list[InjectFileResult] = field(default_factory=list)
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


def refresh_injects(
    *,
    claude_home: Path,
    codex_home: Path,
    hermes_home: Path,
    project_root: Path,
    agents: set[str] | None = None,
    patch_global: bool = True,
    patch_project: bool = True,
    backup: bool = True,
    timestamp: str | None = None,
) -> SyncInjectReport:
    """Refresh the router inject for every installed (and requested) agent.

    Each agent is refreshed only when its router is installed under
    ``<home>/skills/unlimited-skills``. ``agents`` optionally restricts the set
    (default: all of claude-code, codex, hermes). The managed block is rendered
    from in-package functions and applied with the BEGIN/END markers, so a stale
    block is upgraded in place rather than duplicated.
    """
    claude_home = Path(claude_home).expanduser()
    codex_home = Path(codex_home).expanduser()
    hermes_home = Path(hermes_home).expanduser()
    project_root = Path(project_root).expanduser()
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    wanted = agents or {"claude-code", "codex", "hermes"}

    report = SyncInjectReport(contract_version=CONTRACT_VERSION)

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

    # Codex: project AGENTS.md managed block (single launcher).
    if "codex" in wanted and _router_present(codex_home):
        report.agents_present.append("codex")
        sh, _ = _launchers(codex_home)
        block = agents_block(sh)
        if patch_project:
            report.files.append(_refresh_one("codex", project_root / "AGENTS.md", block, backup=backup, timestamp=stamp))

    # Hermes: the contract block embedded in the visible router SKILL.md.
    if "hermes" in wanted and _router_present(hermes_home):
        report.agents_present.append("hermes")
        sh, ps = _launchers(hermes_home)
        block = "\n".join(router_block_lines(sh, ps))
        report.files.append(
            _refresh_one("hermes", _router_home(hermes_home) / "SKILL.md", block, backup=backup, timestamp=stamp)
        )

    if not report.agents_present:
        report.messages.append(
            "No Unlimited Skills router found under ~/.claude, ~/.codex, or ~/.hermes; "
            "run the installer first. No inject was refreshed."
        )
    return report


def report_as_dict(report: SyncInjectReport) -> dict:
    return asdict(report)
