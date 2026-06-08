from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from unlimited_skills.cli import save_index

from .common import copy_skill_tree, count_skill_files, iter_skill_dirs, move_skill_tree, prune_empty_parents
from .remote import RemoteHubInstallOptions, configure_remote_if_enabled, remote_messages, remote_report_lines, render_remote_router_block, validate_remote_options

INSTALL_MODES = {"router-only", "evacuate-visible-skills"}
ROUTER_NAME = "unlimited-skills"


@dataclass
class HermesInstallOptions:
    hermes_home: Path
    install_root: Path
    repo_root: Path
    mode: str = "router-only"
    apply: bool = False
    skip_reindex: bool = False
    python_executable: str = sys.executable
    remote: RemoteHubInstallOptions = field(default_factory=RemoteHubInstallOptions)


@dataclass
class HermesInstallReport:
    visible_root: str
    library_root: str
    mode: str
    dry_run: bool
    before_visible_count: int
    migrated_count: int
    after_visible_count: int
    visible_skills_after: list[str] = field(default_factory=list)
    router_installed: bool = False
    launcher: str = ""
    lexical_index: str = "skipped"
    vector_index: str = "skipped"
    remote_config: str = ""
    remote_first: bool = False
    remote_hub_url: str = ""
    remote_fallback: str = "local_allowed"
    remote_token_source: str = ""
    rollback_manifest: str | None = None
    messages: list[str] = field(default_factory=list)

    def format_text(self) -> str:
        lines = [
            "Hermes Unlimited Skills install report",
            "",
            "Visible Hermes skill root:",
            f"  {self.visible_root}",
            "",
            "Before:",
            f"  visible SKILL.md count: {self.before_visible_count}",
            "",
            "Migrated to library:",
            "  local path: local/hermes/skills",
            f"  migrated skills: {self.migrated_count}",
            "",
            "After:",
            f"  visible SKILL.md count: {self.after_visible_count}",
            "  visible skills:",
        ]
        if self.visible_skills_after:
            lines.extend(f"    - {name}" for name in self.visible_skills_after)
        else:
            lines.append("    - <none>")
        lines.extend(
            [
                "",
                "Router:",
                f"  installed: {'yes' if self.router_installed else 'no'}",
                f"  launcher: {self.launcher or '<not installed>'}",
                "",
                "Index:",
                f"  lexical index: {self.lexical_index}",
                f"  vector index: {self.vector_index}",
                "",
                *remote_report_lines(
                    RemoteHubInstallOptions(
                        remote_first=self.remote_first,
                        remote_hub_url=self.remote_hub_url,
                        hub_token_env=self.remote_token_source.removeprefix("env:") if self.remote_token_source.startswith("env:") else "",
                        hub_token="stored" if self.remote_token_source == "private remote.json" else "",
                        remote_fallback=self.remote_fallback,
                    ),
                    self.remote_config,
                ),
                "",
                "Rollback:",
                f"  manifest: {self.rollback_manifest or '<none>'}",
            ]
        )
        if self.messages:
            lines.extend(["", "Messages:"])
            lines.extend(f"  - {message}" for message in self.messages)
        return "\n".join(lines)


@dataclass
class HermesRollbackReport:
    manifest: str
    visible_root: str
    dry_run: bool
    restored_count: int
    removed_router: bool
    messages: list[str] = field(default_factory=list)

    def format_text(self) -> str:
        lines = [
            "Hermes Unlimited Skills rollback report",
            "",
            f"Manifest: {self.manifest}",
            f"Visible Hermes skill root: {self.visible_root}",
            f"Dry run: {'yes' if self.dry_run else 'no'}",
            f"Restored skills: {self.restored_count}",
            f"Removed router: {'yes' if self.removed_router else 'no'}",
        ]
        if self.messages:
            lines.extend(["", "Messages:"])
            lines.extend(f"  - {message}" for message in self.messages)
        return "\n".join(lines)


def count_visible_skills(visible_root: Path) -> int:
    return count_skill_files(visible_root)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _router_source(repo_root: Path) -> Path:
    hermes_router = repo_root / "skills" / "router-hermes"
    if hermes_router.is_dir():
        return hermes_router
    return repo_root / "skills" / "skill-router"


def _launcher_paths(visible_root: Path) -> tuple[Path, Path]:
    scripts_dir = visible_root / ROUTER_NAME / "scripts"
    return scripts_dir / "unlimited-skills.sh", scripts_dir / "unlimited-skills.ps1"


def _write_launchers(sh_launcher: Path, ps_launcher: Path, repo_root: Path, library_root: Path, python_executable: str) -> None:
    sh_launcher.parent.mkdir(parents=True, exist_ok=True)
    sh_repo_root = shlex.quote(str(repo_root).replace("\\", "/"))
    sh_library_root = shlex.quote(str(library_root).replace("\\", "/"))
    sh_python = shlex.quote(str(python_executable).replace("\\", "/"))
    sh_launcher.write_text(
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
        f"& {json.dumps(python_executable)} -m unlimited_skills.cli --root {json.dumps(str(library_root))} @Args\n",
        encoding="utf-8",
    )


def _render_router_skill(router_skill: Path, sh_launcher: Path, ps_launcher: Path, library_root: Path, remote: RemoteHubInstallOptions) -> None:
    text = router_skill.read_text(encoding="utf-8", errors="replace")
    replacements = {
        "{{HERMES_SH_LAUNCHER}}": sh_launcher.as_posix(),
        "{{HERMES_PS_LAUNCHER}}": ps_launcher.as_posix(),
        "{{UNLIMITED_SKILLS_LIBRARY_ROOT}}": library_root.as_posix(),
        "{{REMOTE_HUB_ROUTER_BLOCK}}": render_remote_router_block("hermes", sh_launcher.as_posix(), remote),
    }
    for needle, value in replacements.items():
        text = text.replace(needle, value)
    router_skill.write_text(text, encoding="utf-8")


def _visible_skill_names(visible_root: Path) -> list[str]:
    return sorted({path.parent.name for path in visible_root.rglob("SKILL.md")}) if visible_root.is_dir() else []


def _write_manifest(
    manifest_path: Path,
    *,
    visible_root: Path,
    library_root: Path,
    backup_root: Path,
    before_visible_count: int,
    items: list[dict[str, str]],
    router_target: Path,
) -> None:
    payload = {
        "agent": "hermes",
        "created_at": _iso_now(),
        "visible_root": str(visible_root),
        "library_root": str(library_root),
        "backup_root": str(backup_root),
        "before_visible_count": before_visible_count,
        "router_target": str(router_target),
        "items": items,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def install_hermes(options: HermesInstallOptions) -> HermesInstallReport:
    if options.mode not in INSTALL_MODES:
        raise ValueError(f"Invalid Hermes install mode: {options.mode}")

    hermes_home = Path(options.hermes_home).expanduser()
    install_root = Path(options.install_root).expanduser()
    repo_root = Path(options.repo_root).expanduser()
    visible_root = hermes_home / "skills"
    library_root = install_root / "library"
    library_skills = library_root / "local" / "hermes" / "skills"
    router_target = visible_root / ROUTER_NAME
    sh_launcher, ps_launcher = _launcher_paths(visible_root)

    before_count = count_visible_skills(visible_root)
    router_target_resolved = router_target.resolve() if router_target.exists() else router_target
    skill_dirs = [
        skill_dir
        for skill_dir in iter_skill_dirs(visible_root)
        if skill_dir.resolve() != router_target_resolved
    ]

    messages: list[str] = []
    validate_remote_options(options.remote)
    messages.extend(remote_messages(options.remote))
    if before_count == 0:
        messages.append(f"No Hermes skills found under {visible_root}. Nothing to evacuate. Router can still be installed.")
    if not options.apply:
        messages.append("Dry run. No files were changed.")

    report = HermesInstallReport(
        visible_root=str(visible_root),
        library_root=str(library_root),
        mode=options.mode,
        dry_run=not options.apply,
        before_visible_count=before_count,
        migrated_count=len(skill_dirs),
        after_visible_count=before_count,
        visible_skills_after=_visible_skill_names(visible_root),
        router_installed=router_target.is_dir(),
        launcher=str(sh_launcher),
        remote_first=options.remote.enabled,
        remote_hub_url=options.remote.remote_hub_url if options.remote.enabled else "",
        remote_fallback=options.remote.remote_fallback,
        remote_token_source=(f"env:{options.remote.hub_token_env}" if options.remote.hub_token_env else ("private remote.json" if options.remote.hub_token else "")),
        messages=messages,
    )

    if not options.apply:
        return report

    router_source = _router_source(repo_root)
    if not router_source.is_dir():
        raise FileNotFoundError(f"Router skill not found: {router_source}")

    backup_root = install_root / "backups" / f"hermes-visible-skills-{_timestamp()}"
    backup_visible_root = backup_root / "visible-skills"
    manifest_path = backup_root / "manifest.json"
    manifest_items: list[dict[str, str]] = []

    for skill_dir in sorted(skill_dirs, key=lambda path: len(path.relative_to(visible_root).parts), reverse=True):
        relative = skill_dir.relative_to(visible_root)
        library_destination = library_skills / relative
        copy_skill_tree(skill_dir, library_destination)
        if options.mode == "evacuate-visible-skills":
            backup_destination = backup_visible_root / relative
            move_skill_tree(skill_dir, backup_destination)
            prune_empty_parents(skill_dir.parent, visible_root)
            manifest_items.append(
                {
                    "name": skill_dir.name,
                    "relative": str(relative),
                    "library_destination": str(library_destination),
                    "backup_destination": str(backup_destination),
                }
            )

    if router_target.exists():
        shutil.rmtree(router_target)
    router_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(router_source, router_target)
    _write_launchers(sh_launcher, ps_launcher, repo_root, library_root, options.python_executable)
    remote_config = configure_remote_if_enabled(options.remote, install_root)
    _render_router_skill(router_target / "SKILL.md", sh_launcher, ps_launcher, library_root, options.remote)

    rollback_manifest: str | None = None
    if options.mode == "evacuate-visible-skills":
        _write_manifest(
            manifest_path,
            visible_root=visible_root,
            library_root=library_root,
            backup_root=backup_root,
            before_visible_count=before_count,
            items=manifest_items,
            router_target=router_target,
        )
        rollback_manifest = str(manifest_path)

    lexical_index = "skipped"
    if not options.skip_reindex:
        save_index(library_root)
        lexical_index = "rebuilt"

    return HermesInstallReport(
        visible_root=str(visible_root),
        library_root=str(library_root),
        mode=options.mode,
        dry_run=False,
        before_visible_count=before_count,
        migrated_count=len(skill_dirs),
        after_visible_count=count_visible_skills(visible_root),
        visible_skills_after=_visible_skill_names(visible_root),
        router_installed=router_target.is_dir(),
        launcher=str(sh_launcher),
        lexical_index=lexical_index,
        vector_index="skipped",
        remote_config=remote_config,
        remote_first=options.remote.enabled,
        remote_hub_url=options.remote.remote_hub_url if options.remote.enabled else "",
        remote_fallback=options.remote.remote_fallback,
        remote_token_source=(f"env:{options.remote.hub_token_env}" if options.remote.hub_token_env else ("private remote.json" if options.remote.hub_token else "")),
        rollback_manifest=rollback_manifest,
        messages=messages,
    )


def rollback_hermes(manifest: Path, apply: bool = False) -> HermesRollbackReport:
    manifest = Path(manifest).expanduser()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    visible_root = Path(payload["visible_root"])
    router_target = Path(payload.get("router_target") or visible_root / ROUTER_NAME)
    items = payload.get("items") or []
    messages = [] if apply else ["Dry run. No files were changed."]

    if apply:
        if router_target.exists():
            shutil.rmtree(router_target)
        for item in items:
            backup_destination = Path(item["backup_destination"])
            restore_destination = visible_root / item["relative"]
            if restore_destination.exists():
                shutil.rmtree(restore_destination)
            restore_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup_destination), str(restore_destination))
            prune_empty_parents(backup_destination.parent, Path(payload["backup_root"]) / "visible-skills")

    return HermesRollbackReport(
        manifest=str(manifest),
        visible_root=str(visible_root),
        dry_run=not apply,
        restored_count=len(items),
        removed_router=router_target.exists() is False if apply else router_target.exists(),
        messages=messages,
    )


def _default_hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _default_install_root() -> Path:
    return Path.home() / ".unlimited-skills"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install or roll back the Unlimited Skills Hermes adapter.")
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="Install the Hermes router adapter.")
    install.add_argument("--hermes-home", type=Path, default=_default_hermes_home())
    install.add_argument("--install-root", type=Path, default=_default_install_root())
    install.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    install.add_argument("--mode", choices=sorted(INSTALL_MODES), default="router-only")
    install.add_argument("--python-executable", default=sys.executable)
    install.add_argument("--skip-reindex", action="store_true")
    install.add_argument("--remote-first", action="store_true")
    install.add_argument("--no-remote", action="store_true")
    install.add_argument("--remote-hub-url", default="")
    install.add_argument("--hub-token-env", default="")
    install.add_argument("--hub-token", default="")
    install.add_argument("--remote-fallback", choices=sorted({"local_allowed", "hub_required"}), default="local_allowed")
    install.add_argument("--json", action="store_true", help="Print JSON instead of a text report.")
    install.add_argument("--apply", action="store_true", help="Actually change files. Omit for dry-run.")

    rollback = sub.add_parser("rollback", help="Restore Hermes visible skills from a rollback manifest.")
    rollback.add_argument("--manifest", type=Path, required=True)
    rollback.add_argument("--json", action="store_true", help="Print JSON instead of a text report.")
    rollback.add_argument("--apply", action="store_true", help="Actually change files. Omit for dry-run.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "install":
        report = install_hermes(
            HermesInstallOptions(
                hermes_home=args.hermes_home,
                install_root=args.install_root,
                repo_root=args.repo_root,
                mode=args.mode,
                apply=args.apply,
                skip_reindex=args.skip_reindex,
                python_executable=args.python_executable,
                remote=RemoteHubInstallOptions(
                    remote_first=args.remote_first,
                    remote_hub_url=args.remote_hub_url,
                    hub_token_env=args.hub_token_env,
                    hub_token=args.hub_token,
                    remote_fallback=args.remote_fallback,
                    no_remote=args.no_remote,
                ),
            )
        )
        print(json.dumps(report.__dict__, ensure_ascii=False, indent=2) if args.json else report.format_text())
        return 0
    if args.command == "rollback":
        report = rollback_hermes(args.manifest, apply=args.apply)
        print(json.dumps(report.__dict__, ensure_ascii=False, indent=2) if args.json else report.format_text())
        return 0
    parser.error("missing command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
