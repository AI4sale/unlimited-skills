"""Tests for the shared launcher renderer (root-cause fix for the stale launcher).

Older launchers prepended ``PYTHONPATH=<repo checkout>`` to the process, which
shadowed the pip-installed package and pinned the router to the version present at
first install. The renderer here runs the INSTALLED package with no PYTHONPATH (so
``pip install --upgrade`` is picked up automatically), stamps every launcher with a
contract version so ``doctor`` / ``sync-inject`` can detect a stale one, and writes
a source-tree fallback only for a bare checkout the package is not importable from.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from unlimited_skills import __version__
from unlimited_skills.launchers import (
    LAUNCHER_CONTRACT_VERSION,
    launcher_is_stale,
    launcher_stamp,
    parse_launcher_contract,
    render_ps_launcher,
    render_sh_launcher,
    resolve_launch_pythonpath,
    write_launchers,
)

_LEGACY_SH = (
    "#!/usr/bin/env bash\nset -euo pipefail\n"
    'if [[ -n "${PYTHONPATH:-}" ]]; then\n'
    '  export PYTHONPATH=/old/repo:"$PYTHONPATH"\n'
    "else\n  export PYTHONPATH=/old/repo\nfi\n"
    'exec /old/py -m unlimited_skills --root /old/lib "$@"\n'
)


# --- stamp / parse -------------------------------------------------------------

def test_stamp_includes_contract_and_pkg_version():
    stamp = launcher_stamp()
    assert f"unlimited-skills-launcher: {LAUNCHER_CONTRACT_VERSION}" in stamp
    assert __version__ in stamp


def test_parse_legacy_is_zero_current_is_one_foreign_is_none():
    assert parse_launcher_contract(_LEGACY_SH) == 0  # pre-stamp = legacy shadowing form
    assert parse_launcher_contract(render_sh_launcher("/py", "/lib")) == LAUNCHER_CONTRACT_VERSION
    assert parse_launcher_contract("echo not ours\n") is None


def test_launcher_is_stale():
    assert launcher_is_stale(_LEGACY_SH) is True
    assert launcher_is_stale(render_sh_launcher("/py", "/lib")) is False
    assert launcher_is_stale("echo not ours") is False  # foreign text is not "stale"


# --- clean render (the fix) ----------------------------------------------------

def test_clean_sh_runs_installed_package_without_pythonpath():
    sh = render_sh_launcher("/venv/python.exe", "/lib", project_root="/proj")
    assert "export PYTHONPATH=" not in sh  # no shadowing assignment (comment may mention it)
    assert "-m unlimited_skills --root" in sh
    assert "UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT=" in sh  # claude sets the project root
    assert sh.startswith("#!/usr/bin/env bash")


def test_clean_sh_omits_project_root_when_none():
    sh = render_sh_launcher("/venv/python.exe", "/lib")
    assert "UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT=" not in sh


def test_clean_ps_runs_installed_package_without_pythonpath():
    ps = render_ps_launcher("C:/venv/python.exe", "C:/lib", project_root="C:/proj")
    assert "$env:PYTHONPATH =" not in ps
    assert "-m unlimited_skills " in ps
    assert "$env:UNLIMITED_SKILLS_CLAUDE_PROJECT_ROOT =" in ps


# --- fallback render (bare source checkout) ------------------------------------

def test_fallback_sh_sets_pythonpath_to_repo():
    sh = render_sh_launcher("/py", "/lib", pythonpath_fallback="/src/repo")
    assert "export PYTHONPATH=/src/repo" in sh
    assert "site-packages" in sh  # explanatory comment present


def test_fallback_ps_sets_pythonpath_to_repo():
    ps = render_ps_launcher("/py", "/lib", pythonpath_fallback="C:/src/repo")
    assert "$env:PYTHONPATH =" in ps and "C:/src/repo" in ps


# --- resolve probe -------------------------------------------------------------

def test_resolve_returns_none_when_no_repo_root():
    assert resolve_launch_pythonpath(sys.executable, None) is None


def test_resolve_returns_none_when_package_importable():
    # This interpreter can import unlimited_skills -> no fallback (clean launcher).
    assert resolve_launch_pythonpath(sys.executable, Path(__file__).resolve().parents[1]) is None


def _fake_failing_python(tmp_path: Path) -> Path:
    fake_py = tmp_path / ("py.bat" if os.name == "nt" else "py.sh")
    if os.name == "nt":
        fake_py.write_text("@echo off\r\nexit /b 1\r\n", encoding="utf-8")
    else:
        fake_py.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        fake_py.chmod(0o755)
    return fake_py


def test_resolve_falls_back_for_uninstalled_interpreter(tmp_path):
    # A repo that contains the package, probed with an interpreter that cannot
    # import it, yields the repo as the PYTHONPATH fallback.
    fake_repo = tmp_path / "repo"
    (fake_repo / "unlimited_skills").mkdir(parents=True)
    (fake_repo / "unlimited_skills" / "__init__.py").write_text("__version__='0'\n", encoding="utf-8")
    result = resolve_launch_pythonpath(str(_fake_failing_python(tmp_path)), fake_repo)
    assert result == fake_repo.as_posix()


def test_resolve_clean_when_repo_lacks_package(tmp_path):
    # Probe fails but repo_root does not actually contain the package -> still clean.
    empty_repo = tmp_path / "norepo"
    empty_repo.mkdir()
    assert resolve_launch_pythonpath(str(_fake_failing_python(tmp_path)), empty_repo) is None


# --- write_launchers + functional resolution -----------------------------------

def test_write_launchers_clean_and_executable(tmp_path):
    sh = tmp_path / "scripts" / "unlimited-skills.sh"
    ps = tmp_path / "scripts" / "unlimited-skills.ps1"
    fallback = write_launchers(
        sh_launcher=sh,
        ps_launcher=ps,
        python_executable=sys.executable,
        library_root=tmp_path / "lib",
        project_root=tmp_path / "proj",
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert fallback is None  # package importable -> clean launcher
    assert "export PYTHONPATH=" not in sh.read_text(encoding="utf-8")
    assert parse_launcher_contract(sh.read_text(encoding="utf-8")) == LAUNCHER_CONTRACT_VERSION
    assert ps.is_file()


def test_write_launchers_sh_only_when_no_ps(tmp_path):
    sh = tmp_path / "scripts" / "unlimited-skills.sh"
    write_launchers(
        sh_launcher=sh,
        ps_launcher=None,
        python_executable=sys.executable,
        library_root=tmp_path / "lib",
    )
    assert sh.is_file()
    assert not (tmp_path / "scripts" / "unlimited-skills.ps1").exists()


def test_written_launcher_resolves_installed_package_no_self_injected_pythonpath(tmp_path):
    """The written launcher runs the INSTALLED package and never re-introduces a
    self-injected source PYTHONPATH (the original stale-launcher bug).

    The launcher is run with a *stale* ``PYTHONPATH`` exported in the environment to
    prove the launcher does not extend it with a source checkout the way the legacy
    launcher did; the clean launcher leaves PYTHONPATH untouched and resolves the
    installed version from site-packages."""
    sh = tmp_path / "scripts" / "unlimited-skills.sh"
    fallback = write_launchers(
        sh_launcher=sh,
        python_executable=sys.executable,
        library_root=tmp_path / "lib",
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert fallback is None
    text = sh.read_text(encoding="utf-8")
    assert "export PYTHONPATH=" not in text  # the bug: launcher must not self-inject a source path

    neutral = tmp_path / "neutral"
    neutral.mkdir()
    from shutil import which

    # On Windows this may resolve to WSL's bash.exe. WSL cannot execute a raw
    # Windows temp path like C:\Users\..., so keep the functional shell-launcher
    # assertion to native POSIX hosts and use the module fallback on Windows.
    bash = None if os.name == "nt" else (which("bash") or which("/usr/bin/bash") or which("/bin/bash"))
    if bash is None:
        out = subprocess.run(
            [sys.executable, "-m", "unlimited_skills", "--version"],
            cwd=neutral, capture_output=True, text=True, timeout=60,
        )
        assert __version__ in out.stdout
        return
    out = subprocess.run(
        [bash, str(sh), "--version"],
        cwd=neutral, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    assert __version__ in out.stdout
