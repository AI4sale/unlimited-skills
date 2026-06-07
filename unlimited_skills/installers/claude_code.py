from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from unlimited_skills.adapters import adapt_library
from unlimited_skills.cli import save_index

from .common import copy_skill_tree, iter_skill_dirs

INSTALL_MODES = {"default", "bundled", "adapt-installed"}
ROUTER_NAME = "unlimited-skills"


@dataclass
class ClaudeCodeInstallOptions:
    claude_home: Path
    project_root: Path
    install_root: Path
    repo_root: Path
    mode: str = "default"
    claude_file: Path | None = None
    patch_claude: bool = True
    include_project_skills: bool = True
    skip_reindex: bool = False
    vector_reindex: bool = False
    python_executable: str = sys.executable


@dataclass
class MigrationResult:
    collection: str
    source_root: str
    migrated_count: int
    skipped: bool = False
    reason: str = ""


@dataclass
class ClaudeCodeInstallReport:
    claude_home: str
    project_root: str
    library_root: str
    mode: str
    router_target: str
    shell_launcher: str
    powershell_launcher: str
    claude_file: str
    router_installed: bool = False
    claude_patched: bool = False
    lexical_index: str = "skipped"
    vector_index: str = "skipped"
    migrations: list[MigrationResult] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def format_text(self) -> str:
        lines = [
            "Claude Code Unlimited Skills install report",
            "",
            f"Claude home: {self.claude_home}",
            f"Project root: {self.project_root}",
            f"Library root: {self.library_root}",
            f"Mode: {self.mode}",
            "",
            "Router:",
            f"  installed: {'yes' if self.router_installed else 'no'}",
            f"  target: {self.router_target}",
            f"  shell launcher: {self.shell_launcher}",
            f"  PowerShell launcher: {self.powershell_launcher}",
            "",
            "CLAUDE.md:",
            f"  patched: {'yes' if self.claude_patched else 'no'}",
            f"  path: {self.claude_file or '<skipped>'}",
            "",
            "Migrations:",
        ]
        if self.migrations:
            for item in self.migrations:
                status = "skipped" if item.skipped else f"{item.migrated_count} skills"
                suffix = f" ({item.reason})" if item.reason else ""
                lines.append(f"  - {item.collection}: {status}{suffix}")
                lines.append(f"    source: {item.source_root}")
        else:
            lines.append("  - <none>")
        lines.extend(
            [
                "",
                "Index:",
                f"  lexical index: {self.lexical_index}",
                f"  vector index: {self.vector_index}",
            ]
        )
        if self.messages:
            lines.extend(["", "Messages:"])
            lines.extend(f"  - {message}" for message in self.messages)
        return "\n".join(lines)


def _router_source(repo_root: Path) -> Path:
    claude_router = repo_root / "skills" / "router-claude-code"
    if claude_router.is_dir():
        return claude_router
    return repo_root / "skills" / "skill-router"


def _write_launchers(sh_launcher: Path, ps_launcher: Path, repo_root: Path, library_root: Path, project_root: Path, python_executable: str) -> None:
    sh_launcher.parent.mkdir(parents=True, exist_ok=True)
    sh_repo_root = shlex.quote(str(repo_root).replace("\\", "/"))
    sh_library_root = shlex.quote(str(library_root).replace("\\", "/"))
    sh_project_root = shlex.quote(str(project_root).replace("\\", "/"))
    sh_python = shlex.quote(str(python_executable).replace("\\", "/"))
    sh_launcher.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"if [[ -n \"${{PYTHONPATH:-}}\" ]]; then\n"
        f"  export PYTHONPATH={sh_repo_root}:\"$PYTHONPATH\"\n"
        "else\n"
        f"  export PYTHONPATH={sh_repo_root}\n"
        "fi\n"
        f"export UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT={sh_project_root}\n"
        f"exec {sh_python} -m unlimited_skills.cli --root {sh_library_root} \"$@\"\n",
        encoding="utf-8",
    )
    try:
        sh_launcher.chmod(0o755)
    except OSError:
        pass
    ps_launcher.write_text(
        "param(\n"
        "  [Parameter(ValueFromRemainingArguments = $true)]\n"
        "  [string[]]$Args\n"
        ")\n\n"
        "$ErrorActionPreference = \"Stop\"\n"
        f"$env:PYTHONPATH = {json.dumps(str(repo_root))} + [System.IO.Path]::PathSeparator + $env:PYTHONPATH\n"
        f"$env:UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT = {json.dumps(str(project_root))}\n"
        f"& {json.dumps(python_executable)} -m unlimited_skills.cli --root {json.dumps(str(library_root))} @Args\n",
        encoding="utf-8",
    )


def _render_router_skill(router_skill: Path, sh_launcher: Path, ps_launcher: Path, library_root: Path) -> None:
    text = router_skill.read_text(encoding="utf-8", errors="replace")
    replacements = {
        "{{CLAUDE_SH_LAUNCHER}}": sh_launcher.as_posix(),
        "{{CLAUDE_PS_LAUNCHER}}": ps_launcher.as_posix(),
        "{{UNLIMITED_SKILLS_LIBRARY_ROOT}}": library_root.as_posix(),
    }
    for needle, value in replacements.items():
        text = text.replace(needle, value)
    router_skill.write_text(text, encoding="utf-8")


def _patch_claude_file(claude_file: Path, sh_launcher: Path, ps_launcher: Path) -> None:
    claude_file.parent.mkdir(parents=True, exist_ok=True)
    sh_text = sh_launcher.as_posix()
    ps_text = ps_launcher.as_posix()
    block = "\n".join(
        [
            "<!-- BEGIN UNLIMITED SKILLS -->",
            "## Unlimited Skills Library",
            "",
            "Unlimited Skills is the external skill memory for Claude Code. Treat it as the first place to ask for task-specific skills, workflows, checklists, procedures, and regression recipes that may not be visible in Claude Code's current skill listing.",
            "",
            "Before doing substantive work, check whether Unlimited Skills has a relevant skill. This includes writing, editing, coding, review, debugging, research, documentation, operations, planning, and design tasks. Skip this check only when a relevant skill is already active in the current context and it is clear why that skill applies.",
            "",
            "Before saying a skill is unavailable, query the library:",
            "",
            "```bash",
            f"\"{sh_text}\" search \"<task or skill name>\" --mode hybrid --limit 8",
            f"\"{sh_text}\" where <skill-name>",
            f"\"{sh_text}\" view <skill-name>",
            "```",
            "",
            "On Windows PowerShell, use:",
            "",
            "```powershell",
            f"powershell -NoProfile -ExecutionPolicy Bypass -File \"{ps_text}\" search \"<task or skill name>\" --mode hybrid --limit 8",
            f"powershell -NoProfile -ExecutionPolicy Bypass -File \"{ps_text}\" where <skill-name>",
            f"powershell -NoProfile -ExecutionPolicy Bypass -File \"{ps_text}\" view <skill-name>",
            "```",
            "",
            "For inventory questions, query the library before answering:",
            "",
            "```bash",
            f"\"{sh_text}\" list --limit 80",
            "```",
            "",
            "Do not rely only on `~/.claude/skills`, `.claude/skills`, or the visible skill list. The library may contain skills that are intentionally not loaded into context.",
            "<!-- END UNLIMITED SKILLS -->",
            "",
        ]
    )
    pattern_start = "<!-- BEGIN UNLIMITED SKILLS -->"
    pattern_end = "<!-- END UNLIMITED SKILLS -->"
    text = claude_file.read_text(encoding="utf-8", errors="replace") if claude_file.is_file() else ""
    start = text.find(pattern_start)
    end = text.find(pattern_end)
    if start >= 0 and end >= start:
        end += len(pattern_end)
        text = text[:start].rstrip() + "\n\n" + block.rstrip() + "\n" + text[end:].lstrip()
    elif text.strip():
        text = text.rstrip() + "\n\n" + block
    else:
        text = block
    claude_file.write_text(text, encoding="utf-8")


def _existing_skill_names(library_root: Path, exclude_collection: str = "") -> set[str]:
    if not library_root.is_dir():
        return set()
    names = set()
    for path in library_root.rglob("SKILL.md"):
        try:
            collection = path.relative_to(library_root).parts[0]
        except (IndexError, ValueError):
            collection = ""
        if exclude_collection and collection == exclude_collection:
            continue
        names.add(path.parent.name)
    return names


def _migrate_source(
    source_root: Path,
    library_root: Path,
    collection: str,
    *,
    exclude_names: set[str] | None = None,
    skip_existing_names: bool = True,
) -> MigrationResult:
    source_root = Path(source_root).expanduser()
    if not source_root.is_dir():
        return MigrationResult(collection=collection, source_root=str(source_root), migrated_count=0, skipped=True, reason="source root not found")

    target_skills = library_root / collection / "skills"
    existing = _existing_skill_names(library_root, exclude_collection=collection) if skip_existing_names else set()
    excluded = exclude_names or set()
    migrated = 0
    for skill_dir in iter_skill_dirs(source_root, exclude_names=excluded):
        if skip_existing_names and skill_dir.name in existing:
            continue
        relative = skill_dir.relative_to(source_root)
        destination = target_skills / relative
        copy_skill_tree(skill_dir, destination)
        existing.add(skill_dir.name)
        migrated += 1
    return MigrationResult(collection=collection, source_root=str(source_root), migrated_count=migrated)


def install_claude_code(options: ClaudeCodeInstallOptions) -> ClaudeCodeInstallReport:
    if options.mode not in INSTALL_MODES:
        raise ValueError(f"Invalid Claude Code install mode: {options.mode}")

    claude_home = Path(options.claude_home).expanduser()
    project_root = Path(options.project_root).expanduser()
    install_root = Path(options.install_root).expanduser()
    repo_root = Path(options.repo_root).expanduser()
    library_root = install_root / "library"
    router_target = claude_home / "skills" / ROUTER_NAME
    sh_launcher = router_target / "scripts" / "unlimited-skills.sh"
    ps_launcher = router_target / "scripts" / "unlimited-skills.ps1"
    claude_file = Path(options.claude_file).expanduser() if options.claude_file else project_root / "CLAUDE.md"
    messages: list[str] = []

    router_source = _router_source(repo_root)
    if not router_source.is_dir():
        raise FileNotFoundError(f"Router skill not found: {router_source}")

    if router_target.exists():
        shutil.rmtree(router_target)
    router_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(router_source, router_target)
    _write_launchers(sh_launcher, ps_launcher, repo_root, library_root, project_root, options.python_executable)
    _render_router_skill(router_target / "SKILL.md", sh_launcher, ps_launcher, library_root)

    claude_patched = False
    if options.patch_claude:
        _patch_claude_file(claude_file, sh_launcher, ps_launcher)
        claude_patched = True

    migrations: list[MigrationResult] = []
    if options.mode == "bundled":
        for pack in ("ecc", "superpowers"):
            migrations.append(
                _migrate_source(
                    repo_root / "packs" / pack / "skills",
                    library_root,
                    pack,
                    skip_existing_names=False,
                )
            )

    migrations.append(
        _migrate_source(
            claude_home / "skills",
            library_root,
            "claude-code",
            exclude_names={ROUTER_NAME},
            skip_existing_names=True,
        )
    )

    if options.include_project_skills:
        migrations.append(
            _migrate_source(
                project_root / ".claude" / "skills",
                library_root,
                "claude-code-project",
                exclude_names={ROUTER_NAME},
                skip_existing_names=True,
            )
        )

    if options.mode == "adapt-installed":
        for collection in ("claude-code", "claude-code-project"):
            adapt_library(library_root, collection=collection, source_pack=collection)

    lexical_index = "skipped"
    if not options.skip_reindex:
        save_index(library_root)
        lexical_index = "rebuilt"

    vector_index = "skipped"
    if options.vector_reindex:
        try:
            subprocess.run(
                [options.python_executable, "-m", "unlimited_skills.cli", "--root", str(library_root), "vector-reindex", "--verbose"],
                check=True,
            )
            vector_index = "rebuilt"
        except Exception as exc:  # pragma: no cover - depends on optional deps
            vector_index = "failed"
            messages.append(f"Vector reindex failed: {exc}")

    if not any(not item.skipped and item.migrated_count for item in migrations):
        messages.append("No Claude Code source skills were migrated. Router was still installed.")
    messages.append("Claude Code watches existing skill directories, but restart Claude Code if ~/.claude/skills did not exist before installation.")

    return ClaudeCodeInstallReport(
        claude_home=str(claude_home),
        project_root=str(project_root),
        library_root=str(library_root),
        mode=options.mode,
        router_target=str(router_target),
        shell_launcher=str(sh_launcher),
        powershell_launcher=str(ps_launcher),
        claude_file=str(claude_file) if options.patch_claude else "",
        router_installed=router_target.is_dir(),
        claude_patched=claude_patched,
        lexical_index=lexical_index,
        vector_index=vector_index,
        migrations=migrations,
        messages=messages,
    )


def _default_claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")


def _default_project_root() -> Path:
    return Path.cwd()


def _default_install_root() -> Path:
    return Path.home() / ".unlimited-skills"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install the Unlimited Skills Claude Code adapter.")
    parser.add_argument("--claude-home", type=Path, default=_default_claude_home())
    parser.add_argument("--project-root", type=Path, default=_default_project_root())
    parser.add_argument("--install-root", type=Path, default=_default_install_root())
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--mode", choices=sorted(INSTALL_MODES), default="default")
    parser.add_argument("--claude-file", type=Path)
    parser.add_argument("--no-claude-patch", action="store_true")
    parser.add_argument("--no-project-skills", action="store_true")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--skip-reindex", action="store_true")
    parser.add_argument("--vector-reindex", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = install_claude_code(
        ClaudeCodeInstallOptions(
            claude_home=args.claude_home,
            project_root=args.project_root,
            install_root=args.install_root,
            repo_root=args.repo_root,
            mode=args.mode,
            claude_file=args.claude_file,
            patch_claude=not args.no_claude_patch,
            include_project_skills=not args.no_project_skills,
            skip_reindex=args.skip_reindex,
            vector_reindex=args.vector_reindex,
            python_executable=args.python_executable,
        )
    )
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2) if args.json else report.format_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
