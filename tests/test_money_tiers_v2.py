"""Tests for the money-bearing tier ladder v2 (O064-R2-06)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills import money_saved_meter_v2 as m2
from unlimited_skills import money_saved_tiers_v2 as t2

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


def _block(total, *, kind="skills"):
    common = {
        "baseline_tokens": total + 60, "tokens_saved_per_event": total, "event_count": 1,
        "total_tokens_saved": total,
        "token_counter": {"provider": "anthropic", "method": "anthropic_count_tokens",
                          "exact_for_model": True, "release_acceptable": True},
        "token_count_privacy": {"provider_count_tokens_used": True,
                                "sent_material": "level1_skill_descriptions_and_mcp_tool_schemas",
                                "raw_prompts_sent": False, "skill_bodies_sent": False, "requires_provider_api": True},
    }
    if kind == "skills":
        common.update({"baseline_skill_count": 372, "actual_router_tokens": 60})
    else:
        common.update({"baseline_server_count": 2, "measured_server_count": 2, "skipped_server_count": 0,
                       "actual_gateway_tokens": 60})
    return common


def _meter(model="anthropic:claude-opus-4.8", agent="claude-code", skills=80000, mcp=20000):
    return m2.build_meter_v2(
        model=model, agent=agent,
        skills_block=_block(skills, kind="skills"), mcp_block=_block(mcp, kind="mcp"),
    )


def test_registered_export_carries_money_and_basis(clean_env):
    export = t2.build_registered_export_v2(_meter(), alias="alice")
    assert export["schema_version"] == "money-saved-registered-export-v2"
    assert export["tier"] == "registered"
    assert export["basis_key"] and export["basis"]["model"] == "claude-opus-4.8"
    assert export["savings"]["total"]["estimated_money_saved_usd"] > 0
    assert export["member"]["skills_estimated_money_saved_usd"] > 0
    assert export["member"]["mcp_estimated_money_saved_usd"] > 0
    assert export["identity"] == {"install_id_included": False, "machine_id_included": False, "account_id_included": False}
    assert export["delivery"]["upload"] is False


def test_registered_export_roundtrip_file(clean_env, tmp_path: Path):
    export = t2.build_registered_export_v2(_meter(), alias="alice")
    path = tmp_path / "alice.json"
    path.write_text(json.dumps(export), encoding="utf-8")
    loaded = t2.load_registered_export_v2(path)
    assert loaded["basis_key"] == export["basis_key"]


def test_team_rollup_same_basis_sums(clean_env):
    a = t2.build_registered_export_v2(_meter(skills=80000, mcp=20000), alias="alice")
    b = t2.build_registered_export_v2(_meter(skills=40000, mcp=10000), alias="bob")
    rollup = t2.build_team_rollup_v2([a, b])
    assert rollup["group_count"] == 1
    assert rollup["single_compatible_basis"] is True
    group = rollup["groups"][0]
    assert group["member_count"] == 2
    assert group["total_tokens_saved"] == (80000 + 20000) + (40000 + 10000)
    assert group["total_estimated_money_saved_usd"] == pytest.approx(
        a["savings"]["total"]["estimated_money_saved_usd"] + b["savings"]["total"]["estimated_money_saved_usd"]
    )


def test_team_rollup_different_basis_not_summed(clean_env):
    opus = t2.build_registered_export_v2(_meter(model="anthropic:claude-opus-4.8"), alias="alice")
    sonnet = t2.build_registered_export_v2(_meter(model="anthropic:claude-sonnet-4.6"), alias="bob")
    rollup = t2.build_team_rollup_v2([opus, sonnet])
    assert rollup["group_count"] == 2
    assert rollup["single_compatible_basis"] is False


def test_team_rollup_dedups_and_rejects(clean_env):
    a = t2.build_registered_export_v2(_meter(), alias="alice")
    rollup = t2.build_team_rollup_v2([a, dict(a), {"schema_version": "garbage"}])
    assert rollup["groups"][0]["member_count"] == 1  # exact duplicate dropped
    assert any(r["reason"] == "wrong_schema_or_type" for r in rollup["rejected"])


def test_team_rollup_contains_assumptions(clean_env):
    assumed = t2.build_registered_export_v2(_meter(model=None, agent="codex"), alias="carol")
    rollup = t2.build_team_rollup_v2([assumed])
    assert rollup["contains_assumptions"] is True
    assert rollup["groups"][0]["contains_assumptions"] is True


def test_admin_export_csv_columns_and_compatible_flag(clean_env):
    opus = t2.build_registered_export_v2(_meter(model="anthropic:claude-opus-4.8", skills=90000, mcp=0), alias="alice")
    opus2 = t2.build_registered_export_v2(_meter(model="anthropic:claude-opus-4.8", skills=50000, mcp=0), alias="bob")
    sonnet = t2.build_registered_export_v2(_meter(model="anthropic:claude-sonnet-4.6", skills=10000, mcp=0), alias="carol")
    rollup = t2.build_team_rollup_v2([opus, opus2, sonnet])
    admin = t2.build_admin_export_v2(rollup, labels={"alice": {"team": "core", "project": "x"}})
    assert admin["schema_version"] == "money-saved-admin-export-v2"
    csv = t2.admin_export_v2_csv(admin)
    header = csv.splitlines()[0]
    assert header == ",".join(t2.ADMIN_CSV_COLUMNS)
    assert admin["row_count"] == 3
    # opus group is the larger (primary) basis -> compatible True; sonnet -> False.
    by_alias = {row["alias"]: row for row in admin["rows"]}
    assert by_alias["alice"]["money_basis_compatible"] is True
    assert by_alias["carol"]["money_basis_compatible"] is False
    assert by_alias["alice"]["team"] == "core"
