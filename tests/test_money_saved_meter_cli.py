from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills.__main__ import main
from unlimited_skills.money_saved_meter import (
    assert_money_saved_meter_safe,
    build_100_call_value_report_fixture,
    build_money_saved_meter_report,
    format_money_saved_meter_markdown,
    money_saved_meter_json,
)
from scripts.verify_money_saved_100_call_report import verify_reproducible_report
from scripts.verify_money_saved_meter_100_call_fixture import verify_fixture_report


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def mcp_savings_payload() -> dict:
    return {
        "servers": [
            {"name": "private-local-server", "status": "ok", "tools_count": 12, "schema_bytes": 91000, "est_tokens": 22750},
            {"name": "skipped-server", "status": "skipped (not reachable)", "tools_count": 0, "schema_bytes": 0, "est_tokens": 0},
        ],
        "measured_servers": 1,
        "skipped_servers": 1,
        "total_bytes": 91000,
        "total_est_tokens": 22750,
        "gateway_bytes": 1268,
        "gateway_est_tokens": 317,
        "savings_bytes": 89732,
        "savings_pct": 98.6,
        "token_heuristic": "est_tokens = bytes / 4 (approximate)",
    }


def test_money_saved_meter_empty_state_is_honest(tmp_path: Path) -> None:
    report = build_money_saved_meter_report(tmp_path, generated_at="2026-06-15T00:00:00Z")

    assert report["report_type"] == "money_saved_meter"
    assert report["mode"] == "current"
    assert report["model_scope"]["cli_command_implemented"] is True
    assert report["model_scope"]["push_nudge_implemented"] is False
    assert report["source_inputs"]["mcp_savings_context_budget"]["status"] == "unavailable"
    assert report["measured_bytes"]["context_bytes_avoided"]["available"] is False
    assert report["estimates"]["estimated_tokens_avoided"]["available"] is False
    assert report["estimates"]["estimated_dollar_value"]["enabled"] is False
    assert report["privacy"]["upload"] is False
    assert report["privacy"]["hosted_telemetry"] is False


def test_money_saved_meter_strips_mcp_server_names_and_estimates_tokens(tmp_path: Path) -> None:
    report = build_money_saved_meter_report(
        tmp_path,
        mode="before",
        mcp_savings_report=mcp_savings_payload(),
        generated_at="2026-06-15T00:00:00Z",
    )
    serialized = json.dumps(report, sort_keys=True)

    assert report["source_inputs"]["mcp_savings_context_budget"]["status"] == "available"
    assert report["measured_bytes"]["upstream_schema_bytes"]["value"] == 91000
    assert report["measured_bytes"]["gateway_schema_bytes"]["value"] == 1268
    assert report["measured_bytes"]["context_bytes_avoided"]["value"] == 89732
    assert report["estimates"]["estimated_tokens_avoided"]["value"] == 22433
    assert report["estimates"]["estimated_tokens_avoided"]["method"] == "bytes_divided_by_4"
    assert report["privacy"]["server_names_included"] is False
    assert "private-local-server" not in serialized
    assert "skipped-server" not in serialized


def test_money_saved_meter_reads_gateway_audit_counts(tmp_path: Path) -> None:
    audit_log = tmp_path / "audit.jsonl"
    write_jsonl(
        audit_log,
        [
            {"ts": 1.0, "tool": "tools_search", "upstream": "alpha", "ok": True, "duration_ms": 3.0},
            {"ts": 2.0, "tool": "tools_schema", "upstream": "alpha", "ok": False, "duration_ms": 4.0},
        ],
    )

    report = build_money_saved_meter_report(
        tmp_path,
        mcp_savings_report=mcp_savings_payload(),
        audit_log=audit_log,
        target_call_count=2,
        generated_at="2026-06-15T00:00:00Z",
    )

    assert report["exact_counts"]["gateway_mcp_call_count"]["value"] == 2
    assert report["window"]["window_call_count"] == 2
    assert report["window"]["is_complete_window"] is True
    assert report["source_inputs"]["gateway_audit_summary"]["status"] == "available"
    assert report["privacy"]["local_absolute_paths_included"] is False


def test_money_saved_meter_compares_previous_report(tmp_path: Path) -> None:
    before = build_money_saved_meter_report(
        tmp_path,
        mode="before",
        mcp_savings_report=mcp_savings_payload(),
        generated_at="2026-06-15T00:00:00Z",
    )
    after_payload = {**mcp_savings_payload(), "savings_bytes": 90000}
    after = build_money_saved_meter_report(
        tmp_path,
        mode="after",
        mcp_savings_report=after_payload,
        compare_report=before,
        generated_at="2026-06-15T00:00:01Z",
    )

    assert after["comparison"]["baseline_mode"] == "before"
    assert after["comparison"]["current_mode"] == "after"
    assert after["comparison"]["delta_context_bytes_avoided"] == 268


def test_money_saved_meter_cli_outputs_json_and_writes_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mcp_path = tmp_path / "mcp-savings.json"
    out_path = tmp_path / "meter.json"
    mcp_path.write_text(json.dumps(mcp_savings_payload()), encoding="utf-8")

    code = main(
        [
            "--root",
            str(tmp_path),
            "money-saved",
            "meter",
            "--json",
            "--mode",
            "before",
            "--mcp-savings-json",
            str(mcp_path),
            "--out",
            str(out_path),
            "--json-status",
        ]
    )

    assert code == 0
    status = json.loads(capsys.readouterr().out)
    assert status == {"schema_version": 1, "written": True, "format": "json"}
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "money_saved_meter"
    assert payload["mode"] == "before"


def test_money_saved_meter_markdown_is_local_only(tmp_path: Path) -> None:
    report = build_money_saved_meter_report(tmp_path, mcp_savings_report=mcp_savings_payload())
    text = format_money_saved_meter_markdown(report)

    assert "Local-only: yes" in text
    assert "Telemetry: no" in text
    assert "Dollar estimate: unavailable by default" in text


def test_money_saved_meter_safety_gate_rejects_planted_needles() -> None:
    report = build_money_saved_meter_report(Path("."), mcp_savings_report=mcp_savings_payload())
    report["unsafe"] = "C:\\Users\\tedja\\secret.txt"

    with pytest.raises(RuntimeError):
        assert_money_saved_meter_safe(report)


def test_money_saved_meter_json_round_trip_is_safe(tmp_path: Path) -> None:
    report = build_money_saved_meter_report(tmp_path, mcp_savings_report=mcp_savings_payload())
    payload = json.loads(money_saved_meter_json(report))

    assert payload["privacy"]["raw_prompts_included"] is False
    assert payload["privacy"]["raw_mcp_payloads_included"] is False


def test_money_saved_meter_100_call_fixture_is_complete_and_bounded() -> None:
    report = build_100_call_value_report_fixture()
    result = verify_fixture_report(report)
    serialized = json.dumps(report, sort_keys=True)

    assert result["ok"] is True
    assert report["window"]["target_call_count"] == 100
    assert report["window"]["window_call_count"] == 100
    assert report["window"]["cadence_not_billing_math"] is True
    assert report["exact_counts"]["window_call_count"]["measurement_kind"] == "exact"
    assert report["measured_bytes"]["context_bytes_avoided"]["measurement_kind"] == "measured"
    assert report["estimates"]["estimated_tokens_avoided"]["method"] == "bytes_divided_by_4"
    assert report["estimates"]["estimated_dollar_value"]["enabled"] is False
    assert "redacted-fixture-upstream" not in serialized
    assert "exact tokens saved" in report["claim_boundary"]["forbidden_claims"]


def test_money_saved_meter_cli_emits_100_call_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_path = tmp_path / "100-call-value-report.json"

    code = main(
        [
            "--root",
            str(tmp_path),
            "money-saved",
            "meter",
            "--json",
            "--fixture-100-call",
            "--out",
            str(out_path),
            "--json-status",
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"schema_version": 1, "written": True, "format": "json"}
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert verify_fixture_report(payload)["window_call_count"] == 100


def test_money_saved_meter_partial_window_remains_honest(tmp_path: Path) -> None:
    report = build_money_saved_meter_report(
        tmp_path,
        mcp_savings_report=mcp_savings_payload(),
        gateway_call_count=42,
        target_call_count=100,
        generated_at="2026-06-15T00:00:00Z",
    )

    assert report["window"]["target_call_count"] == 100
    assert report["window"]["window_call_count"] == 42
    assert report["window"]["is_complete_window"] is False
    assert "never extrapolate exact tokens" in report["window"]["partial_window_policy"]
    assert report["estimates"]["estimated_tokens_avoided"]["method"] == "bytes_divided_by_4"
    assert report["estimates"]["estimated_dollar_value"]["enabled"] is False


def test_money_saved_meter_100_call_fixture_top_level_fields_are_stable() -> None:
    report = build_100_call_value_report_fixture()

    assert list(report.keys()) == [
        "schema_version",
        "report_type",
        "generated_at",
        "mode",
        "measurement_surface",
        "unlimited_skills_version",
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
        "notice",
        "fixture",
    ]


def test_money_saved_meter_100_call_markdown_does_not_overclaim() -> None:
    text = format_money_saved_meter_markdown(build_100_call_value_report_fixture())

    assert "Gateway calls in window: 100 / 100" in text
    assert "Surface: 100-call value report fixture" in text
    assert "100-call window is cadence/reporting, not billing math: True" in text
    assert "Estimated tokens avoided: 22288" in text
    assert "Dollar estimate: unavailable by default" in text
    assert "exact tokens saved" not in text.lower()
    assert "exact money saved" not in text.lower()
    assert "bill reduction" not in text.lower()


def test_money_saved_meter_100_call_report_verifier_reproduces_fixture() -> None:
    result = verify_reproducible_report()

    assert result["ok"] is True
    assert result["target_call_count"] == 100
    assert result["window_call_count"] == 100


def test_money_saved_meter_100_call_verifier_catches_drift(tmp_path: Path) -> None:
    fixture = build_100_call_value_report_fixture()
    fixture["window"]["window_call_count"] = 99
    expected = tmp_path / "drifted.json"
    expected.write_text(json.dumps(fixture, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(SystemExit):
        verify_reproducible_report(expected_json_path=expected)
