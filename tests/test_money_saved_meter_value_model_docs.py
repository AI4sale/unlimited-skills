from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
VALUE_MODEL = REPO_ROOT / "docs" / "product" / "v0.6.4" / "money-saved-meter-value-model.md"
JSON_CONTRACT = REPO_ROOT / "docs" / "product" / "v0.6.4" / "money-saved-meter-json-contract.v1.md"
BEFORE_AFTER_COMMAND = REPO_ROOT / "docs" / "product" / "v0.6.4" / "money-saved-meter-before-after-command.md"
LIMITATIONS = REPO_ROOT / "docs" / "reports" / "v0.6.4-money-saved-meter-known-limitations.md"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "money_saved_meter"
EMPTY_FIXTURE = FIXTURE_DIR / "value-model-empty.json"
EXAMPLE_FIXTURE = FIXTURE_DIR / "value-model-example.json"

ALLOWED_CLAIMS = [
    "Unlimited Skills estimates local context savings from routed skill/tool usage.",
    "Bytes may be measured when local artifacts expose sizes.",
    "Tokens and dollars are estimates.",
]

FORBIDDEN_CLAIMS = [
    "exact tokens saved",
    "exact money saved",
    "bill reduction guaranteed",
    "hosted telemetry-backed savings",
    "all skill-body savings measured exactly",
    "provider billing reconciliation",
]

REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "report_type",
    "generated_at",
    "mode",
    "model_scope",
    "window",
    "source_inputs",
    "exact_counts",
    "measured_bytes",
    "estimates",
    "disabled_by_default",
    "forbidden_fields",
    "claim_boundary",
    "privacy",
    "next_actions",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def serialized(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def scan_payload_values(value: Any) -> str:
    """Serialize user-visible example payload values, excluding boundary labels."""
    if isinstance(value, dict):
        return " ".join(
            scan_payload_values(item)
            for key, item in value.items()
            if key not in {"forbidden_fields", "claim_boundary", "privacy"}
        )
    if isinstance(value, list):
        return " ".join(scan_payload_values(item) for item in value)
    return str(value)


def test_value_model_docs_define_required_sections_and_boundaries() -> None:
    text = read(VALUE_MODEL)
    lower = text.lower()

    for heading in [
        "## purpose",
        "## source inputs",
        "## exact counted fields",
        "## measured byte fields",
        "## estimated fields",
        "## disabled-by-default fields",
        "## explicitly forbidden fields",
        "## claim boundary",
        "## per-100-call framing",
        "## non-goals",
    ]:
        assert heading in lower

    for phrase in [
        "router call count",
        "suggested skill count",
        "injected skill card count",
        "gateway/mcp call count",
        "measured bytes",
        "estimated tokens avoided",
        "estimated context bytes avoided",
        "estimated dollar value",
        "disabled unless the user provides local pricing config",
        "router inject v2 inventory snapshot",
        "local router metrics",
        "local event logs after privacy sanitizer",
        "mcp savings and gateway context-budget artifacts",
        "existing roi receipt",
        "100 calls",
        "local reporting window and cadence, not billing math",
        "empty-state output",
        "model/spec only",
    ]:
        assert phrase in lower

    for claim in ALLOWED_CLAIMS:
        assert claim in text
    for claim in FORBIDDEN_CLAIMS:
        assert claim in text


def test_json_contract_names_stable_fields_and_fixture_rules() -> None:
    text = read(JSON_CONTRACT)
    lower = text.lower()

    for key in REQUIRED_TOP_LEVEL_KEYS:
        assert key in text

    for phrase in [
        "money_saved_meter_value_model",
        "measurement_kind",
        "estimated_tokens_avoided",
        "estimated_context_bytes_avoided",
        "estimated_dollar_value",
        "dollar value remains unavailable unless local user configuration supplies a price",
        "the empty fixture must show zero counts",
        "the example fixture may show aggregate local counts and measured bytes",
        "must not contain raw prompts",
    ]:
        assert phrase in lower

    for claim in ALLOWED_CLAIMS + FORBIDDEN_CLAIMS:
        assert claim in text


def test_known_limitations_prevent_exact_or_hosted_overclaim() -> None:
    text = read(LIMITATIONS)
    lower = text.lower()

    for phrase in [
        "does not promise exact tokens",
        "does not promise exact money",
        "provider-bill reduction",
        "hosted telemetry-backed analytics",
        "per-100-call frame is a local reporting cadence",
        "us-064-002 adds `unlimited-skills money-saved meter`",
        "does not mutate local meter state",
        "does not add a state writer, push nudge, or daemon behavior",
    ]:
        assert phrase in lower

    for claim in ALLOWED_CLAIMS + FORBIDDEN_CLAIMS:
        assert claim in text


def test_before_after_command_doc_defines_reproducible_local_flow() -> None:
    text = read(BEFORE_AFTER_COMMAND)
    lower = text.lower()

    for phrase in [
        "us-064-002",
        "unlimited-skills money-saved meter",
        "unlimited-skills mcp savings --json > before-mcp-savings.json",
        "--mode before",
        "--mode after",
        "--compare before-meter.json",
        "report_type=money_saved_meter",
        "does not write `<root>/.learning/savings-meter.json`",
        "ambient nudge",
        "strips server names, schemas, commands, env, local paths",
        "no telemetry, upload, hosted calls",
    ]:
        assert phrase in lower


def test_fixtures_follow_stable_contract_and_measurement_kinds() -> None:
    for path in [EMPTY_FIXTURE, EXAMPLE_FIXTURE]:
        payload = load_fixture(path)
        assert set(payload) == REQUIRED_TOP_LEVEL_KEYS
        assert payload["schema_version"] == 1
        assert payload["report_type"] == "money_saved_meter_value_model"
        assert payload["model_scope"]["runtime_meter_implemented"] is False
        assert payload["model_scope"]["cli_command_implemented"] is False
        assert payload["model_scope"]["state_writer_implemented"] is False
        assert payload["window"]["target_call_count"] == 100
        assert payload["window"]["cadence_not_billing_math"] is True

        for key in [
            "router_call_count",
            "suggested_skill_count",
            "injected_skill_card_count",
            "gateway_mcp_call_count",
            "window_call_count",
        ]:
            assert payload["exact_counts"][key]["measurement_kind"] == "exact"

        for key in [
            "upstream_schema_bytes",
            "gateway_schema_bytes",
            "context_bytes_avoided",
            "skill_card_bytes_injected",
        ]:
            assert payload["measured_bytes"][key]["measurement_kind"] == "measured"
            assert "available" in payload["measured_bytes"][key]

        for key in [
            "estimated_tokens_avoided",
            "estimated_context_bytes_avoided",
            "estimated_dollar_value",
        ]:
            assert payload["estimates"][key]["measurement_kind"] == "estimated"
            assert "available" in payload["estimates"][key]

        assert payload["estimates"]["estimated_dollar_value"]["enabled"] is False
        assert payload["estimates"]["estimated_dollar_value"]["configured_locally"] is False
        assert payload["disabled_by_default"]["dollar_value"]["enabled"] is False
        assert payload["claim_boundary"]["allowed_claims"] == ALLOWED_CLAIMS
        assert payload["claim_boundary"]["forbidden_claims"] == FORBIDDEN_CLAIMS
        assert payload["privacy"] == {
            "local_only": True,
            "upload": False,
            "hosted_telemetry": False,
            "raw_prompts_included": False,
            "raw_task_text_included": False,
            "skill_bodies_included": False,
            "local_absolute_paths_included": False,
            "tokens_keys_secrets_included": False,
            "customer_names_included": False,
            "private_repo_paths_included": False,
            "raw_mcp_payloads_included": False,
        }


def test_empty_fixture_is_honest_empty_state() -> None:
    payload = load_fixture(EMPTY_FIXTURE)
    assert payload["mode"] == "empty"
    assert payload["window"]["window_call_count"] == 0
    assert payload["window"]["is_complete_window"] is False
    assert all(item["value"] == 0 for item in payload["exact_counts"].values())
    assert all(item["available"] is False for item in payload["measured_bytes"].values())
    assert all(item["available"] is False for item in payload["estimates"].values())
    assert all(item["status"] == "unavailable" for item in payload["source_inputs"].values())


def test_example_fixture_is_aggregate_only_and_privacy_safe() -> None:
    payload = load_fixture(EXAMPLE_FIXTURE)
    lower = scan_payload_values(payload).lower()

    assert payload["mode"] == "example"
    assert payload["window"]["window_call_count"] == 100
    assert payload["window"]["is_complete_window"] is True
    assert payload["exact_counts"]["router_call_count"]["value"] == 100
    assert payload["exact_counts"]["gateway_mcp_call_count"]["value"] == 64
    assert payload["measured_bytes"]["context_bytes_avoided"]["value"] == 89152
    assert payload["measured_bytes"]["context_bytes_avoided"]["available"] is True
    assert payload["estimates"]["estimated_tokens_avoided"]["value"] == 22288
    assert payload["estimates"]["estimated_tokens_avoided"]["method"] == "bytes_divided_by_4"

    forbidden_needles = [
        r"[A-Za-z]:\\\\",
        r"/home/",
        r"/users/",
        r"\\\\",
        "begin private key",
        "authorization",
        "bearer ",
        "api_key",
        "access_token",
        "refresh_token",
        "password",
        "raw_prompt",
        "prompt_text",
        "raw_task",
        "task_text",
        "skill_body",
        "customer_name",
        "private_repo_path",
        "raw_mcp_tool_input",
        "raw_mcp_tool_output",
        "mcp_schema",
    ]
    for needle in forbidden_needles:
        assert not re.search(needle, lower), needle
    assert "sk-" not in lower
    assert "secret" not in lower
