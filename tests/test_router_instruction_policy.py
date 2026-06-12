from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

# The A0 router contract: one cheap `suggest` probe, an explicit trigger
# taxonomy, an act-on-result rule, and a credible skip rule. Every surface
# that emits or installs the router instructions must carry all of it.


def test_router_skills_carry_the_suggest_contract() -> None:
    for path in [
        REPO_ROOT / "skills" / "skill-router" / "SKILL.md",
        REPO_ROOT / "skills" / "router-claude-code" / "SKILL.md",
        REPO_ROOT / "skills" / "router-openclaw" / "SKILL.md",
        REPO_ROOT / "skills" / "router-hermes" / "SKILL.md",
        REPO_ROOT / "plugin" / "skills" / "unlimited-skills" / "SKILL.md",
    ]:
        text = path.read_text(encoding="utf-8")
        assert 'suggest "<task in 3-8 keywords>"' in text, path
        assert "TRIGGERS (any one suffices):" in text, path
        assert "SKIP only when a relevant skill is already active" in text, path
        assert "do not search again with synonyms" in text, path


def test_installed_router_blocks_carry_the_suggest_contract() -> None:
    for path in [
        REPO_ROOT / "scripts" / "install-codex.ps1",
        REPO_ROOT / "scripts" / "install-codex.sh",
        REPO_ROOT / "unlimited_skills" / "installers" / "claude_code.py",
        REPO_ROOT / "unlimited_skills" / "installers" / "openclaw.py",
    ]:
        text = path.read_text(encoding="utf-8")
        assert 'suggest "<task in 3-8 keywords>"' in text.replace("\\\"", '"'), path
        assert "TRIGGERS (any one suffices):" in text, path
        assert "SKIP only when a relevant skill is already active" in text, path
        assert "RUN this single command BEFORE starting any task" in text, path


def test_session_start_hook_carries_the_suggest_contract() -> None:
    text = (REPO_ROOT / "plugin" / "hooks" / "session_start.py").read_text(encoding="utf-8")
    assert 'suggest "<task in 3-8 keywords>"' in text
    assert "TRIGGERS (any one suffices)" in text
    assert "SKIP only when a relevant skill is already active" in text
