"""Tests for the R2 money foundation: price DB + pricing engine + model binding.

Covers O064-R2-01 (model_prices.json v1 + money_pricing) and O064-R2-00
(model_detect cascade: explicit -> runtime -> env -> assumption -> unknown), incl.
the owner corrections (model normally known; hidden runtime -> assumption profile).
"""

from __future__ import annotations

import pytest

from unlimited_skills import money_pricing as mp
from unlimited_skills import model_detect as md

_MODEL_ENV_VARS = (
    "UNLIMITED_SKILLS_MODEL", "UNLIMITED_SKILLS_RUNTIME_MODEL", "UNLIMITED_SKILLS_AGENT",
    "ANTHROPIC_MODEL", "CLAUDE_MODEL", "OPENAI_MODEL", "GOOGLE_MODEL", "DEEPSEEK_MODEL",
    "CODEX_HOME", "OPENCLAW_HOME", "OPENCLAW_WORKSPACE", "HERMES_HOME",
)


@pytest.fixture
def clean_env(monkeypatch):
    for var in _MODEL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


# --- price DB + pricing engine -------------------------------------------------

def test_price_db_is_v1_and_has_active_anthropic():
    db = mp.load_price_db()
    assert db["schema_version"] == mp.PRICE_DB_SCHEMA_VERSION
    opus = mp.resolve_model("anthropic:claude-opus-4.8", db)
    assert opus is not None and opus.status == "active"
    assert opus.base_input_per_1m == 5.0 and opus.cache_write_5m_per_1m == 6.25


def test_resolve_by_alias_and_bare_model():
    assert mp.resolve_model("opus-4.8").model == "claude-opus-4.8"
    assert mp.resolve_model("claude-opus-4-8").model == "claude-opus-4.8"
    assert mp.resolve_model("sonnet").model == "claude-sonnet-4.6"


def test_todo_model_not_selectable_unless_opted_in():
    assert mp.resolve_model("deepseek:deepseek-v4-pro") is None
    assert mp.resolve_model("deepseek:deepseek-v4-pro", allow_todo=True) is not None


def test_price_class_and_null_fallback_to_base():
    opus = mp.resolve_model("anthropic:claude-opus-4.8")
    assert mp.price_per_1m(opus, "cache_write_5m") == 6.25
    assert mp.price_per_1m(opus, "base_input") == 5.0
    gpt = mp.resolve_model("openai:gpt-5.5")
    # OpenAI has no 5m cache-write premium (null) -> falls back to base input.
    assert mp.price_per_1m(gpt, "cache_write_5m") == gpt.base_input_per_1m == 5.0


def test_money_formula_matches_hermes_example():
    opus = mp.resolve_model("anthropic:claude-opus-4.8")
    # Hermes worked example: 152,169 total tokens saved @ cache_write_5m ($6.25) = $0.95105625
    assert mp.money_for_tokens(152169, opus, "cache_write_5m") == pytest.approx(0.95105625)
    assert mp.money_for_tokens(85305, opus, "cache_write_5m") == pytest.approx(0.53315625)
    assert mp.money_for_tokens(66864, opus, "cache_write_5m") == pytest.approx(0.4179)


def test_pricing_basis_block():
    opus = mp.resolve_model("anthropic:claude-opus-4.8")
    basis = mp.pricing_basis(opus, "cache_write_5m")
    assert basis["currency"] == "USD" and basis["price_class"] == "cache_write_5m"
    assert basis["price_per_1m_input_tokens"] == 6.25
    assert basis["source_url"] and basis["source_date"] == "2026-06-17"


def test_assumption_models_are_priceable():
    # every agent_model_profiles model must be an active, priceable entry
    profiles = md.load_agent_profiles()["profiles"]
    for agent, prof in profiles.items():
        price = mp.resolve_model(f"{prof['provider']}:{prof['model']}")
        assert price is not None and price.base_input_per_1m is not None, agent


# --- model binding cascade -----------------------------------------------------

def test_explicit_cli_is_exact(clean_env):
    b = md.bind_model("anthropic:claude-opus-4.8", agent="claude-code")
    assert b.available and b.source == "explicit_cli" and b.confidence == "exact"
    assert b.provider == "anthropic" and b.model == "claude-opus-4.8"


def test_runtime_channel_is_exact(clean_env):
    clean_env.setenv("UNLIMITED_SKILLS_RUNTIME_MODEL", "anthropic:claude-opus-4.8")
    b = md.bind_model(agent="claude-code")
    assert b.source == "detected_runtime" and b.confidence == "exact" and b.available


def test_env_metadata_is_inferred(clean_env):
    clean_env.setenv("ANTHROPIC_MODEL", "claude-opus-4.8")
    b = md.bind_model(agent="claude-code")
    assert b.source == "env_metadata" and b.confidence == "inferred" and b.available


def test_hidden_runtime_falls_back_to_assumption(clean_env):
    # No explicit/runtime/env -> claude-code assumption profile = Sonnet-class.
    b = md.bind_model(agent="claude-code")
    assert b.source == "basic_assumption_due_hidden_runtime" and b.confidence == "assumed"
    assert b.model == "claude-sonnet-4.6" and b.available
    assert "hidden" in b.note.lower()


def test_codex_assumption_is_gpt55(clean_env):
    b = md.bind_model(agent="codex")
    assert b.available and b.provider == "openai" and b.model == "gpt-5.5"
    assert b.confidence == "assumed"


def test_hermes_assumption_is_conservative_gpt55_not_pro(clean_env):
    b = md.bind_model(agent="hermes")
    assert b.available and b.provider == "openai" and b.model == "gpt-5.5"
    assert b.confidence == "assumed"
    assert b.assumption_profile == "hermes"


def test_explicit_unresolvable_is_unavailable(clean_env):
    b = md.bind_model("anthropic:does-not-exist", agent="claude-code")
    assert not b.available and b.source == "explicit_cli" and b.confidence == "unknown"


def test_binding_error_supported_is_integration_bug(clean_env):
    b = md.bind_model(agent="claude-code", allow_assumption=False)
    assert not b.available
    err = md.binding_error(b)
    assert err["error"] == "model_binding_missing" and err["classification"] == "integration_bug"


def test_model_detect_report_shapes(clean_env):
    ok = md.model_detect_report(md.bind_model("anthropic:claude-opus-4.8", agent="claude-code"))
    assert ok["available"] is True and ok["pricing_available"] is True
    assert ok["model_binding"]["model"] == "claude-opus-4.8"
    bad = md.model_detect_report(md.bind_model(agent="claude-code", allow_assumption=False))
    assert bad["available"] is False and bad["diagnostic"]["classification"] == "integration_bug"
