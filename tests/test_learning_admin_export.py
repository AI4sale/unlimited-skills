"""Tests for the Business-tier Learning Loop admin export (O063-TIER-BUSINESS-IMPL)."""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

import pytest

from unlimited_skills.learning_tiers import (
    IncompatibleExportError,
    build_learning_admin_export,
    build_learning_export,
    build_learning_team_rollup,
    learning_admin_export_csv,
    learning_admin_export_json,
    learning_export_json,
    learning_team_rollup_json,
)
from unlimited_skills.commands.learning import cmd_learning_admin_export

FIXED_TS = "2026-01-01T00:00:00Z"
LABELS = {
    "alice": {"team": "core", "workspace": "ws1", "agent_class": "builder"},
    "bob": {"team": "core", "workspace": "ws2", "agent_class": "reviewer"},
}


def _export_file(tmp_path: Path, name: str, rows: list[dict]) -> Path:
    root = tmp_path / name
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    if rows:
        (learning / "feedback.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    out = tmp_path / f"{name}.json"
    out.write_text(learning_export_json(build_learning_export(root, generated_at=FIXED_TS)), encoding="utf-8")
    return out


def _team_rollup_file(tmp_path: Path) -> Path:
    a = _export_file(tmp_path, "alice", [{"verdict": "wrong", "skill": "x"}, {"verdict": "missed", "skill": "y"}])
    b = _export_file(tmp_path, "bob", [{"verdict": "wrong", "skill": "z"}])
    rollup = build_learning_team_rollup([a, b], generated_at=FIXED_TS)
    out = tmp_path / "team.json"
    out.write_text(learning_team_rollup_json(rollup), encoding="utf-8")
    return out


def test_json_export(tmp_path):
    export = build_learning_admin_export(_team_rollup_file(tmp_path), labels=LABELS, generated_at=FIXED_TS)
    assert export["schema_version"] == "learning-admin-export-v1"
    assert export["tier"] == "business"
    assert export["measured"]["total_feedback"] == 3
    assert export["grouping"]["by_team"]["core"]["feedback_count"] == 3


def test_csv_and_json_agree(tmp_path):
    export = build_learning_admin_export(_team_rollup_file(tmp_path), labels=LABELS, generated_at=FIXED_TS)
    json_rows = {r["alias"]: r for r in export["rows"]}
    csv_rows = {r["alias"]: r for r in csv.DictReader(io.StringIO(learning_admin_export_csv(export)))}
    assert set(json_rows) == set(csv_rows)
    for alias, jr in json_rows.items():
        assert str(jr["feedback_count"]) == csv_rows[alias]["feedback_count"]
        assert csv_rows[alias]["agent_class"] == jr["agent_class"]


def test_missing_labels_handled_safely(tmp_path):
    export = build_learning_admin_export(_team_rollup_file(tmp_path), labels=None, generated_at=FIXED_TS)
    assert all(r["team"] == "unlabeled" for r in export["rows"])
    partial = build_learning_admin_export(_team_rollup_file(tmp_path), labels={"alice": {"team": "core"}}, generated_at=FIXED_TS)
    by_alias = {r["alias"]: r for r in partial["rows"]}
    assert by_alias["alice"]["team"] == "core"
    assert by_alias["alice"]["workspace"] == "unlabeled"
    assert by_alias["bob"]["team"] == "unlabeled"


def test_measured_vs_advisory_separation(tmp_path):
    export = build_learning_admin_export(_team_rollup_file(tmp_path), labels=LABELS, generated_at=FIXED_TS)
    assert "total_feedback" in export["measured"]
    assert "no_feedback_members" in export["advisory"]


def test_forbidden_needles_absent(tmp_path):
    export = build_learning_admin_export(_team_rollup_file(tmp_path), labels=LABELS, generated_at=FIXED_TS)
    blob = learning_admin_export_json(export).lower()
    assert export["delivery"]["hosted_dashboard"] is False
    assert export["delivery"]["mutation"] is False
    assert export["privacy"]["provider_account_ids_included"] is False
    assert "c:\\" not in blob and "/home/" not in blob and "/users/" not in blob


def test_incompatible_rollup_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "learning-export-v1"}), encoding="utf-8")  # an export, not a rollup
    with pytest.raises(IncompatibleExportError):
        build_learning_admin_export(bad, generated_at=FIXED_TS)


def test_cli_writes_csv_and_json(tmp_path):
    team = _team_rollup_file(tmp_path)
    labels_file = tmp_path / "labels.json"
    labels_file.write_text(json.dumps(LABELS), encoding="utf-8")
    csv_out = tmp_path / "l.csv"
    json_out = tmp_path / "l.json"
    args = argparse.Namespace(root=str(tmp_path), input=str(team), labels=str(labels_file), csv=str(csv_out), json=str(json_out))
    rc = cmd_learning_admin_export(args)
    assert rc == 0
    assert csv_out.is_file() and json_out.is_file()
    written = json.loads(json_out.read_text(encoding="utf-8"))
    assert written["measured"]["total_feedback"] == 3
    assert len(list(csv.DictReader(io.StringIO(csv_out.read_text(encoding="utf-8"))))) == 2


def test_cli_rejects_incompatible_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "WRONG"}), encoding="utf-8")
    args = argparse.Namespace(root=str(tmp_path), input=str(bad), labels="", csv="", json="")
    rc = cmd_learning_admin_export(args)
    assert rc == 2
    assert "incompatible" in capsys.readouterr().out.lower()
