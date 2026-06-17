"""Tests for the R2 skills-savings foundation (O064-R2-02).

Covers the token-counting abstraction (exact-via-injected-counter + the
``bytes_divided_by_4`` fallback that is NOT release-acceptable + the privacy
disclosure) and the skills_savings block built on the router's own skill
inventory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from unlimited_skills import token_counting as tc
from unlimited_skills import skills_savings as ss


# --- token counting ------------------------------------------------------------

def test_bytes_fallback_is_an_accepted_estimate():
    out = tc.count_tokens("hello world", provider="anthropic")  # no API, no injected counter
    assert out.method == tc.FALLBACK_NAME
    # Estimate, not exact — but accepted for the release (Money Saved is an estimate).
    assert out.exact_for_model is False and out.release_acceptable is True
    assert out.tokens == len("hello world".encode("utf-8")) // 4
    assert out.used_provider_api is False
    desc = out.descriptor()
    assert desc == {
        "provider": "anthropic",
        "method": "bytes_divided_by_4",
        "exact_for_model": False,
        "release_acceptable": True,
    }


def test_injected_exact_counter_is_release_acceptable_for_claude():
    out = tc.count_tokens(
        "x" * 9999, provider="anthropic", model_api_id="claude-opus-4-8",
        exact_counter=lambda _t: 1234,
    )
    assert out.tokens == 1234
    assert out.method == tc.ANTHROPIC_COUNTER
    assert out.exact_for_model is True and out.release_acceptable is True
    assert out.used_provider_api is True


def test_non_anthropic_exact_counter_uses_provider_method():
    out = tc.count_tokens("abc", provider="openai", exact_counter=lambda _t: 7)
    assert out.tokens == 7 and out.method == tc.PROVIDER_COUNTER
    assert out.exact_for_model is True and out.release_acceptable is True


def test_prefer_bytes_forces_fallback_even_with_exact_counter():
    out = tc.count_tokens("abcd", provider="anthropic", exact_counter=lambda _t: 5, prefer="bytes")
    assert out.method == tc.FALLBACK_NAME and out.tokens == 1


def test_exact_counter_failure_falls_back():
    def boom(_t: str) -> int:
        raise RuntimeError("network down")

    out = tc.count_tokens("abcd", provider="anthropic", exact_counter=boom)
    assert out.method == tc.FALLBACK_NAME and out.exact_for_model is False


def test_token_count_privacy_disclosure():
    block = tc.token_count_privacy(provider_count_tokens_used=True)
    assert block["provider_count_tokens_used"] is True
    assert block["sent_material"] == "level1_skill_descriptions_and_mcp_tool_schemas"
    assert block["raw_prompts_sent"] is False and block["skill_bodies_sent"] is False
    assert block["requires_provider_api"] is True


# --- skills savings ------------------------------------------------------------

def _write_skill(root: Path, collection: str, name: str, description: str) -> None:
    skill_dir = root / collection / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nBody.\n",
        encoding="utf-8",
    )


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """A tiny 3-skill library (smaller than the router descriptor itself)."""
    _write_skill(tmp_path, "ecc", "git-commit-helper", "Use when writing conventional-commit messages.")
    _write_skill(tmp_path, "ecc", "pytest-recipes", "Use when adding or fixing pytest test suites.")
    _write_skill(tmp_path, "superpowers", "react-review", "Use when reviewing React component changes.")
    return tmp_path


@pytest.fixture
def big_library(tmp_path: Path) -> Path:
    """A realistically-sized library where collapsing to one descriptor wins."""
    for i in range(80):
        _write_skill(
            tmp_path, "ecc", f"skill-number-{i:03d}",
            f"Use when working on task family {i} with several distinct keywords and triggers.",
        )
    return tmp_path


def test_inventory_reads_every_visible_skill(library: Path):
    inv = ss.inventory_skill_descriptors(library)
    names = {name for name, _desc in inv}
    assert names == {"git-commit-helper", "pytest-recipes", "react-review"}


def test_skills_savings_exact_path(big_library: Path):
    # Deterministic exact counter: 1 token per whitespace-delimited word.
    block = ss.build_skills_savings(
        provider="anthropic", model_api_id="claude-opus-4-8", root=big_library,
        exact_counter=lambda text: len(text.split()),
    )
    assert block["baseline_skill_count"] == 80
    assert block["baseline_material"] == "level1_name_description_for_every_visible_skill"
    assert block["actual_material"] == "router_descriptor"
    assert block["baseline_tokens"] > block["actual_router_tokens"] > 0
    assert block["tokens_saved_per_event"] == block["baseline_tokens"] - block["actual_router_tokens"]
    assert block["event_count"] == 1
    assert block["total_tokens_saved"] == block["tokens_saved_per_event"]
    assert block["token_counter"]["exact_for_model"] is True
    assert block["token_counter"]["release_acceptable"] is True
    assert block["token_count_privacy"]["provider_count_tokens_used"] is True


def test_skills_savings_tiny_library_clamps_to_zero(library: Path):
    # Honest model: 3 tiny skills are not bigger than one router descriptor.
    block = ss.build_skills_savings(
        provider="anthropic", model_api_id="claude-opus-4-8", root=library,
        exact_counter=lambda text: len(text.split()),
    )
    assert block["baseline_skill_count"] == 3
    assert block["tokens_saved_per_event"] == max(0, block["baseline_tokens"] - block["actual_router_tokens"])


def test_skills_savings_event_count_scales_total(big_library: Path):
    block = ss.build_skills_savings(
        provider="anthropic", model_api_id="claude-opus-4-8", root=big_library,
        exact_counter=lambda text: len(text.split()), event_count=4,
    )
    assert block["event_count"] == 4
    assert block["tokens_saved_per_event"] > 0
    assert block["total_tokens_saved"] == block["tokens_saved_per_event"] * 4


def test_skills_savings_fallback_path_is_accepted_estimate(big_library: Path):
    block = ss.build_skills_savings(provider="anthropic", model_api_id="claude-opus-4-8", root=big_library)
    assert block["token_counter"]["method"] == "bytes_divided_by_4"
    assert block["token_counter"]["exact_for_model"] is False
    assert block["token_counter"]["release_acceptable"] is True
    assert block["token_count_privacy"]["provider_count_tokens_used"] is False
    assert block["tokens_saved_per_event"] >= 0


def test_skills_savings_empty_library_clamps_to_zero(tmp_path: Path):
    block = ss.build_skills_savings(
        provider="anthropic", root=tmp_path, exact_counter=lambda text: len(text.split()),
    )
    assert block["baseline_skill_count"] == 0
    assert block["tokens_saved_per_event"] == 0
    assert block["total_tokens_saved"] == 0
