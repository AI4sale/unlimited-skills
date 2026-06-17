"""`unlimited-skills sync-inject` command wrapper."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _env_home(var: str, default_subdir: str) -> Path:
    value = os.environ.get(var) or ""
    return Path(value).expanduser() if value else Path.home() / default_subdir


def _default_project_root() -> Path:
    value = os.environ.get("UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or ""
    return Path(value).expanduser() if value else Path.cwd()


def _default_openclaw_workspace(openclaw_home: Path) -> Path:
    value = os.environ.get("OPENCLAW_WORKSPACE") or ""
    return Path(value).expanduser() if value else openclaw_home / "workspace"


def cmd_sync_inject(args: argparse.Namespace) -> int:
    from ..sync_inject import refresh_injects, report_as_dict

    claude_home = Path(args.claude_home).expanduser() if getattr(args, "claude_home", "") else _env_home("CLAUDE_HOME", ".claude")
    codex_home = Path(args.codex_home).expanduser() if getattr(args, "codex_home", "") else _env_home("CODEX_HOME", ".codex")
    hermes_home = Path(args.hermes_home).expanduser() if getattr(args, "hermes_home", "") else _env_home("HERMES_HOME", ".hermes")
    openclaw_home = Path(args.openclaw_home).expanduser() if getattr(args, "openclaw_home", "") else _env_home("OPENCLAW_HOME", ".openclaw")
    openclaw_workspace = (
        Path(args.openclaw_workspace).expanduser()
        if getattr(args, "openclaw_workspace", "")
        else _default_openclaw_workspace(openclaw_home)
    )
    project_root = Path(args.project_root).expanduser() if getattr(args, "project_root", "") else _default_project_root()
    agents = set(args.agent) if getattr(args, "agent", None) else None
    library_root = Path(args.library_root).expanduser() if getattr(args, "library_root", "") else None
    repo_root = Path(args.repo_root).expanduser() if getattr(args, "repo_root", "") else None

    report = refresh_injects(
        claude_home=claude_home,
        codex_home=codex_home,
        hermes_home=hermes_home,
        project_root=project_root,
        openclaw_home=openclaw_home,
        openclaw_workspace=openclaw_workspace,
        agents=agents,
        patch_global=not getattr(args, "no_global", False),
        patch_project=not getattr(args, "no_project", False),
        backup=not getattr(args, "no_backup", False),
        heal_launchers=getattr(args, "heal_launchers", False),
        python_executable=sys.executable,
        library_root=library_root,
        repo_root=repo_root,
    )
    if getattr(args, "json", False):
        print(json.dumps(report_as_dict(report), ensure_ascii=False, indent=2))
    else:
        print(report.format_text())
    return 0 if report.ok else 1
