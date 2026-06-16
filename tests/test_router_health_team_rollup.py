"""Tests for the Team-tier router-health rollup (O062-TIER-TEAM-IMPL).

Proves the rollup aggregates locally-gathered Registered exports with member
aliases, duplicate detection, incompatible-schema rejection, unsafe-export
rejection, and a no-network/no-dashboard boundary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from unlimited_skills.router_health import (
    IncompatibleExportError,
    build_router_health_export,
    build_router_health_team_rollup,
    router_health_export_json,
    router_health_team_rollup_json,
)
from unlimited_skills.commands.router_health import cmd_router_health_team_rollup

FIXED_TS = "2026-01-01T00:00:00Z"


def _make_export_file(tmp_path: Path, name: str, total: int, *, vector: bool = False, invoked: bool = True) -> Path:
    root = tmp_path / name
    learning = root / ".learning"
    learning.mkdir(parents=True)
    metrics = {"total_invocations": total}
    if invoked:
        metrics["last_call"] = {"iso": "2026-01-02T00:00:00Z", "path": "lexical", "reason_code": "match_found"}
    (learning / "router-metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    if vector:
        (root / ".chroma-skills").mkdir()
    else:
        (root / ".unlimited-skills-index.json").write_text("{}", encoding="utf-8")
    export = build_router_health_export(root, generated_at=FIXED_TS)
    out = tmp_path / f"{name}.json"
    out.write_text(router_health_export_json(export), encoding="utf-8")
    return out


def test_one_export(tmp_path):
    a = _make_export_file(tmp_path, "alice", 5, vector=True)
    rollup = build_router_health_team_rollup([a], generated_at=FIXED_TS)
    assert rollup["schema_version"] == "router-health-team-rollup-v1"
    assert rollup["report_type"] == "router_health_team_rollup"
    assert rollup["tier"] == "team"
    assert rollup["member_count"] == 1
    assert rollup["team_total_invocations"] == 5
    assert rollup["members"][0]["alias"] == "alice"


def test_multiple_exports(tmp_path):
    a = _make_export_file(tmp_path, "alice", 5, vector=True)
    b = _make_export_file(tmp_path, "bob", 3, vector=False)
    rollup = build_router_health_team_rollup([a, b], generated_at=FIXED_TS)
    assert rollup["member_count"] == 2
    assert rollup["team_total_invocations"] == 8
    summary = rollup["non_english_readiness_summary"]
    assert summary.get("multilingual_vector_ready") == 1
    assert summary.get("lexical_fallback_only") == 1


def test_duplicate_input_deduped(tmp_path):
    a = _make_export_file(tmp_path, "alice", 5, vector=True)
    rollup = build_router_health_team_rollup([a, a], generated_at=FIXED_TS)
    assert rollup["member_count"] == 1
    assert rollup["team_total_invocations"] == 5
    assert rollup["duplicate_inputs"] and rollup["duplicate_inputs"][0]["duplicate_of_alias"] == "alice"


def test_stale_member_flagged(tmp_path):
    idle = _make_export_file(tmp_path, "idle", 0, invoked=False)
    active = _make_export_file(tmp_path, "active", 4, vector=True)
    rollup = build_router_health_team_rollup([idle, active], generated_at=FIXED_TS)
    assert "idle" in rollup["stale_or_no_router_call_members"]
    assert "active" not in rollup["stale_or_no_router_call_members"]


def test_incompatible_schema_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "WRONG"}), encoding="utf-8")
    with pytest.raises(IncompatibleExportError):
        build_router_health_team_rollup([bad], generated_at=FIXED_TS)


def test_unsafe_export_rejected(tmp_path):
    a = _make_export_file(tmp_path, "alice", 5, vector=True)
    data = json.loads(a.read_text(encoding="utf-8"))
    data["router"]["raw_queries_included"] = True  # privacy violation
    a.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(IncompatibleExportError):
        build_router_health_team_rollup([a], generated_at=FIXED_TS)


def test_no_network_or_dashboard_boundary(tmp_path):
    a = _make_export_file(tmp_path, "alice", 5, vector=True)
    rollup = build_router_health_team_rollup([a], generated_at=FIXED_TS)
    assert rollup["delivery"]["network_fetch"] is False
    assert rollup["delivery"]["hosted_sync"] is False
    assert rollup["delivery"]["dashboard"] is False
    assert rollup["privacy"]["os_usernames_or_emails_included"] is False
    # Stable, sorted JSON.
    assert router_health_team_rollup_json(rollup) == router_health_team_rollup_json(rollup)


def test_cli_rejects_incompatible_with_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "WRONG"}), encoding="utf-8")
    args = argparse.Namespace(root=str(tmp_path), input=[str(bad)], alias=[], out="", json_status=False)
    rc = cmd_router_health_team_rollup(args)
    assert rc == 2
    assert "incompatible" in capsys.readouterr().out.lower()


def test_cli_writes_rollup_file(tmp_path):
    a = _make_export_file(tmp_path, "alice", 5, vector=True)
    b = _make_export_file(tmp_path, "bob", 3)
    out = tmp_path / "team.json"
    args = argparse.Namespace(root=str(tmp_path), input=[str(a), str(b)], alias=[], out=str(out), json_status=True)
    rc = cmd_router_health_team_rollup(args)
    assert rc == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["member_count"] == 2
    assert written["team_total_invocations"] == 8
