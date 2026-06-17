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

from unlimited_skills.agents_patch import (
    CONTRACT_VERSION,
    UNLIMITED_END,
    UNLIMITED_START,
    contract_stamp,
    parse_contract_version,
)
from unlimited_skills.adapters import adapt_library
from unlimited_skills.cli import index_path, save_index, vector_meta_path, vector_sidecar_path
from unlimited_skills.hub import remote_config_path

from .common import InstallTransaction, MigrationResult, migrate_source, rollback_install
from .remote import RemoteHubInstallOptions, configure_remote_if_enabled, remote_messages, remote_report_lines, render_remote_router_block

INSTALL_MODES = {"default", "bundled", "adapt-installed"}
ROUTER_NAME = "unlimited-skills"

# The CLAUDE.md managed block shares the router-inject contract version with
# every other agent surface (see ``agents_patch.CONTRACT_VERSION``). Aliases are
# kept here for backwards-compatible imports.
CLAUDE_CONTRACT_VERSION = CONTRACT_VERSION
CLAUDE_BLOCK_START = UNLIMITED_START
CLAUDE_BLOCK_END = UNLIMITED_END
_contract_stamp = contract_stamp
parse_claude_contract_version = parse_contract_version


def apply_claude_block(text: str, block: str) -> str:
    """Insert or replace the managed UNLIMITED SKILLS block in CLAUDE.md text.

    Idempotent + upgrade-safe: an existing marked block (any contract version)
    is replaced in place; otherwise the block is appended. Keying on the
    BEGIN/END markers means a stale block is upgraded rather than duplicated.
    Applying the same block twice is a no-op (byte-for-byte stable), so
    `sync-inject` reports ``changed=False`` on an already-current file.
    """
    block = block.strip()
    start = text.find(CLAUDE_BLOCK_START)
    end = text.find(CLAUDE_BLOCK_END)
    if start >= 0 and end >= start:
        before = text[:start].rstrip()
        after = text[end + len(CLAUDE_BLOCK_END):].strip()
    elif text.strip():
        before = text.rstrip()
        after = ""
    else:
        before = ""
        after = ""
    out = (before + "\n\n") if before else ""
    out += block + "\n"
    if after:
        out += "\n" + after + "\n"
    return out


@dataclass
class ClaudeCodeInstallOptions:
    claude_home: Path
    project_root: Path
    install_root: Path
    repo_root: Path
    mode: str = "default"
    claude_file: Path | None = None
    patch_claude: bool = True
    patch_global_claude: bool = True
    include_project_skills: bool = True
    register_hooks: bool = True
    skip_reindex: bool = False
    vector_reindex: bool = False
    python_executable: str = sys.executable
    remote: RemoteHubInstallOptions = field(default_factory=RemoteHubInstallOptions)


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
    global_claude_file: str = ""
    router_installed: bool = False
    claude_patched: bool = False
    global_claude_patched: bool = False
    hooks_registered: bool = False
    hooks_settings_file: str = ""
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
            f"  project patched: {'yes' if self.claude_patched else 'no'}",
            f"  project path: {self.claude_file or '<skipped>'}",
            f"  global patched: {'yes' if self.global_claude_patched else 'no'}",
            f"  global path: {self.global_claude_file or '<skipped>'}",
            "",
            "Hooks:",
            f"  registered: {'yes' if self.hooks_registered else 'no'}",
            f"  settings file: {self.hooks_settings_file or '<skipped>'}",
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
        f"exec {sh_python} -m unlimited_skills --root {sh_library_root} \"$@\"\n",
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
        f"& {json.dumps(python_executable)} -m unlimited_skills --root {json.dumps(str(library_root))} @Args\n",
        encoding="utf-8",
    )


def _render_router_skill(router_skill: Path, sh_launcher: Path, ps_launcher: Path, library_root: Path, remote: RemoteHubInstallOptions) -> None:
    text = router_skill.read_text(encoding="utf-8", errors="replace")
    replacements = {
        "{{CLAUDE_SH_LAUNCHER}}": sh_launcher.as_posix(),
        "{{CLAUDE_PS_LAUNCHER}}": ps_launcher.as_posix(),
        "{{UNLIMITED_SKILLS_LIBRARY_ROOT}}": library_root.as_posix(),
        "{{REMOTE_HUB_ROUTER_BLOCK}}": render_remote_router_block("claude-code", sh_launcher.as_posix(), remote),
    }
    for needle, value in replacements.items():
        text = text.replace(needle, value)
    router_skill.write_text(text, encoding="utf-8")


def router_block_lines(sh_text: str, ps_text: str) -> list[str]:
    """The managed CLAUDE.md router block (A0 contract).

    Regenerable: re-running the installer replaces everything between the
    BEGIN/END UNLIMITED SKILLS markers with the current contract.
    """
    return [
        CLAUDE_BLOCK_START,
        _contract_stamp(),
        "## Unlimited Skills Library",
        "",
        "A generated inventory of proven skills (checklists, workflows, regression recipes) that is deliberately NOT in your skill list. A 1-second lookup often replaces 20 minutes of rediscovery because the library has shipped-and-tested procedures for recurring tasks.",
        "",
        "RUN this single command BEFORE starting every substantive work phase that matches a trigger below. It costs ~1 second and returns at most one compact card, one name hint, or nothing:",
        "",
        "```bash",
        f"\"{sh_text}\" suggest \"<3-8 keyword phase summary>\" --json --card --limit 1",
        "```",
        "",
        "On Windows PowerShell:",
        "",
        "```powershell",
        f"powershell -NoProfile -ExecutionPolicy Bypass -File \"{ps_text}\" suggest \"<3-8 keyword phase summary>\" --json --card --limit 1",
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
        "MULTILINGUAL INSTALL — IMPORTANT: if you have EVER conversed with this user in a language other than English, make the vector + warm-daemon setup your DEFAULT install, not lexical-only. Lexical search scores non-English prompts at zero, so without a multilingual embedding sidecar AND a warm model the router returns nothing for their tasks. Build the sidecar with `" + sh_text + " vector-reindex` and keep the embedding model warm by running the daemon `" + sh_text + " serve`.",
        "",
        "SKIP only when a relevant skill is already active in the current context.",
        "<!-- END UNLIMITED SKILLS -->",
        "",
    ]


def _patch_claude_file(claude_file: Path, sh_launcher: Path, ps_launcher: Path) -> None:
    claude_file.parent.mkdir(parents=True, exist_ok=True)
    block = "\n".join(router_block_lines(sh_launcher.as_posix(), ps_launcher.as_posix()))
    text = claude_file.read_text(encoding="utf-8", errors="replace") if claude_file.is_file() else ""
    claude_file.write_text(apply_claude_block(text, block), encoding="utf-8")


HOOK_SCRIPTS = ("_cli_resolve.py", "session_start.py", "user_prompt_submit.py")
HOOK_EVENTS = {"SessionStart": "session_start.py", "UserPromptSubmit": "user_prompt_submit.py"}
HOOK_TIMEOUTS = {"SessionStart": 15, "UserPromptSubmit": 10}


def _copy_hook_scripts(repo_root: Path, hooks_target: Path) -> bool:
    source_dir = repo_root / "plugin" / "hooks"
    if not all((source_dir / script).is_file() for script in HOOK_SCRIPTS):
        return False
    hooks_target.mkdir(parents=True, exist_ok=True)
    for script in HOOK_SCRIPTS:
        shutil.copy2(source_dir / script, hooks_target / script)
    return True


def _is_unlimited_skills_hook_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks") or []:
        command = str(hook.get("command") or "") if isinstance(hook, dict) else ""
        if "unlimited-skills" in command and any(script in command for script in HOOK_SCRIPTS):
            return True
    return False


def _register_claude_hooks(settings_file: Path, hooks_dir: Path, python_executable: str) -> tuple[bool, str]:
    """Merge SessionStart/UserPromptSubmit hook commands into settings.json.

    Idempotent: previous unlimited-skills hook entries are replaced. Fails
    soft (returns False + reason) when the settings file is unparseable, so
    the install never destroys user configuration.
    """
    try:
        text = settings_file.read_text(encoding="utf-8") if settings_file.is_file() else ""
    except OSError as exc:
        return False, f"could not read {settings_file}: {exc}"
    try:
        payload = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return False, f"{settings_file} is not valid JSON; hooks were not registered."
    if not isinstance(payload, dict):
        return False, f"{settings_file} does not contain a JSON object; hooks were not registered."

    hooks_section = payload.setdefault("hooks", {})
    if not isinstance(hooks_section, dict):
        return False, f"{settings_file} has a non-object 'hooks' section; hooks were not registered."

    for event, script in HOOK_EVENTS.items():
        entries = hooks_section.get(event)
        if not isinstance(entries, list):
            entries = []
        entries = [entry for entry in entries if not _is_unlimited_skills_hook_entry(entry)]
        command = f'"{python_executable}" "{hooks_dir / script}"'
        entries.append({"hooks": [{"type": "command", "command": command, "timeout": HOOK_TIMEOUTS[event]}]})
        hooks_section[event] = entries

    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True, ""


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

    transaction = InstallTransaction("claude-code", install_root)
    global_claude_file = claude_home / "CLAUDE.md"
    settings_file = claude_home / "settings.json"
    claude_patched = False
    global_claude_patched = False
    hooks_registered = False
    migrations: list[MigrationResult] = []
    lexical_index = "skipped"
    vector_index = "skipped"

    try:
        transaction.stage_dir_replace(router_target)
        router_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(router_source, router_target)
        _write_launchers(sh_launcher, ps_launcher, repo_root, library_root, project_root, options.python_executable)
        transaction.snapshot_file(remote_config_path(install_root))
        remote_config = configure_remote_if_enabled(options.remote, install_root)
        messages.extend(remote_messages(options.remote))

        _render_router_skill(router_target / "SKILL.md", sh_launcher, ps_launcher, library_root, options.remote)

        if options.patch_claude:
            transaction.snapshot_file(claude_file)
            _patch_claude_file(claude_file, sh_launcher, ps_launcher)
            claude_patched = True

        # The project CLAUDE.md is only loaded when Claude Code runs inside that
        # project, so the router contract must also live in the global memory file
        # that is loaded for every session.
        if options.patch_global_claude:
            same_file = False
            if options.patch_claude:
                try:
                    same_file = global_claude_file.resolve() == claude_file.resolve()
                except OSError:
                    same_file = global_claude_file == claude_file
            if same_file:
                global_claude_patched = claude_patched
            else:
                transaction.snapshot_file(global_claude_file)
                _patch_claude_file(global_claude_file, sh_launcher, ps_launcher)
                global_claude_patched = True

        # Deterministic per-session / per-prompt hook delivery for the legacy
        # (non-plugin) install path: copy the plugin hook scripts next to the
        # router and register them in the Claude Code settings file.
        if options.register_hooks:
            hooks_dir = router_target / "hooks"
            if _copy_hook_scripts(repo_root, hooks_dir):
                transaction.snapshot_file(settings_file)
                hooks_registered, hook_message = _register_claude_hooks(settings_file, hooks_dir, options.python_executable)
                if hook_message:
                    messages.append(hook_message)
            else:
                messages.append("Plugin hook scripts not found in the repo; Claude Code hooks were not registered.")

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

        migrations.append(
            migrate_source(
                claude_home / "skills",
                library_root,
                "claude-code",
                exclude_names={ROUTER_NAME},
                skip_existing_names=True,
                transaction=transaction,
            )
        )

        if options.include_project_skills:
            migrations.append(
                migrate_source(
                    project_root / ".claude" / "skills",
                    library_root,
                    "claude-code-project",
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
            "claude_home": str(claude_home),
            "project_root": str(project_root),
            "library_root": str(library_root),
            "mode": options.mode,
            "router_target": str(router_target),
        }
    )

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
        global_claude_file=str(global_claude_file) if options.patch_global_claude else "",
        router_installed=router_target.is_dir(),
        claude_patched=claude_patched,
        global_claude_patched=global_claude_patched,
        hooks_registered=hooks_registered,
        hooks_settings_file=str(settings_file) if options.register_hooks else "",
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
    parser.add_argument("--no-global-claude-patch", action="store_true")
    parser.add_argument("--no-project-skills", action="store_true")
    parser.add_argument("--no-hooks", action="store_true", help="Do not register SessionStart/UserPromptSubmit hooks in Claude Code settings.json.")
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
    report = install_claude_code(
        ClaudeCodeInstallOptions(
            claude_home=args.claude_home,
            project_root=args.project_root,
            install_root=args.install_root,
            repo_root=args.repo_root,
            mode=args.mode,
            claude_file=args.claude_file,
            patch_claude=not args.no_claude_patch,
            patch_global_claude=not args.no_global_claude_patch,
            include_project_skills=not args.no_project_skills,
            register_hooks=not args.no_hooks,
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
