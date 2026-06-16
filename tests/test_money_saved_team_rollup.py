"""Tests for the Team-tier Money Saved rollup (O064-MSM-TEAM-IMPL).

Proves the rollup aggregates locally-gathered Registered Money Saved exports,
keeps exact counts / measured bytes / token estimates honestly separated,
detects duplicates, and rejects incompatible / unsafe inputs. Fail-closed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from unlimited_skills.money_saved_meter import (
    build_registered_export,
    registered_export_json,
)
from unlimited_skills.money_saved_tiers import (
    MSM_TEAM_ROLLUP_SCHEMA_VERSION,
    IncompatibleExportError,
    build_money_saved_team_rollup,
    money_saved_team_rollup_json,
)
from unlimited_skills.commands.money_saved import cmd_money_saved_team_rollup

FIXED_TS = "2026-01-01T00:00:00Z"


def _registered_export_file(tmp_path: Path, name: str, *, calls: int) -> Path:
    """Write a Registered Money Saved export with a deterministic 100-call fixture body."""
    from unlimited_skills.money_saved_meter import fixture_100_call_mcp_savings_payload

    export = build_registered_export(
        tmp_path,
        mode="fixture_100_call",
        mcp_savings_report=fixture_100_call_mcp_savings_payload(),
        generated_at=FIXED_TS,
    )
    # Force a deterministic gateway window count for aggregation testing.
    export["body"]["window"]["window_call_count"] = calls
    export["body"]["window"]["is_complete_window"] = calls >= export["body"]["window"]["target_call_count"]
    path = tmp_path / name
    path.write_text(registered_export_json(export), encoding="utf-8")
    return path


def test_single_export_rollup(tmp_path):
    exp = _registered_export_file(tmp_path, "alice.json", calls=100)
    rollup = build_money_saved_team_rollup([exp], generated_at=FIXED_TS)
    assert rollup["schema_version"] == MSM_TEAM_ROLLUP_SCHEMA_VERSION
    assert rollup["report_type"] == "money_saved_team_rollup"
    assert rollup["member_count"] == 1
    assert rollup["exact_counts"]["team_window_call_count"] == 100
    assert rollup["members"][0]["alias"] == "alice"


def test_multiple_exports_aggregate(tmp_path):
    a = _registered_export_file(tmp_path, "alice.json", calls=100)
    b = _registered_export_file(tmp_path, "bob.json", calls=40)
    rollup = build_money_saved_team_rollup([a, b], aliases=["alice", "bob"], generated_at=FIXED_TS)
    assert rollup["member_count"] == 2
    assert rollup["exact_counts"]["team_window_call_count"] == 140
    # Both members measured the same fixture bytes -> measured aggregate sums both.
    assert rollup["measured_bytes"]["members_with_measured_bytes"] == 2
    assert rollup["estimates"]["measurement_kind"] == "estimated"


def test_duplicate_input_deduped(tmp_path):
    a = _registered_export_file(tmp_path, "alice.json", calls=100)
    rollup = build_money_saved_team_rollup([a, a], aliases=["alice", "alice-copy"], generated_at=FIXED_TS)
    assert rollup["member_count"] == 1
    assert rollup["duplicate_inputs"] and rollup["duplicate_inputs"][0]["duplicate_of_alias"] == "alice"


def test_incompatible_schema_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "something-else-v9", "export_type": "money_saved_registered_export"}), encoding="utf-8")
    with pytest.raises(IncompatibleExportError):
        build_money_saved_team_rollup([bad])


def test_unsafe_export_rejected(tmp_path):
    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text(
        json.dumps({
            "schema_version": "registered-export-v1",
            "export_type": "money_saved_registered_export",
            "raw_prompts_included": True,
        }),
        encoding="utf-8",
    )
    with pytest.raises(IncompatibleExportError):
        build_money_saved_team_rollup([unsafe])


def test_no_exact_money_or_token_overclaim(tmp_path):
    exp = _registered_export_file(tmp_path, "alice.json", calls=100)
    rollup = build_money_saved_team_rollup([exp], generated_at=FIXED_TS)
    assert rollup["dollars"]["enabled"] is False
    assert rollup["estimates"]["measurement_kind"] == "estimated"
    # The forbidden phrases must only appear inside the forbidden_claims list, never as an asserted claim.
    forbidden = rollup["claim_boundary"]["forbidden_claims"]
    assert "exact tokens saved" in forbidden
    assert "exact money saved" in forbidden
    assert "hosted team dashboard" in forbidden
    allowed_text = " ".join(rollup["claim_boundary"]["allowed_claims"]).lower()
    assert "exact tokens" not in allowed_text and "exact money" not in allowed_text


def test_cli_writes_file_and_status(tmp_path, capsys):
    exp = _registered_export_file(tmp_path, "alice.json", calls=100)
    out = tmp_path / "team.json"
    args = argparse.Namespace(root=str(tmp_path), input=[str(exp)], alias=[], out=str(out), json_status=True)
    assert cmd_money_saved_team_rollup(args) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["written"] is True and status["schema_version"] == MSM_TEAM_ROLLUP_SCHEMA_VERSION
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["report_type"] == "money_saved_team_rollup"


def test_cli_no_input_exit_2(tmp_path):
    args = argparse.Namespace(root=str(tmp_path), input=[], alias=[], out="", json_status=False)
    assert cmd_money_saved_team_rollup(args) == 2


def test_free_meter_and_registered_export_unchanged(tmp_path):
    """The Team tier must not mutate the Free meter or Registered export contracts."""
    from unlimited_skills.money_saved_meter import (
        REGISTERED_EXPORT_SCHEMA_VERSION,
        REPORT_SCHEMA_VERSION,
        REPORT_TYPE,
    )

    assert REGISTERED_EXPORT_SCHEMA_VERSION == "registered-export-v1"
    assert REPORT_TYPE == "money_saved_meter"
    assert REPORT_SCHEMA_VERSION == 1
    export = build_registered_export(tmp_path, generated_at=FIXED_TS)
    assert export["export_type"] == "money_saved_registered_export"
    assert export["schema_version"] == REGISTERED_EXPORT_SCHEMA_VERSION
