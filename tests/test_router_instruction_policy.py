from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

RI2_SUGGEST = 'suggest "<3-8 keyword phase summary>" --json --card --limit 1'

# The RI2 router contract: one cheap phase-scoped `suggest` probe, an explicit
# trigger taxonomy, an act-on-result rule, phase freshness, and a credible skip
# rule. Every surface that emits or installs the router instructions must carry it.


def test_router_skills_carry_the_suggest_contract() -> None:
    for path in [
        REPO_ROOT / "skills" / "skill-router" / "SKILL.md",
        REPO_ROOT / "skills" / "router-claude-code" / "SKILL.md",
        REPO_ROOT / "skills" / "router-openclaw" / "SKILL.md",
        REPO_ROOT / "skills" / "router-hermes" / "SKILL.md",
        REPO_ROOT / "plugin" / "skills" / "unlimited-skills" / "SKILL.md",
    ]:
        text = path.read_text(encoding="utf-8")
        assert RI2_SUGGEST in text, path
        assert "TRIGGERS (any one suffices):" in text, path
        assert "SKIP only when a relevant skill is already active" in text, path
        assert "do not search" in text and "synonyms" in text, path
        assert "current phase" in text, path
        assert "Phase freshness" in text or "Phase Freshness" in text, path
        assert "Tier behavior" in text, path


def test_router_skills_carry_multilingual_vector_guidance() -> None:
    for path in [
        REPO_ROOT / "skills" / "skill-router" / "SKILL.md",
        REPO_ROOT / "skills" / "router-openclaw" / "SKILL.md",
        REPO_ROOT / "skills" / "router-hermes" / "SKILL.md",
        REPO_ROOT / "plugin" / "skills" / "unlimited-skills" / "SKILL.md",
    ]:
        text = path.read_text(encoding="utf-8")
        assert "MULTILINGUAL" in text, path
        assert "other than English" in text, path
        assert "vector-reindex" in text, path
        assert "unlimited-skills serve" in text, path
        assert "non-English prompts at zero" in text, path


def test_public_claude_router_is_safe_for_awesome_skills_install() -> None:
    text = (REPO_ROOT / "skills" / "router-claude-code" / "SKILL.md").read_text(encoding="utf-8")
    assert "{{" not in text
    assert "}}" not in text
    assert 'pip install --upgrade "unlimited-skills>=0.6.1"' in text
    assert "unlimited-skills quickstart" in text
    assert "npx skills add AI4sale/unlimited-skills" in text


def test_installed_router_blocks_carry_the_suggest_contract() -> None:
    for path in [
        REPO_ROOT / "scripts" / "install-codex.ps1",
        REPO_ROOT / "scripts" / "install-codex.sh",
        REPO_ROOT / "unlimited_skills" / "installers" / "claude_code.py",
        REPO_ROOT / "unlimited_skills" / "installers" / "openclaw.py",
    ]:
        text = path.read_text(encoding="utf-8")
        assert RI2_SUGGEST in text.replace("\\\"", '"'), path
        assert "TRIGGERS (any one suffices):" in text, path
        assert "SKIP only when a relevant skill is already active" in text, path
        assert "RUN this single command BEFORE starting every substantive work phase" in text, path
        assert "PHASE FRESHNESS" in text or "Phase freshness" in text, path
        assert "for that same phase" in text, path


def test_session_start_hook_carries_the_suggest_contract() -> None:
    text = (REPO_ROOT / "plugin" / "hooks" / "session_start.py").read_text(encoding="utf-8")
    assert RI2_SUGGEST in text
    assert "TRIGGERS (any one suffices)" in text
    assert "SKIP only when a relevant skill is already active" in text
    assert "current phase" in text
    assert "ANTI-SPAM" in text


def test_claude_code_block_instructs_multilingual_install() -> None:
    # The installed CLAUDE.md block must tell the LLM: if it has ever spoken a
    # non-English language with this user, default to the vector + daemon install
    # (lexical-only scores non-English prompts at zero).
    text = (REPO_ROOT / "unlimited_skills" / "installers" / "claude_code.py").read_text(encoding="utf-8")
    assert "MULTILINGUAL INSTALL" in text
    assert "other than English" in text
    assert "vector-reindex" in text
    assert "serve" in text
