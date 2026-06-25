"""Render the router launcher scripts (.sh / .ps1) for every agent surface.

Single source of truth so the installers and ``sync-inject`` produce
byte-identical launchers, and so every launcher carries a version/contract stamp
that lets ``doctor`` and the SessionStart hook detect a launcher left behind by
an older install.

Root-cause fix for the stale-launcher bug
-----------------------------------------
Older launchers hardcoded ``PYTHONPATH=<repo checkout>`` and prepended it to the
process ``PYTHONPATH``. That source checkout SHADOWED the pip-installed package,
so the router kept running whatever version was checked out at first install even
after ``pip install --upgrade`` — the same disease as the stale inject, but on the
executable path. The launcher now runs the INSTALLED package
(``<python> -m unlimited_skills``) with no PYTHONPATH manipulation, so a future
upgrade into the same interpreter is picked up automatically.

A ``PYTHONPATH`` fallback is written *only* for a bare source/editable checkout
where the package is not importable from the interpreter's own ``site-packages``
(probed with ``python -I`` so cwd and ambient ``PYTHONPATH`` cannot mask a missing
install). On the shipped pip-install path the fallback is never emitted.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

from . import __version__

# Bump when the rendered launcher format changes meaningfully. Stamped INSIDE
# each launcher so an upgraded package can detect a launcher written by an older
# install (which used the shadowing PYTHONPATH=<repo> pattern, contract 0) and
# refresh it via `unlimited-skills sync-inject --heal-launchers`.
LAUNCHER_CONTRACT_VERSION = 1
_STAMP_PREFIX = "unlimited-skills-launcher:"


def launcher_stamp(version: int = LAUNCHER_CONTRACT_VERSION) -> str:
    return f"{_STAMP_PREFIX} {version} (pkg {__version__})"


def parse_launcher_contract(text: str) -> int | None:
    """Return the launcher contract version found in launcher text.

    Returns the stamped integer, ``0`` for a launcher that predates the stamp
    (the legacy ``PYTHONPATH=<repo>`` launchers), or ``None`` when the text is not
    one of our launchers at all.
    """
    if "unlimited_skills" not in text:
        return None
    for line in text.splitlines():
        marker = line.find(_STAMP_PREFIX)
        if marker >= 0:
            tail = line[marker + len(_STAMP_PREFIX):].strip()
            number = ""
            for char in tail:
                if char.isdigit():
                    number += char
                else:
                    break
            if number:
                return int(number)
    return 0


def launcher_is_stale(text: str) -> bool:
    version = parse_launcher_contract(text)
    return version is not None and version < LAUNCHER_CONTRACT_VERSION


def resolve_launch_pythonpath(python_executable: str | Path, repo_root: str | Path | None) -> str | None:
    """Return a source-tree PYTHONPATH fallback, or ``None`` for a clean launcher.

    The recorded interpreter is probed in isolated mode (``python -I``) so that
    neither the current working directory nor an ambient ``PYTHONPATH`` can mask a
    package that is not actually installed. When the package imports cleanly the
    launcher needs no ``PYTHONPATH`` (and a later ``pip install --upgrade`` into
    that interpreter is picked up automatically). Only a bare source/editable
    checkout — where the package is reachable solely through ``repo_root`` — gets a
    fallback, and only when ``repo_root`` really contains the package. On any
    probe failure we default to a clean launcher: never re-introduce a shadowing
    path on a guess.
    """
    if repo_root is None:
        return None
    try:
        proc = subprocess.run(
            [str(python_executable), "-I", "-c", "import unlimited_skills"],
            capture_output=True,
            timeout=20,
        )
        if proc.returncode == 0:
            return None
    except Exception:
        return None
    repo_root = Path(repo_root)
    if (repo_root / "unlimited_skills" / "__init__.py").is_file():
        return repo_root.as_posix()
    return None


def _sh_posix(value: str | Path) -> str:
    return shlex.quote(str(value).replace("\\", "/"))


def render_sh_launcher(
    python_executable: str | Path,
    library_root: str | Path,
    *,
    project_root: str | Path | None = None,
    pythonpath_fallback: str | None = None,
) -> str:
    py = _sh_posix(python_executable)
    lib = _sh_posix(library_root)
    home = _sh_posix(Path(library_root).parent)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"# {launcher_stamp()}",
        "# Runs the INSTALLED unlimited_skills package via the recorded interpreter, so a",
        "# `pip install --upgrade` into that interpreter is picked up automatically.",
        "# (Older launchers prepended PYTHONPATH=<repo checkout>, which shadowed the",
        "# installed package and pinned the router to the version present at first install.)",
    ]
    if pythonpath_fallback:
        fb = _sh_posix(pythonpath_fallback)
        lines += [
            "# Source/editable checkout fallback: the package is not importable from this",
            "# interpreter's site-packages, so add the repo that actually contains it.",
            'if [[ -n "${PYTHONPATH:-}" ]]; then',
            f'  export PYTHONPATH={fb}:"$PYTHONPATH"',
            "else",
            f"  export PYTHONPATH={fb}",
            "fi",
        ]
    if project_root is not None:
        lines.append(f"export UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT={_sh_posix(project_root)}")
    lines.append(f"export UNLIMITED_SKILLS_HOME={home}")
    lines.append(f'exec {py} -m unlimited_skills --root {lib} "$@"')
    return "\n".join(lines) + "\n"


def render_ps_launcher(
    python_executable: str | Path,
    library_root: str | Path,
    *,
    project_root: str | Path | None = None,
    pythonpath_fallback: str | None = None,
) -> str:
    home = Path(library_root).parent
    lines = [
        "param(",
        "  [Parameter(ValueFromRemainingArguments = $true)]",
        "  [string[]]$Args",
        ")",
        "",
        '$ErrorActionPreference = "Stop"',
        f"# {launcher_stamp()}",
        "# Runs the INSTALLED unlimited_skills package via the recorded interpreter, so a",
        "# `pip install --upgrade` into that interpreter is picked up automatically.",
        "# (Older launchers prepended PYTHONPATH=<repo checkout>, which shadowed the",
        "# installed package and pinned the router to the version present at first install.)",
    ]
    if pythonpath_fallback:
        lines.append(
            f"$env:PYTHONPATH = {json.dumps(str(pythonpath_fallback))} + "
            "[System.IO.Path]::PathSeparator + $env:PYTHONPATH"
        )
    if project_root is not None:
        lines.append(f"$env:UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT = {json.dumps(str(project_root))}")
    lines.append(f"$env:UNLIMITED_SKILLS_HOME = {json.dumps(str(home))}")
    lines.append(
        f"& {json.dumps(str(python_executable))} -m unlimited_skills "
        f"--root {json.dumps(str(library_root))} @Args"
    )
    return "\n".join(lines) + "\n"


def write_launchers(
    *,
    sh_launcher: str | Path,
    ps_launcher: str | Path | None = None,
    python_executable: str | Path = sys.executable,
    library_root: str | Path,
    project_root: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> str | None:
    """Write the launcher script(s) from the shared templates.

    Returns the resolved source-tree PYTHONPATH fallback (or ``None`` for a clean
    launcher). ``ps_launcher=None`` writes only the shell launcher (OpenClaw).
    """
    fallback = resolve_launch_pythonpath(python_executable, repo_root)
    sh_path = Path(sh_launcher)
    sh_path.parent.mkdir(parents=True, exist_ok=True)
    sh_path.write_text(
        render_sh_launcher(
            python_executable,
            library_root,
            project_root=project_root,
            pythonpath_fallback=fallback,
        ),
        encoding="utf-8",
    )
    try:
        sh_path.chmod(0o755)
    except OSError:
        pass
    if ps_launcher is not None:
        ps_path = Path(ps_launcher)
        ps_path.parent.mkdir(parents=True, exist_ok=True)
        ps_path.write_text(
            render_ps_launcher(
                python_executable,
                library_root,
                project_root=project_root,
                pythonpath_fallback=fallback,
            ),
            encoding="utf-8",
        )
    return fallback
