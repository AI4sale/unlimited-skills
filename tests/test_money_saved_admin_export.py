"""Tests for the Business-tier Money Saved admin export (O064-MSM-BUSINESS-IMPL).

Proves the admin export renders consistent CSV + JSON over a Team rollup, groups
by admin-supplied local labels (team/workspace/agent_class/project), keeps
measured facts separate from token estimates, handles missing labels safely, and
carries no hosted dashboard / billing / telemetry claim. Fail-closed.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

import pytest

from unlimited_skills.money_saved_meter import (
    build_registered_export,
    registered_export_json,
)
from unlimited_skills.money_saved_tiers import (
    MSM_ADMIN_EXPORT_SCHEMA_VERSION,
    IncompatibleExportError,
    build_money_saved_admin_export,
    build_money_saved_team_rollup,
    money_saved_admin_export_csv,
    money_saved_team_rollup_json,
)
from unlimited_skills.commands.money_saved import cmd_money_saved_admin_export

FIXED_TS = "2026-01-01T00:00:00Z"
LABELS = {"alice": {"team": "core", "workspace": "ws1", "agent_class": "builder", "project": "alpha"}}


def _team_rollup_file(tmp_path: Path, aliases: list[str]) -> Path:
    from unlimited_skills.money_saved_meter import fixture_100_call_mcp_savings_payload

    inputs = []
    for alias in aliases:
        export = build_registered_export(
            tmp_path,
            mode="fixture_100_call",
            mcp_savings_report=fixture_100_call_mcp_savings_payload(),
            generated_at=FIXED_TS,
        )
        export["body"]["window"]["window_call_count"] = 100
        p = tmp_path / f"{alias}.json"
        p.write_text(registered_export_json(export), encoding="utf-8")
        inputs.append(p)
    rollup = build_money_saved_team_rollup(inputs, aliases=aliases, generated_at=FIXED_TS)
    rf = tmp_path / "team.json"
    rf.write_text(money_saved_team_rollup_json(rollup), encoding="utf-8")
    return rf


def test_json_export(tmp_path):
    rf = _team_rollup_file(tmp_path, ["alice"])
    export = build_money_saved_admin_export(rf, labels=LABELS, generated_at=FIXED_TS)
    assert export["schema_version"] == MSM_ADMIN_EXPORT_SCHEMA_VERSION
    assert export["report_type"] == "money_saved_admin_export"
    assert export["rows"][0]["team"] == "core"
    assert export["rows"][0]["project"] == "alpha"


def test_csv_export(tmp_path):
    rf = _team_rollup_file(tmp_path, ["alice"])
    export = build_money_saved_admin_export(rf, labels=LABELS, generated_at=FIXED_TS)
    csv_text = money_saved_admin_export_csv(export)
    reader = list(csv.DictReader(io.StringIO(csv_text)))
    assert reader[0]["alias"] == "alice"
    assert reader[0]["team"] == "core"
    assert reader[0]["window_call_count"] == "100"


def test_csv_and_json_agree(tmp_path):
    rf = _team_rollup_file(tmp_path, ["alice", "bob"])
    export = build_money_saved_admin_export(rf, labels=LABELS, generated_at=FIXED_TS)
    json_rows = export["rows"]
    csv_rows = list(csv.DictReader(io.StringIO(money_saved_admin_export_csv(export))))
    assert len(json_rows) == len(csv_rows)
    for jr, cr in zip(json_rows, csv_rows):
        assert cr["alias"] == jr["alias"]
        assert cr["window_call_count"] == str(jr["window_call_count"])
        # agent_class falls back to unlabeled for bob (no label entry)
        assert cr["agent_class"] == jr["agent_class"]


def test_missing_labels_safe(tmp_path):
    rf = _team_rollup_file(tmp_path, ["bob"])  # no label entry for bob
    export = build_money_saved_admin_export(rf, labels=LABELS, generated_at=FIXED_TS)
    row = export["rows"][0]
    assert row["team"] == "unlabeled"
    assert row["workspace"] == "unlabeled"
    assert row["project"] == "unlabeled"


def test_measured_vs_estimated_separation(tmp_path):
    rf = _team_rollup_file(tmp_path, ["alice"])
    export = build_money_saved_admin_export(rf, labels=LABELS, generated_at=FIXED_TS)
    assert "total_window_call_count" in export["measured"]
    assert "total_measured_context_bytes_avoided" in export["measured"]
    assert export["estimated"]["measurement_kind"] == "estimated"
    assert "estimated_tokens" not in export["measured"]  # estimates never live under measured


def test_forbidden_needles_absent(tmp_path):
    rf = _team_rollup_file(tmp_path, ["alice"])
    export = build_money_saved_admin_export(rf, labels=LABELS, generated_at=FIXED_TS)
    assert export["dollars"]["enabled"] is False
    forbidden = export["claim_boundary"]["forbidden_claims"]
    for needle in ("hosted admin dashboard", "billing or entitlement", "telemetry-backed admin analytics", "exact money saved"):
        assert needle in forbidden
    # delivery explicitly disclaims hosted/billing/telemetry
    assert export["delivery"]["hosted_dashboard"] is False
    assert export["delivery"]["billing_or_entitlement"] is False
    assert export["delivery"]["telemetry"] is False


def test_no_hosted_billing_telemetry_claim_in_allowed(tmp_path):
    rf = _team_rollup_file(tmp_path, ["alice"])
    export = build_money_saved_admin_export(rf, labels=LABELS, generated_at=FIXED_TS)
    allowed = " ".join(export["claim_boundary"]["allowed_claims"]).lower()
    for needle in ("hosted", "billing", "telemetry", "dashboard"):
        assert needle not in allowed


def test_incompatible_input_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "registered-export-v1"}), encoding="utf-8")
    with pytest.raises(IncompatibleExportError):
        build_money_saved_admin_export(bad)


def test_cli_writes_csv_and_json(tmp_path):
    rf = _team_rollup_file(tmp_path, ["alice"])
    labels_file = tmp_path / "labels.json"
    labels_file.write_text(json.dumps(LABELS), encoding="utf-8")
    csv_out = tmp_path / "m.csv"
    json_out = tmp_path / "m.json"
    args = argparse.Namespace(root=str(tmp_path), input=str(rf), labels=str(labels_file), csv=str(csv_out), json=str(json_out))
    assert cmd_money_saved_admin_export(args) == 0
    assert csv_out.is_file() and json_out.is_file()
    written = json.loads(json_out.read_text(encoding="utf-8"))
    assert written["schema_version"] == MSM_ADMIN_EXPORT_SCHEMA_VERSION


def test_cli_no_input_exit_2(tmp_path):
    args = argparse.Namespace(root=str(tmp_path), input="", labels="", csv="", json="")
    assert cmd_money_saved_admin_export(args) == 2
