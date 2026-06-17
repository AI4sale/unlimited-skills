"""Tests for the Free Money Saved meter v2 (O064-R2-05)."""

from __future__ import annotations

import pytest

from unlimited_skills import money_saved_meter_v2 as m2

_MODEL_ENV = (
    "UNLIMITED_SKILLS_MODEL", "UNLIMITED_SKILLS_RUNTIME_MODEL", "UNLIMITED_SKILLS_AGENT",
    "ANTHROPIC_MODEL", "CLAUDE_MODEL", "OPENAI_MODEL", "GOOGLE_MODEL", "DEEPSEEK_MODEL",
    "CODEX_HOME", "OPENCLAW_HOME", "OPENCLAW_WORKSPACE", "HERMES_HOME",
)


@pytest.fixture
def clean_env(monkeypatch):
    for var in _MODEL_ENV:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _skills_block(total):
    return {
        "baseline_skill_count": 372, "baseline_material": "level1_name_description_for_every_visible_skill",
        "baseline_tokens": total + 60, "actual_material": "router_descriptor", "actual_router_tokens": 60,
        "tokens_saved_per_event": total, "event_count": 1, "total_tokens_saved": total,
        "token_counter": {"provider": "anthropic", "method": "anthropic_count_tokens",
                          "exact_for_model": True, "release_acceptable": True},
        "token_count_privacy": {"provider_count_tokens_used": True,
                                "sent_material": "level1_skill_descriptions_and_mcp_tool_schemas",
                                "raw_prompts_sent": False, "skill_bodies_sent": False, "requires_provider_api": True},
    }


def _mcp_block(total):
    return {
        "baseline_server_count": 2, "measured_server_count": 2, "skipped_server_count": 0,
        "baseline_material": "full_upstream_tools_list_for_all_configured_servers",
        "baseline_tokens": total + 50, "actual_material": "gateway_meta_tools_list",
        "actual_gateway_tokens": 50, "tokens_saved_per_event": total, "event_count": 1,
        "total_tokens_saved": total,
        "token_counter": {"provider": "anthropic", "method": "anthropic_count_tokens",
                          "exact_for_model": True, "release_acceptable": True},
        "token_count_privacy": {"provider_count_tokens_used": True,
                                "sent_material": "level1_skill_descriptions_and_mcp_tool_schemas",
                                "raw_prompts_sent": False, "skill_bodies_sent": False, "requires_provider_api": True},
    }


def test_meter_v2_hermes_worked_example(clean_env):
    # 85,305 (skills) + 66,864 (mcp) = 152,169 tokens @ opus cache_write_5m ($6.25)
    report = m2.build_meter_v2(
        model="anthropic:claude-opus-4.8", agent="claude-code",
        skills_block=_skills_block(85305), mcp_block=_mcp_block(66864),
        events={"event_count": 3, "event_types": {"session_start": 1, "compaction": 2}},
    )
    assert report["schema_version"] == "money-saved-meter-v2"
    assert report["available"] is True
    assert report["model_binding"]["model"] == "claude-opus-4.8"
    assert report["model_binding"]["source"] == "explicit_cli"
    assert report["pricing"]["price_class"] == "cache_write_5m"
    assert report["pricing"]["price_per_1m_input_tokens"] == 6.25
    assert report["pricing"]["source_url"] and report["pricing"]["source_date"] == "2026-06-17"
    assert report["savings"]["skills"]["estimated_money_saved_usd"] == pytest.approx(0.53315625)
    assert report["savings"]["mcp"]["estimated_money_saved_usd"] == pytest.approx(0.4179)
    assert report["savings"]["total"]["tokens_saved"] == 152169
    assert report["savings"]["total"]["estimated_money_saved_usd"] == pytest.approx(0.95105625)
    assert report["claim_boundary"]["money_kind"] == "api_equivalent_estimate"
    assert report["claim_boundary"]["not_provider_bill_reconciliation"] is True
    assert report["events"]["event_count"] == 3
    assert report["token_count_privacy"]["provider_count_tokens_used"] is True


def test_meter_v2_assumption_path_still_produces_money(clean_env):
    # No model + codex agent -> gpt-5.5 assumption. OpenAI has no cache-write
    # premium, so cache_write_5m falls back to base_input ($5.0).
    report = m2.build_meter_v2(
        agent="codex", skills_block=_skills_block(100000), mcp_block=_mcp_block(0),
    )
    assert report["available"] is True
    assert report["model_binding"]["confidence"] == "assumed"
    assert report["model_binding"]["provider"] == "openai" and report["model_binding"]["model"] == "gpt-5.5"
    assert report["pricing"]["price_per_1m_input_tokens"] == 5.0  # null cache class -> base
    assert report["savings"]["total"]["estimated_money_saved_usd"] == pytest.approx(0.5)


def test_meter_v2_include_toggles(clean_env):
    report = m2.build_meter_v2(
        model="anthropic:claude-opus-4.8", include_mcp=False,
        skills_block=_skills_block(1000),
    )
    assert "skills" in report["savings"] and "mcp" not in report["savings"]
    assert report["savings"]["total"]["tokens_saved"] == 1000


def test_meter_v2_explicit_unresolvable_model_is_diagnostic(clean_env):
    report = m2.build_meter_v2(model="anthropic:does-not-exist", agent="claude-code")
    assert report["available"] is False
    assert report["diagnostic"]["error"] == "model_binding_missing"


def test_anthropic_api_model_id_is_dashed():
    from unlimited_skills.money_pricing import resolve_model
    opus = resolve_model("anthropic:claude-opus-4.8")
    assert m2.anthropic_api_model_id(opus) == "claude-opus-4-8"
