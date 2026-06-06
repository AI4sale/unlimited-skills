from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_router_skills_require_skill_lookup_before_substantive_work() -> None:
    for path in [
        REPO_ROOT / "skills" / "skill-router" / "SKILL.md",
        REPO_ROOT / "skills" / "router-openclaw" / "SKILL.md",
        REPO_ROOT / "skills" / "router-hermes" / "SKILL.md",
    ]:
        text = path.read_text(encoding="utf-8")
        assert "before doing substantive work" in text.lower()
        assert "already active" in text.lower()
        assert "content writing" in text.lower()


def test_agents_patches_require_skill_lookup_before_substantive_work() -> None:
    for path in [
        REPO_ROOT / "scripts" / "install-codex.ps1",
        REPO_ROOT / "scripts" / "install-codex.sh",
        REPO_ROOT / "unlimited_skills" / "installers" / "openclaw.py",
    ]:
        text = path.read_text(encoding="utf-8")
        assert "Before doing substantive work" in text
        assert "relevant skill is already active" in text
