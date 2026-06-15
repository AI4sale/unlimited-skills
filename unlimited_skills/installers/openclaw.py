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
from unlimited_skills.cli import index_path, save_index, vector_meta_path, vector_sidecar_path
from unlimited_skills.hub import remote_config_path

from .common import InstallTransaction, MigrationResult, migrate_source, rollback_install
from .remote import RemoteHubInstallOptions, configure_remote_if_enabled, remote_messages, remote_report_lines, render_remote_router_block

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
    remote: RemoteHubInstallOptions = field(default_factory=RemoteHubInstallOptions)


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
    remote_config: str = ""
    remote_first: bool = False
    remote_hub_url: str = ""
    remote_fallback: str = "local_allowed"
    remote_token_source: str = ""
    rollback_manifest: str = ""
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
                "",
                "Rollback:",
                f"  manifest: {self.rollback_manifest or '<none>'}",
            ]
        )
        lines.extend(["", *remote_report_lines(
            RemoteHubInstallOptions(
                remote_first=self.remote_first,
                remote_hub_url=self.remote_hub_url,
                hub_token_env=self.remote_token_source.removeprefix("env:") if self.remote_token_source.startswith("env:") else "",
                hub_token="stored" if self.remote_token_source == "private remote.json" else "",
                remote_fallback=self.remote_fallback,
            ),
            self.remote_config,
        )])
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
        f"exec {sh_python} -m unlimited_skills --root {sh_library_root} \"$@\"\n",
        encoding="utf-8",
    )
    try:
        launcher.chmod(0o755)
    except OSError:
        pass


def _render_router_skill(router_skill: Path, launcher: Path, library_root: Path, remote: RemoteHubInstallOptions) -> None:
    text = router_skill.read_text(encoding="utf-8", errors="replace")
    replacements = {
        "{{OPENCLAW_SH_LAUNCHER}}": launcher.as_posix(),
        "{{UNLIMITED_SKILLS_LIBRARY_ROOT}}": library_root.as_posix(),
        "{{REMOTE_HUB_ROUTER_BLOCK}}": render_remote_router_block("openclaw", launcher.as_posix(), remote),
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
            "A generated inventory of proven skills (checklists, workflows, regression recipes) that is deliberately NOT in the always-loaded skill list. A 1-second lookup often replaces 20 minutes of rediscovery because the library has shipped-and-tested procedures for recurring tasks.",
            "",
            "RUN this single command BEFORE starting every substantive work phase that matches a trigger below. It costs ~1 second and returns at most one compact card, one name hint, or nothing:",
            "",
            "```bash",
            f"\"{launcher_text}\" suggest \"<3-8 keyword phase summary>\" --json --card --limit 1",
            "```",
            "",
            "TRIGGERS (any one suffices):",
            "",
            "- writing or reviewing code in a named language/framework (React, Python, Go, n8n, ...)",
            "- review, audit, or security check of any artifact",
            "- writing tests, fixing a bug, or debugging a failure",
            "- git/GitHub workflows: branches, PRs, releases, changelogs",
            "- writing prose: docs, posts, outreach, marketing, research reports",
            "- planning, refactoring, migrations, deployments, ops procedures",
            "- the user names a skill, workflow, or asks \"what can you do\"",
            "",
            "PHASE FRESHNESS: a `suggest` result is fresh only for the current substantive phase. Re-query at phase boundaries such as planning -> implementation, backend/API -> frontend/UI, implementation -> testing, testing -> debugging, implementation -> security review, code -> docs, or docs -> release/git workflow. A no-hit result is also scoped only to the current phase.",
            "",
            "ACT on the result: if a suggestion looks relevant, run `view <skill-name>` with the same launcher and follow it. If `suggest` returns nothing, proceed with the current phase; do not search again with synonyms for that same phase. Anti-spam: at most one `suggest` probe per phase unless the user explicitly asks for a broader search. For deeper retrieval use `search \"<query>\" --mode hybrid --limit 8`; for inventory questions use `list --limit 80`.",
            "",
            "TIER BEHAVIOR: silence means no confident match; a name hint means inspect that skill if it looks relevant; a compact card means a high-confidence match for this phase.",
            "",
            "SKIP only when a relevant skill is already active in the current context.",
            "<!-- END UNLIMITED SKILLS -->",
            "",
        ]
    )
    patch_agents_file(agents_file, block)


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
    messages.extend(remote_messages(options.remote))

    router_source = _router_source(repo_root)
    if not router_source.is_dir():
        raise FileNotFoundError(f"Router skill not found: {router_source}")

    transaction = InstallTransaction("openclaw", install_root)
    agents_patched = False
    migrations: list[MigrationResult] = []
    lexical_index = "skipped"
    vector_index = "skipped"

    try:
        transaction.stage_dir_replace(router_target)
        router_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(router_source, router_target)
        _write_launcher(launcher, repo_root, library_root, options.python_executable)
        transaction.snapshot_file(remote_config_path(install_root))
        remote_config = configure_remote_if_enabled(options.remote, install_root)
        _render_router_skill(router_target / "SKILL.md", launcher, library_root, options.remote)

        if options.patch_agents:
            transaction.snapshot_file(agents_file)
            _patch_agents_file(agents_file, launcher)
            agents_patched = True

        if options.mode == "bundled":
            for pack in ("ecc", "superpowers"):
                migrations.append(
                    migrate_source(
                        repo_root / "packs" / pack / "skills",
                        library_root,
                        pack,
                        skip_existing_names=False,
                        registry_collection=True,
                        transaction=transaction,
                    )
                )

        for collection, source_root in _openclaw_sources(openclaw_home, workspace_root, options.include_builtin, options.include_plugin_skills):
            migrations.append(
                migrate_source(
                    source_root,
                    library_root,
                    collection,
                    exclude_names={ROUTER_NAME},
                    skip_existing_names=True,
                    transaction=transaction,
                )
            )

        if options.mode == "adapt-installed":
            adapt_library(library_root, collection="local", source_pack="local")
            messages.append("adapt-installed rewrites skills in place; those rewrites are not covered by the rollback manifest.")

        if not options.skip_reindex:
            transaction.snapshot_file(index_path(library_root))
            save_index(library_root)
            lexical_index = "rebuilt"
    except BaseException:
        transaction.rollback_now()
        raise

    if options.vector_reindex:
        transaction.snapshot_file(vector_sidecar_path(library_root))
        transaction.snapshot_file(vector_meta_path(library_root))
        try:
            subprocess.run(
                [options.python_executable, "-m", "unlimited_skills.cli", "--root", str(library_root), "vector-reindex", "--verbose"],
                check=True,
            )
            vector_index = "rebuilt"
        except Exception as exc:  # pragma: no cover - depends on optional deps
            vector_index = "failed"
            messages.append(f"Vector reindex failed: {exc}")

    rollback_manifest = transaction.write_manifest(
        extra={
            "workspace_root": str(workspace_root),
            "library_root": str(library_root),
            "mode": options.mode,
            "router_target": str(router_target),
        }
    )

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
        remote_config=remote_config,
        remote_first=options.remote.enabled,
        remote_hub_url=options.remote.remote_hub_url if options.remote.enabled else "",
        remote_fallback=options.remote.remote_fallback,
        remote_token_source=(f"env:{options.remote.hub_token_env}" if options.remote.hub_token_env else ("private remote.json" if options.remote.hub_token else "")),
        rollback_manifest=str(rollback_manifest),
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
    parser.add_argument("--remote-first", action="store_true")
    parser.add_argument("--no-remote", action="store_true")
    parser.add_argument("--remote-hub-url", default="")
    parser.add_argument("--hub-token-env", default="")
    parser.add_argument("--hub-token", default="")
    parser.add_argument("--remote-fallback", choices=sorted({"local_allowed", "hub_required"}), default="local_allowed")
    parser.add_argument("--rollback", type=Path, metavar="MANIFEST", help="Roll back a previous install from its manifest instead of installing.")
    parser.add_argument("--rollback-apply", action="store_true", help="Actually restore files during --rollback. Omit for dry-run.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.rollback:
        rollback_report = rollback_install(args.rollback, apply=args.rollback_apply)
        print(json.dumps(asdict(rollback_report), ensure_ascii=False, indent=2) if args.json else rollback_report.format_text())
        return 0
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
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2) if args.json else report.format_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
