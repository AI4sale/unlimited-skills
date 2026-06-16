"""Tests for the Team-tier Learning Loop rollup (O063-TIER-TEAM-IMPL)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from unlimited_skills.learning_tiers import (
    IncompatibleExportError,
    build_learning_export,
    build_learning_team_rollup,
    learning_export_json,
    learning_team_rollup_json,
)
from unlimited_skills.commands.learning import cmd_learning_team_rollup

FIXED_TS = "2026-01-01T00:00:00Z"


def _make_export_file(tmp_path: Path, name: str, feedback_rows: list[dict]) -> Path:
    root = tmp_path / name
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    if feedback_rows:
        (learning / "feedback.jsonl").write_text("\n".join(json.dumps(r) for r in feedback_rows) + "\n", encoding="utf-8")
    out = tmp_path / f"{name}.json"
    out.write_text(learning_export_json(build_learning_export(root, generated_at=FIXED_TS)), encoding="utf-8")
    return out


def test_one_export(tmp_path):
    a = _make_export_file(tmp_path, "alice", [{"verdict": "wrong", "skill": "x"}])
    rollup = build_learning_team_rollup([a], generated_at=FIXED_TS)
    assert rollup["schema_version"] == "learning-team-rollup-v1"
    assert rollup["report_type"] == "learning_team_rollup"
    assert rollup["tier"] == "team"
    assert rollup["member_count"] == 1
    assert rollup["team_total_feedback"] == 1
    assert rollup["members"][0]["alias"] == "alice"


def test_multiple_exports_aggregate(tmp_path):
    a = _make_export_file(tmp_path, "alice", [{"verdict": "wrong", "skill": "x"}, {"verdict": "missed", "skill": "y"}])
    b = _make_export_file(tmp_path, "bob", [{"verdict": "wrong", "skill": "z"}])
    rollup = build_learning_team_rollup([a, b], generated_at=FIXED_TS)
    assert rollup["member_count"] == 2
    assert rollup["team_total_feedback"] == 3
    assert sum(rollup["aggregate_outcome_counts"].values()) == 3


def test_duplicate_input_deduped(tmp_path):
    a = _make_export_file(tmp_path, "alice", [{"verdict": "wrong", "skill": "x"}])
    rollup = build_learning_team_rollup([a, a], generated_at=FIXED_TS)
    assert rollup["member_count"] == 1
    assert rollup["duplicate_inputs"] and rollup["duplicate_inputs"][0]["duplicate_of_alias"] == "alice"


def test_no_feedback_member_flagged(tmp_path):
    idle = _make_export_file(tmp_path, "idle", [])
    active = _make_export_file(tmp_path, "active", [{"verdict": "wrong", "skill": "x"}])
    rollup = build_learning_team_rollup([idle, active], generated_at=FIXED_TS)
    assert "idle" in rollup["no_feedback_members"]
    assert "active" not in rollup["no_feedback_members"]


def test_incompatible_schema_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "WRONG"}), encoding="utf-8")
    with pytest.raises(IncompatibleExportError):
        build_learning_team_rollup([bad], generated_at=FIXED_TS)


def test_unsafe_export_rejected(tmp_path):
    a = _make_export_file(tmp_path, "alice", [{"verdict": "wrong", "skill": "x"}])
    data = json.loads(a.read_text(encoding="utf-8"))
    data["feedback"]["raw_queries_included"] = True
    a.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(IncompatibleExportError):
        build_learning_team_rollup([a], generated_at=FIXED_TS)


def test_no_network_no_mutation_boundary(tmp_path):
    a = _make_export_file(tmp_path, "alice", [{"verdict": "wrong", "skill": "x"}])
    rollup = build_learning_team_rollup([a], generated_at=FIXED_TS)
    assert rollup["delivery"]["network_fetch"] is False
    assert rollup["delivery"]["mutation"] is False
    assert rollup["privacy"]["os_usernames_or_emails_included"] is False
    assert learning_team_rollup_json(rollup) == learning_team_rollup_json(rollup)


def test_cli_rejects_incompatible_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "WRONG"}), encoding="utf-8")
    args = argparse.Namespace(root=str(tmp_path), input=[str(bad)], alias=[], out="", json_status=False)
    rc = cmd_learning_team_rollup(args)
    assert rc == 2
    assert "incompatible" in capsys.readouterr().out.lower()


def test_cli_writes_rollup_file(tmp_path):
    a = _make_export_file(tmp_path, "alice", [{"verdict": "wrong", "skill": "x"}])
    b = _make_export_file(tmp_path, "bob", [{"verdict": "missed", "skill": "y"}])
    out = tmp_path / "team.json"
    args = argparse.Namespace(root=str(tmp_path), input=[str(a), str(b)], alias=[], out=str(out), json_status=True)
    rc = cmd_learning_team_rollup(args)
    assert rc == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["member_count"] == 2
    assert written["team_total_feedback"] == 2
