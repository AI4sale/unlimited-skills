"""Guard the documented install path until the package exists on PyPI.

`unlimited-skills` is not published on PyPI, so any instruction telling users
to run ``pip install unlimited-skills`` is a guaranteed 404 dead end. Until
the v0.5 PyPI publication gate (A3) lands, the working install path is the
Git install::

    pip install "git+https://github.com/AI4sale/unlimited-skills.git"

This test fails if the unpublished-package command reappears anywhere in the
repo without an ``A3-PYPI-FLIP`` marker on the same line. The marker is how
the A3 publication gate will mechanically find and flip every site back to
the plain PyPI command once the package is real.

Allowed without the marker: CHANGELOG.md (release history may quote the old
command), README-pypi.md (the future PyPI long description that is not uploaded
until publication), the Trusted Publishing runbook, and this test itself.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEAD_COMMAND = "pip install unlimited-skills"
MARKER = "A3-PYPI-FLIP"
GIT_INSTALL = 'pip install "git+https://github.com/AI4sale/unlimited-skills.git"'
ALLOWED_WITHOUT_MARKER = {
    "CHANGELOG.md",
    "README-pypi.md",
    "docs/releases/v0.5.0-alpha-blocked-status.md",
    "docs/releases/v0.5.0-alpha-pypi-publishing.md",
    "tests/test_install_path_docs.py",
}


def _tracked_files() -> list[Path]:
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", "ls-files", "-z"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available; cannot enumerate tracked files")
    names = proc.stdout.decode("utf-8", errors="replace").split("\0")
    return [REPO_ROOT / name for name in names if name.strip()]


def test_unpublished_pypi_install_requires_a3_flip_marker() -> None:
    offenders: list[str] = []
    for path in _tracked_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWED_WITHOUT_MARKER or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if DEAD_COMMAND in line and MARKER not in line:
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "`pip install unlimited-skills` points at an unpublished PyPI package "
        "(404 for every new user). Use the Git install "
        f"({GIT_INSTALL}) instead, or, if this is the A3 publication flip, "
        f"keep the {MARKER} marker on the same line:\n" + "\n".join(offenders)
    )


def test_marketplace_json_advertises_working_install() -> None:
    # .claude-plugin/marketplace.json is JSON, which cannot carry an
    # A3-PYPI-FLIP comment, so pin its install hint here instead.
    text = (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    assert "git+https://github.com/AI4sale/unlimited-skills.git" in text
    assert DEAD_COMMAND + ")" not in text and DEAD_COMMAND + '"' not in text


def test_blocked_status_documents_release_owner_actions() -> None:
    text = (REPO_ROOT / "docs/releases/v0.5.0-alpha-blocked-status.md").read_text(encoding="utf-8")
    for required in (
        "blocked_account_setup",
        "GitHub environment pypi",
        "PyPI Pending Trusted Publisher",
        "workflow filename = publish-pypi.yml",
        "PR #127",
        "PR #119 is background E19 trust-stack work",
        "No local PyPI token is required",
        "release/v0.5.0-alpha-pypi-flip-reapply",
    ):
        assert required in text
