"""`unlimited-skills sync-inject` command wrapper."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _env_home(var: str, default_subdir: str) -> Path:
    value = os.environ.get(var) or ""
    return Path(value).expanduser() if value else Path.home() / default_subdir


def _default_project_root() -> Path:
    value = os.environ.get("UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or ""
    return Path(value).expanduser() if value else Path.cwd()


def cmd_sync_inject(args: argparse.Namespace) -> int:
    from ..sync_inject import refresh_injects, report_as_dict

    claude_home = Path(args.claude_home).expanduser() if getattr(args, "claude_home", "") else _env_home("CLAUDE_HOME", ".claude")
    codex_home = Path(args.codex_home).expanduser() if getattr(args, "codex_home", "") else _env_home("CODEX_HOME", ".codex")
    hermes_home = Path(args.hermes_home).expanduser() if getattr(args, "hermes_home", "") else _env_home("HERMES_HOME", ".hermes")
    project_root = Path(args.project_root).expanduser() if getattr(args, "project_root", "") else _default_project_root()
    agents = set(args.agent) if getattr(args, "agent", None) else None

    report = refresh_injects(
        claude_home=claude_home,
        codex_home=codex_home,
        hermes_home=hermes_home,
        project_root=project_root,
        agents=agents,
        patch_global=not getattr(args, "no_global", False),
        patch_project=not getattr(args, "no_project", False),
        backup=not getattr(args, "no_backup", False),
    )
    if getattr(args, "json", False):
        print(json.dumps(report_as_dict(report), ensure_ascii=False, indent=2))
    else:
        print(report.format_text())
    return 0 if report.ok else 1
