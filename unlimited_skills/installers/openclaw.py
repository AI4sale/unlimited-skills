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
from unlimited_skills.agents_patch import patch_agents_file
from unlimited_skills.cli import save_index

from .common import copy_skill_tree, iter_skill_dirs

INSTALL_MODES = {"default", "bundled", "adapt-installed"}
ROUTER_NAME = "unlimited-skills"


@dataclass
class OpenClawInstallOptions:
    openclaw_home: Path
    workspace_root: Path
    install_root: Path
    repo_root: Path
    mode: str = "default"
    agents_file: Path | None = None
    patch_agents: bool = True
    include_builtin: bool = True
    include_plugin_skills: bool = True
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
class OpenClawInstallReport:
    workspace_root: str
    library_root: str
    mode: str
    router_target: str
    launcher: str
    agents_file: str
    router_installed: bool = False
    agents_patched: bool = False
    lexical_index: str = "skipped"
    vector_index: str = "skipped"
    migrations: list[MigrationResult] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def format_text(self) -> str:
        lines = [
            "OpenClaw Unlimited Skills install report",
            "",
            f"Workspace root: {self.workspace_root}",
            f"Library root: {self.library_root}",
            f"Mode: {self.mode}",
            "",
            "Router:",
            f"  installed: {'yes' if self.router_installed else 'no'}",
            f"  target: {self.router_target}",
            f"  launcher: {self.launcher}",
            "",
            "AGENTS.md:",
            f"  patched: {'yes' if self.agents_patched else 'no'}",
            f"  path: {self.agents_file or '<skipped>'}",
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
    openclaw_router = repo_root / "skills" / "router-openclaw"
    if openclaw_router.is_dir():
        return openclaw_router
    return repo_root / "skills" / "skill-router"


def _write_launcher(launcher: Path, repo_root: Path, library_root: Path, python_executable: str) -> None:
    launcher.parent.mkdir(parents=True, exist_ok=True)
    sh_repo_root = shlex.quote(str(repo_root).replace("\\", "/"))
    sh_library_root = shlex.quote(str(library_root).replace("\\", "/"))
    sh_python = shlex.quote(str(python_executable).replace("\\", "/"))
    launcher.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"if [[ -n \"${{PYTHONPATH:-}}\" ]]; then\n"
        f"  export PYTHONPATH={sh_repo_root}:\"$PYTHONPATH\"\n"
        "else\n"
        f"  export PYTHONPATH={sh_repo_root}\n"
        "fi\n"
        f"exec {sh_python} -m unlimited_skills.cli --root {sh_library_root} \"$@\"\n",
        encoding="utf-8",
    )
    try:
        launcher.chmod(0o755)
    except OSError:
        pass


def _render_router_skill(router_skill: Path, launcher: Path, library_root: Path) -> None:
    text = router_skill.read_text(encoding="utf-8", errors="replace")
    replacements = {
        "{{OPENCLAW_SH_LAUNCHER}}": launcher.as_posix(),
        "{{UNLIMITED_SKILLS_LIBRARY_ROOT}}": library_root.as_posix(),
    }
    for needle, value in replacements.items():
        text = text.replace(needle, value)
    router_skill.write_text(text, encoding="utf-8")


def _patch_agents_file(agents_file: Path, launcher: Path) -> None:
    agents_file.parent.mkdir(parents=True, exist_ok=True)
    launcher_text = launcher.as_posix()
    block = "\n".join(
        [
            "<!-- BEGIN UNLIMITED SKILLS -->",
            "## Unlimited Skills Library",
            "",
            "Unlimited Skills is the external skill memory for this agent. Treat it as the first place to ask for task-specific skills, workflows, checklists, procedures, and regression recipes that may not be visible in the always-loaded skill list.",
            "",
            "Before doing substantive work, check whether Unlimited Skills has a relevant skill. This includes writing, editing, coding, review, debugging, research, documentation, operations, planning, and design tasks. Skip this check only when a relevant skill is already active in the current context and it is clear why that skill applies.",
            "",
            "Before saying a skill is unavailable, query the library:",
            "",
            "```bash",
            f"\"{launcher_text}\" search \"<task or skill name>\" --mode hybrid --limit 8",
            f"\"{launcher_text}\" where <skill-name>",
            f"\"{launcher_text}\" view <skill-name>",
            "```",
            "",
            "For inventory questions, query the library before answering:",
            "",
            "```bash",
            f"\"{launcher_text}\" list --limit 80",
            "```",
            "",
            "Do not rely only on the visible skill list. The library may contain skills that are intentionally not loaded into context.",
            "<!-- END UNLIMITED SKILLS -->",
            "",
        ]
    )
    patch_agents_file(agents_file, block)


def _existing_skill_names(library_root: Path, exclude_target: Path | None = None) -> set[str]:
    if not library_root.is_dir():
        return set()
    names = set()
    exclude_target_resolved = exclude_target.resolve() if exclude_target else None
    for path in library_root.rglob("SKILL.md"):
        if exclude_target_resolved:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved == exclude_target_resolved or exclude_target_resolved in resolved.parents:
                continue
        if "duplicates" in path.relative_to(library_root).parts:
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
    registry_collection: bool = False,
) -> MigrationResult:
    source_root = Path(source_root).expanduser()
    if not source_root.is_dir():
        return MigrationResult(collection=collection, source_root=str(source_root), migrated_count=0, skipped=True, reason="source root not found")

    target_skills = library_root / ("registry" if registry_collection else "local") / collection / "skills"
    existing = _existing_skill_names(library_root, exclude_target=target_skills) if skip_existing_names else set()
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


def _openclaw_sources(openclaw_home: Path, workspace_root: Path, include_builtin: bool, include_plugin_skills: bool) -> list[tuple[str, Path]]:
    sources: list[tuple[str, Path]] = [
        ("openclaw-workspace", workspace_root / "skills"),
    ]
    if include_plugin_skills:
        sources.extend(
            [
                ("openclaw-plugin", openclaw_home / "plugin-skills"),
                ("openclaw-plugin", Path("/usr/local/lib/node_modules/openclaw/dist/extensions/browser/skills")),
            ]
        )
    if include_builtin:
        sources.append(("openclaw-builtin", Path("/usr/local/lib/node_modules/openclaw/skills")))
    return sources


def install_openclaw(options: OpenClawInstallOptions) -> OpenClawInstallReport:
    if options.mode not in INSTALL_MODES:
        raise ValueError(f"Invalid OpenClaw install mode: {options.mode}")

    openclaw_home = Path(options.openclaw_home).expanduser()
    workspace_root = Path(options.workspace_root).expanduser()
    install_root = Path(options.install_root).expanduser()
    repo_root = Path(options.repo_root).expanduser()
    library_root = install_root / "library"
    router_target = workspace_root / "skills" / ROUTER_NAME
    launcher = router_target / "scripts" / "unlimited-skills.sh"
    agents_file = Path(options.agents_file).expanduser() if options.agents_file else workspace_root / "AGENTS.md"
    messages: list[str] = []

    router_source = _router_source(repo_root)
    if not router_source.is_dir():
        raise FileNotFoundError(f"Router skill not found: {router_source}")

    if router_target.exists():
        shutil.rmtree(router_target)
    router_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(router_source, router_target)
    _write_launcher(launcher, repo_root, library_root, options.python_executable)
    _render_router_skill(router_target / "SKILL.md", launcher, library_root)

    agents_patched = False
    if options.patch_agents:
        _patch_agents_file(agents_file, launcher)
        agents_patched = True

    migrations: list[MigrationResult] = []
    if options.mode == "bundled":
        for pack in ("ecc", "superpowers"):
            migrations.append(
                _migrate_source(
                    repo_root / "packs" / pack / "skills",
                    library_root,
                    pack,
                    skip_existing_names=False,
                    registry_collection=True,
                )
            )

    for collection, source_root in _openclaw_sources(openclaw_home, workspace_root, options.include_builtin, options.include_plugin_skills):
        migrations.append(
            _migrate_source(
                source_root,
                library_root,
                collection,
                exclude_names={ROUTER_NAME},
                skip_existing_names=True,
            )
        )

    if options.mode == "adapt-installed":
        adapt_library(library_root, collection="local", source_pack="local")

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
        messages.append("No OpenClaw source skills were migrated. Check workspace/plugin/builtin paths.")

    return OpenClawInstallReport(
        workspace_root=str(workspace_root),
        library_root=str(library_root),
        mode=options.mode,
        router_target=str(router_target),
        launcher=str(launcher),
        agents_file=str(agents_file) if options.patch_agents else "",
        router_installed=router_target.is_dir(),
        agents_patched=agents_patched,
        lexical_index=lexical_index,
        vector_index=vector_index,
        migrations=migrations,
        messages=messages,
    )


def _default_openclaw_home() -> Path:
    return Path(os.environ.get("OPENCLAW_HOME") or Path.home() / ".openclaw")


def _default_workspace_root(openclaw_home: Path | None = None) -> Path:
    if os.environ.get("OPENCLAW_WORKSPACE"):
        return Path(os.environ["OPENCLAW_WORKSPACE"])
    return (openclaw_home or _default_openclaw_home()) / "workspace"


def _default_install_root() -> Path:
    return Path.home() / ".unlimited-skills"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install the Unlimited Skills OpenClaw adapter.")
    parser.add_argument("--openclaw-home", type=Path, default=_default_openclaw_home())
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--install-root", type=Path, default=_default_install_root())
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--mode", choices=sorted(INSTALL_MODES), default="default")
    parser.add_argument("--agents-file", type=Path)
    parser.add_argument("--no-agents-patch", action="store_true")
    parser.add_argument("--no-builtin", action="store_true")
    parser.add_argument("--no-plugin-skills", action="store_true")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--skip-reindex", action="store_true")
    parser.add_argument("--vector-reindex", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    workspace_root = args.workspace_root or _default_workspace_root(args.openclaw_home)
    report = install_openclaw(
        OpenClawInstallOptions(
            openclaw_home=args.openclaw_home,
            workspace_root=workspace_root,
            install_root=args.install_root,
            repo_root=args.repo_root,
            mode=args.mode,
            agents_file=args.agents_file,
            patch_agents=not args.no_agents_patch,
            include_builtin=not args.no_builtin,
            include_plugin_skills=not args.no_plugin_skills,
            skip_reindex=args.skip_reindex,
            vector_reindex=args.vector_reindex,
            python_executable=args.python_executable,
        )
    )
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2) if args.json else report.format_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
