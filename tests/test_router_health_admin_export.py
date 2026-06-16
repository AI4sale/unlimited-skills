"""Tests for the Business-tier router-health admin export (O062-TIER-BUSINESS-IMPL).

Proves the admin export produces consistent CSV + JSON over a Team rollup, with
admin-supplied local labels, grouping, measured-vs-advisory separation, safe
handling of missing labels, and no hosted/billing/provider-id/telemetry surface.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

import pytest

from unlimited_skills.router_health import (
    IncompatibleExportError,
    build_router_health_admin_export,
    build_router_health_export,
    build_router_health_team_rollup,
    router_health_admin_export_csv,
    router_health_admin_export_json,
    router_health_export_json,
    router_health_team_rollup_json,
)
from unlimited_skills.commands.router_health import cmd_router_health_admin_export

FIXED_TS = "2026-01-01T00:00:00Z"


def _member_export(tmp_path: Path, name: str, total: int, *, vector: bool = True) -> Path:
    root = tmp_path / name
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    (learning / "router-metrics.json").write_text(
        json.dumps({"total_invocations": total, "last_call": {"iso": "2026-01-02T00:00:00Z", "path": "lexical", "reason_code": "match_found"}}),
        encoding="utf-8",
    )
    if vector:
        (root / ".chroma-skills").mkdir(exist_ok=True)
    else:
        (root / ".unlimited-skills-index.json").write_text("{}", encoding="utf-8")
    out = tmp_path / f"{name}.json"
    out.write_text(router_health_export_json(build_router_health_export(root, generated_at=FIXED_TS)), encoding="utf-8")
    return out


def _team_rollup_file(tmp_path: Path) -> Path:
    a = _member_export(tmp_path, "alice", 5, vector=True)
    b = _member_export(tmp_path, "bob", 3, vector=False)
    rollup = build_router_health_team_rollup([a, b], generated_at=FIXED_TS)
    out = tmp_path / "team.json"
    out.write_text(router_health_team_rollup_json(rollup), encoding="utf-8")
    return out


LABELS = {
    "alice": {"team": "core", "workspace": "ws1", "agent_class": "builder"},
    "bob": {"team": "core", "workspace": "ws2", "agent_class": "reviewer"},
}


def test_json_export(tmp_path):
    export = build_router_health_admin_export(_team_rollup_file(tmp_path), labels=LABELS, generated_at=FIXED_TS)
    assert export["schema_version"] == "router-health-admin-export-v1"
    assert export["report_type"] == "router_health_admin_export"
    assert export["tier"] == "business"
    assert export["measured"]["total_invocations"] == 8
    assert export["grouping"]["by_team"]["core"]["total_invocations"] == 8
    assert export["grouping"]["by_workspace"]["ws1"]["members"] == 1


def test_csv_export_has_header_and_rows(tmp_path):
    export = build_router_health_admin_export(_team_rollup_file(tmp_path), labels=LABELS, generated_at=FIXED_TS)
    text = router_health_admin_export_csv(export)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2
    assert {r["alias"] for r in rows} == {"alice", "bob"}
    assert {r["team"] for r in rows} == {"core"}


def test_csv_and_json_agree(tmp_path):
    export = build_router_health_admin_export(_team_rollup_file(tmp_path), labels=LABELS, generated_at=FIXED_TS)
    json_rows = {r["alias"]: r for r in export["rows"]}
    csv_rows = {r["alias"]: r for r in csv.DictReader(io.StringIO(router_health_admin_export_csv(export)))}
    assert set(json_rows) == set(csv_rows)
    for alias, jr in json_rows.items():
        cr = csv_rows[alias]
        assert str(jr["total_invocations"]) == cr["total_invocations"]
        assert cr["agent_class"] == jr["agent_class"]


def test_missing_labels_handled_safely(tmp_path):
    # No labels at all -> everything 'unlabeled', no crash.
    export = build_router_health_admin_export(_team_rollup_file(tmp_path), labels=None, generated_at=FIXED_TS)
    assert all(r["team"] == "unlabeled" for r in export["rows"])
    assert "unlabeled" in export["grouping"]["by_team"]
    # Partial labels -> the unlabeled member is still safe.
    partial = {"alice": {"team": "core"}}
    export2 = build_router_health_admin_export(_team_rollup_file(tmp_path), labels=partial, generated_at=FIXED_TS)
    by_alias = {r["alias"]: r for r in export2["rows"]}
    assert by_alias["alice"]["team"] == "core"
    assert by_alias["alice"]["workspace"] == "unlabeled"
    assert by_alias["bob"]["team"] == "unlabeled"


def test_measured_vs_advisory_separation(tmp_path):
    export = build_router_health_admin_export(_team_rollup_file(tmp_path), labels=LABELS, generated_at=FIXED_TS)
    assert "total_invocations" in export["measured"]
    assert "stale_or_no_router_call_members" in export["advisory"]


def test_forbidden_needles_absent(tmp_path):
    export = build_router_health_admin_export(_team_rollup_file(tmp_path), labels=LABELS, generated_at=FIXED_TS)
    blob = router_health_admin_export_json(export).lower()
    assert export["delivery"]["hosted_dashboard"] is False
    assert export["delivery"]["billing_or_entitlement"] is False
    assert export["privacy"]["provider_account_ids_included"] is False
    assert "c:\\" not in blob and "/home/" not in blob and "/users/" not in blob


def test_incompatible_rollup_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "router-health-export-v1"}), encoding="utf-8")  # an export, not a rollup
    with pytest.raises(IncompatibleExportError):
        build_router_health_admin_export(bad, generated_at=FIXED_TS)


def test_cli_writes_csv_and_json(tmp_path):
    team = _team_rollup_file(tmp_path)
    labels_file = tmp_path / "labels.json"
    labels_file.write_text(json.dumps(LABELS), encoding="utf-8")
    csv_out = tmp_path / "rh.csv"
    json_out = tmp_path / "rh.json"
    args = argparse.Namespace(root=str(tmp_path), input=str(team), labels=str(labels_file), csv=str(csv_out), json=str(json_out))
    rc = cmd_router_health_admin_export(args)
    assert rc == 0
    assert csv_out.is_file() and json_out.is_file()
    written = json.loads(json_out.read_text(encoding="utf-8"))
    assert written["measured"]["total_invocations"] == 8
    csv_rows = list(csv.DictReader(io.StringIO(csv_out.read_text(encoding="utf-8"))))
    assert len(csv_rows) == 2


def test_cli_rejects_incompatible_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "WRONG"}), encoding="utf-8")
    args = argparse.Namespace(root=str(tmp_path), input=str(bad), labels="", csv="", json="")
    rc = cmd_router_health_admin_export(args)
    assert rc == 2
    assert "incompatible" in capsys.readouterr().out.lower()
