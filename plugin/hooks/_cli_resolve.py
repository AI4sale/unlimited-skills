"""Shared CLI resolution for the Unlimited Skills Claude Code hooks.

The old hooks gated on ``shutil.which("unlimited-skills")`` only, so every
working install whose CLI was not on PATH (the common case: venv install +
rendered launchers) got the "install the CLI" nag instead of the router
contract. This module resolves the CLI through a fallback chain:

1. ``UNLIMITED_SKILLS_CLI`` env var (explicit operator override);
2. ``unlimited-skills`` on PATH;
3. the standard install venv (``~/.unlimited-skills/.venv``);
4. the rendered launchers under ``<claude home>/skills/unlimited-skills/scripts/``.

Each candidate is returned as an argv prefix (a list), because launchers need
an interpreter (`powershell -File` / `bash`). Pure stdlib; never raises.
"""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")


def _install_root() -> Path:
    return Path(os.environ.get("UNLIMITED_SKILLS_INSTALL_ROOT") or Path.home() / ".unlimited-skills")


def resolve_cli_command() -> list[str] | None:
    """Return an argv prefix that runs the unlimited-skills CLI, or None."""
    # Multi-token override, e.g. 'C:/py/python.exe -m unlimited_skills'
    # (use forward slashes in paths; the value is shlex-split).
    override = os.environ.get("UNLIMITED_SKILLS_CLI", "").strip()
    if override:
        try:
            parts = shlex.split(override)
        except ValueError:
            parts = [override]
        return parts or None

    on_path = shutil.which("unlimited-skills")
    if on_path:
        return [on_path]

    venv = _install_root() / ".venv"
    for candidate in (
        venv / "Scripts" / "unlimited-skills.exe",
        venv / "Scripts" / "unlimited-skills",
        venv / "bin" / "unlimited-skills",
    ):
        try:
            if candidate.is_file():
                return [str(candidate)]
        except OSError:
            continue

    scripts_dir = _claude_home() / "skills" / "unlimited-skills" / "scripts"
    ps_launcher = scripts_dir / "unlimited-skills.ps1"
    sh_launcher = scripts_dir / "unlimited-skills.sh"
    try:
        if sys.platform == "win32" and ps_launcher.is_file():
            return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps_launcher)]
        if sh_launcher.is_file():
            bash = shutil.which("bash")
            if bash:
                return [bash, str(sh_launcher)]
        if ps_launcher.is_file():
            pwsh = shutil.which("pwsh") or shutil.which("powershell")
            if pwsh:
                return [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps_launcher)]
    except OSError:
        pass
    return None


def display_command(command: list[str]) -> str:
    """Human-readable form of the argv prefix for contract text."""
    return " ".join(f'"{part}"' if " " in part else part for part in command)
