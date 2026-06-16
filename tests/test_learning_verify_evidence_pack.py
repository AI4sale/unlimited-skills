"""Tests for the Learning Loop evidence-pack verifier (O063-TIER-ENTERPRISE-IMPL-R).

Proves the evidence pack is independently verifiable and tamper-evident: a clean
pack passes all checks; tampering with a file (content or deletion) fails the
hash/presence check.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from unlimited_skills.learning_tiers import (
    build_learning_admin_export,
    build_learning_evidence_pack,
    build_learning_export,
    build_learning_team_rollup,
    learning_admin_export_json,
    learning_export_json,
    learning_team_rollup_json,
    verify_learning_evidence_pack,
    write_learning_evidence_pack,
)
from unlimited_skills.commands.learning import cmd_learning_verify_evidence_pack

FIXED_TS = "2026-01-01T00:00:00Z"
LABELS = {"alice": {"team": "core", "workspace": "ws1", "agent_class": "builder"}}


def _written_pack(tmp_path: Path) -> Path:
    root = tmp_path / "alice"
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    (learning / "feedback.jsonl").write_text(json.dumps({"verdict": "wrong", "skill": "x"}) + "\n", encoding="utf-8")
    exp = tmp_path / "alice.json"
    exp.write_text(learning_export_json(build_learning_export(root, generated_at=FIXED_TS)), encoding="utf-8")
    rollup = build_learning_team_rollup([exp], generated_at=FIXED_TS)
    rollup_file = tmp_path / "team.json"
    rollup_file.write_text(learning_team_rollup_json(rollup), encoding="utf-8")
    admin = build_learning_admin_export(rollup_file, labels=LABELS, generated_at=FIXED_TS)
    admin_file = tmp_path / "admin.json"
    admin_file.write_text(learning_admin_export_json(admin), encoding="utf-8")
    pack = build_learning_evidence_pack(admin_file, generated_at=FIXED_TS)
    out_dir = tmp_path / "evidence"
    write_learning_evidence_pack(pack, out_dir)
    return out_dir


def test_clean_pack_verifies_ok(tmp_path):
    out_dir = _written_pack(tmp_path)
    report = verify_learning_evidence_pack(out_dir)
    assert report["schema_version"] == "learning-evidence-pack-verification-v1"
    assert report["ok"] is True
    assert all(c["ok"] for c in report["checks"])
    names = {c["check"] for c in report["checks"]}
    assert {"manifest_schema", "files_exist_and_hashes_match", "schema_version_proof_matches_chain",
            "privacy_proof_passes_and_fail_closed_enforced", "non_mutation_proof",
            "closed_loop_dry_run_reference", "reproducibility_hash_matches_inventory",
            "local_only_no_egress"}.issubset(names)


def test_tampered_file_fails_hash_check(tmp_path):
    out_dir = _written_pack(tmp_path)
    # Tamper with a pack file after the manifest hashed it.
    (out_dir / "non-mutation-proof.json").write_text('{"mutation_supported": true}', encoding="utf-8")
    report = verify_learning_evidence_pack(out_dir)
    assert report["ok"] is False
    hash_check = next(c for c in report["checks"] if c["check"] == "files_exist_and_hashes_match")
    assert hash_check["ok"] is False


def test_missing_file_fails(tmp_path):
    out_dir = _written_pack(tmp_path)
    (out_dir / "privacy-proof.json").unlink()
    report = verify_learning_evidence_pack(out_dir)
    assert report["ok"] is False


def test_missing_manifest_fails(tmp_path):
    out_dir = tmp_path / "empty"
    out_dir.mkdir()
    report = verify_learning_evidence_pack(out_dir)
    assert report["ok"] is False
    assert report["checks"][0]["check"] == "manifest_present"
    assert report["checks"][0]["ok"] is False


def test_cli_returns_0_on_ok_and_1_on_fail(tmp_path, capsys):
    out_dir = _written_pack(tmp_path)
    args = argparse.Namespace(root=str(tmp_path), input=str(out_dir), json=True)
    assert cmd_learning_verify_evidence_pack(args) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    (out_dir / "manifest.json").unlink()
    args2 = argparse.Namespace(root=str(tmp_path), input=str(out_dir), json=True)
    assert cmd_learning_verify_evidence_pack(args2) == 1


def test_cli_missing_input_exit_2(tmp_path, capsys):
    args = argparse.Namespace(root=str(tmp_path), input="", json=True)
    assert cmd_learning_verify_evidence_pack(args) == 2
