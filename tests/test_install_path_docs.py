"""Guard the documented install path after the v0.5 PyPI flip."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPI_INSTALL = "pip install unlimited-skills"
VERSIONED_PYPI_INSTALL = "pip install unlimited-skills==0.5.3"
GIT_INSTALL = 'pip install "git+https://github.com/AI4sale/unlimited-skills.git"'
MARKER = "A3-PYPI-FLIP"


def read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_primary_install_docs_use_pypi_command() -> None:
    for rel in (
        "README.md",
        "README-pypi.md",
        "docs/quickstart.md",
        "docs/adoption/marketplace-listing-copy.md",
        ".claude-plugin/marketplace.json",
    ):
        text = read(rel)
        assert PYPI_INSTALL in text, f"{rel} must show the PyPI install command"
        assert GIT_INSTALL not in text, f"{rel} must not send new users to the pre-PyPI Git install"


def test_pypi_flip_markers_do_not_ship_in_publishable_surfaces() -> None:
    for rel in (
        "README.md",
        "README-pypi.md",
        "docs/quickstart.md",
        ".claude-plugin/marketplace.json",
        "unlimited_skills/commands/library.py",
        "unlimited_skills/hub.py",
    ):
        assert MARKER not in read(rel), f"{rel} still contains the internal A3 flip marker"


def test_final_publication_docs_pin_versioned_install_smoke() -> None:
    text = read("docs/releases/v0.5.3-alpha-checklist.md")
    assert VERSIONED_PYPI_INSTALL in text
