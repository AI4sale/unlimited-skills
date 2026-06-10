from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills.recommendation_policy import (
    DENIAL_OUTCOMES,
    OUTCOMES,
    PRIVATE_DATA_KEYS,
    RecommendationPolicyError,
    _assert_public_safe,
    decision_for_case,
    decision_table,
    refusal_code_contract,
    summarize_decision_counts,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "recommendations"
SCHEMAS = ROOT / "schemas"

REQUIRED_CASES = {
    "local_mit_skill",
    "hosted_official_catalog_item",
    "community_catalog_item",
    "private_team_pack_item",
    "deprecated",
    "retired",
    "blocked",
    "low_score",
    "fixed_pending_eval",
    "policy_denied",
    "entitlement_denied",
    "registration_required",
    "wrong_channel",
    "wrong_agent",
    "unsigned_metadata",
    "stale_installed_version",
}


def test_decision_table_covers_required_cases_and_outcomes() -> None:
    payload = decision_table()
    cases = {item["case"] for item in payload["decisions"]}
    outcomes = {item["outcome"] for item in payload["decisions"]}

    assert REQUIRED_CASES.issubset(cases)
    assert set(OUTCOMES) == set(payload["outcomes"])
    assert set(OUTCOMES).issubset(outcomes)
    assert summarize_decision_counts()["allow_update_preview"] >= 2


def test_denials_include_refusal_reason_next_command_owner_action_and_fallback() -> None:
    payload = decision_table()
    refusal_contract = refusal_code_contract()
    refusal_by_code = {item["code"]: item for item in refusal_contract["refusal_codes"]}

    for decision in payload["decisions"]:
        if decision["outcome"] not in DENIAL_OUTCOMES:
            assert "refusal_code" not in decision
            continue

        assert decision["refusal_code"] in refusal_by_code
        assert refusal_by_code[decision["refusal_code"]]["outcome"] == decision["outcome"]
        for field in ("reason", "next_command", "owner", "action", "fallback"):
            assert decision[field].strip()


def test_recommendations_are_fixture_only_and_never_apply_changes() -> None:
    payloads = [decision_table(), refusal_code_contract()]

    for payload in payloads:
        assert payload["fixture_only"] is True
        assert payload["preview_only"] is True
        assert payload["automatic_install"] is False
        assert payload["automatic_update"] is False
        assert payload["automatic_remove"] is False
        assert payload["automatic_telemetry"] is False
        assert payload["hosted_query_forwarding"] is False
        assert payload["skill_rewriting"] is False
        assert payload["full_catalog_distribution"] is False

    for decision in decision_table()["decisions"]:
        assert decision["will_install"] is False
        assert decision["will_update"] is False
        assert decision["will_remove"] is False
        assert decision["automatic_install"] is False
        assert decision["automatic_update"] is False
        assert decision["automatic_remove"] is False


def test_public_payloads_emit_no_private_data_fields_or_sensitive_text() -> None:
    payloads = [decision_table(), refusal_code_contract()]
    for path in [*EXAMPLES.glob("*.json"), SCHEMAS / "recommendation-decision.schema.json", SCHEMAS / "recommendation-refusal.schema.json"]:
        payloads.append(json.loads(path.read_text(encoding="utf-8")))

    for payload in payloads:
        _assert_public_safe(payload)
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for forbidden in PRIVATE_DATA_KEYS:
            assert f'"{forbidden}"' not in serialized
        assert "skill.md" not in serialized
        assert "```" not in serialized
        assert "authorization: bearer" not in serialized


def test_schema_and_example_files_are_valid_json_and_keep_contract_flags() -> None:
    for path in [
        SCHEMAS / "recommendation-decision.schema.json",
        SCHEMAS / "recommendation-refusal.schema.json",
        *EXAMPLES.glob("*.json"),
    ]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload

    decision_example = json.loads((EXAMPLES / "decision-table.example.json").read_text(encoding="utf-8"))
    refusal_example = json.loads((EXAMPLES / "refusal-codes.example.json").read_text(encoding="utf-8"))

    assert decision_example["manifest_type"] == "recommendation-decision"
    assert refusal_example["manifest_type"] == "recommendation-refusal"
    assert decision_example == decision_table()
    assert refusal_example == refusal_code_contract()
    for payload in (decision_example, refusal_example):
        assert payload["fixture_only"] is True
        assert payload["automatic_install"] is False
        assert payload["automatic_update"] is False
        assert payload["automatic_remove"] is False
        assert payload["hosted_query_forwarding"] is False


def test_case_lookup_is_public_safe_and_rejects_unknown_case() -> None:
    decision = decision_for_case("stale_installed_version")
    assert decision.outcome == "allow_update_preview"
    assert decision.to_json()["will_update"] is False

    with pytest.raises(RecommendationPolicyError, match="Unknown recommendation fixture case"):
        decision_for_case("missing")
