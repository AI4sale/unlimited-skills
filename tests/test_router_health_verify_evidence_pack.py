"""Tests for the router-health evidence-pack verifier (O062-TIER-ENTERPRISE-IMPL-R).

Proves the evidence pack is independently verifiable and tamper-evident.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unlimited_skills.router_health import (
    build_router_health_admin_export,
    build_router_health_evidence_pack,
    build_router_health_export,
    build_router_health_team_rollup,
    router_health_admin_export_json,
    router_health_export_json,
    router_health_team_rollup_json,
    verify_router_health_evidence_pack,
    write_router_health_evidence_pack,
)
from unlimited_skills.commands.router_health import cmd_router_health_verify_evidence_pack

FIXED_TS = "2026-01-01T00:00:00Z"
LABELS = {"alice": {"team": "core", "workspace": "ws1", "agent_class": "builder"}}


def _written_pack(tmp_path: Path) -> Path:
    root = tmp_path / "alice"
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    (learning / "router-metrics.json").write_text(
        json.dumps({"total_invocations": 5, "last_call": {"iso": "2026-01-02T00:00:00Z", "path": "lexical", "reason_code": "match_found"}}),
        encoding="utf-8",
    )
    (root / ".chroma-skills").mkdir(exist_ok=True)
    exp = tmp_path / "alice.json"
    exp.write_text(router_health_export_json(build_router_health_export(root, generated_at=FIXED_TS)), encoding="utf-8")
    rollup = build_router_health_team_rollup([exp], generated_at=FIXED_TS)
    rollup_file = tmp_path / "team.json"
    rollup_file.write_text(router_health_team_rollup_json(rollup), encoding="utf-8")
    admin = build_router_health_admin_export(rollup_file, labels=LABELS, generated_at=FIXED_TS)
    admin_file = tmp_path / "admin.json"
    admin_file.write_text(router_health_admin_export_json(admin), encoding="utf-8")
    pack = build_router_health_evidence_pack(admin_file, generated_at=FIXED_TS)
    out_dir = tmp_path / "evidence"
    write_router_health_evidence_pack(pack, out_dir)
    return out_dir


def test_clean_pack_verifies_ok(tmp_path):
    report = verify_router_health_evidence_pack(_written_pack(tmp_path))
    assert report["schema_version"] == "router-health-evidence-pack-verification-v1"
    assert report["ok"] is True
    assert all(c["ok"] for c in report["checks"])
    names = {c["check"] for c in report["checks"]}
    assert {"manifest_schema", "files_exist_and_hashes_match", "schema_version_proof_matches_chain",
            "privacy_proof_passes_and_fail_closed_enforced", "reproducibility_hash_matches_inventory",
            "local_only_no_egress"}.issubset(names)


def test_tampered_file_fails_hash_check(tmp_path):
    out_dir = _written_pack(tmp_path)
    (out_dir / "privacy-proof.json").write_text('{"tampered": true}', encoding="utf-8")
    report = verify_router_health_evidence_pack(out_dir)
    assert report["ok"] is False
    hash_check = next(c for c in report["checks"] if c["check"] == "files_exist_and_hashes_match")
    assert hash_check["ok"] is False


def test_missing_file_fails(tmp_path):
    out_dir = _written_pack(tmp_path)
    (out_dir / "schema-version-proof.json").unlink()
    assert verify_router_health_evidence_pack(out_dir)["ok"] is False


def test_missing_manifest_fails(tmp_path):
    out_dir = tmp_path / "empty"
    out_dir.mkdir()
    report = verify_router_health_evidence_pack(out_dir)
    assert report["ok"] is False
    assert report["checks"][0]["check"] == "manifest_present"


def test_cli_returns_0_then_1(tmp_path, capsys):
    out_dir = _written_pack(tmp_path)
    args = argparse.Namespace(root=str(tmp_path), input=str(out_dir), json=True)
    assert cmd_router_health_verify_evidence_pack(args) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    (out_dir / "manifest.json").unlink()
    args2 = argparse.Namespace(root=str(tmp_path), input=str(out_dir), json=True)
    assert cmd_router_health_verify_evidence_pack(args2) == 1


def test_cli_missing_input_exit_2(tmp_path):
    args = argparse.Namespace(root=str(tmp_path), input="", json=True)
    assert cmd_router_health_verify_evidence_pack(args) == 2
