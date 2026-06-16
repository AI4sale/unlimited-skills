"""Tests for the Enterprise-tier Learning Loop evidence pack (O063-TIER-ENTERPRISE-IMPL)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from unlimited_skills.learning_tiers import (
    IncompatibleExportError,
    build_learning_admin_export,
    build_learning_evidence_pack,
    build_learning_export,
    build_learning_team_rollup,
    learning_admin_export_json,
    learning_export_json,
    learning_team_rollup_json,
    validate_learning_evidence_pack_manifest,
    write_learning_evidence_pack,
)
from unlimited_skills.commands.learning import cmd_learning_evidence_pack

FIXED_TS = "2026-01-01T00:00:00Z"
OTHER_TS = "2026-09-09T09:09:09Z"
LABELS = {"alice": {"team": "core", "workspace": "ws1", "agent_class": "builder"}}


def _admin_file(tmp_path: Path, name: str = "admin.json", *, generated_at: str = FIXED_TS) -> Path:
    root = tmp_path / "alice"
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    (learning / "feedback.jsonl").write_text(json.dumps({"verdict": "wrong", "skill": "x"}) + "\n", encoding="utf-8")
    exp = tmp_path / "alice.json"
    exp.write_text(learning_export_json(build_learning_export(root, generated_at=generated_at)), encoding="utf-8")
    rollup = build_learning_team_rollup([exp], generated_at=generated_at)
    rollup_file = tmp_path / "team.json"
    rollup_file.write_text(learning_team_rollup_json(rollup), encoding="utf-8")
    export = build_learning_admin_export(rollup_file, labels=LABELS, generated_at=generated_at)
    out = tmp_path / name
    out.write_text(learning_admin_export_json(export), encoding="utf-8")
    return out


def test_pack_generated(tmp_path):
    pack = build_learning_evidence_pack(_admin_file(tmp_path), generated_at=FIXED_TS)
    assert pack["manifest"]["schema_version"] == "learning-evidence-pack-v1"
    assert pack["manifest"]["tier"] == "enterprise"
    assert set(pack["files"]) == {
        "method-and-assumptions.md", "privacy-proof.json", "non-mutation-proof.json",
        "closed-loop-dry-run-proof.json", "schema-version-proof.json",
    }


def test_manifest_validates(tmp_path):
    pack = build_learning_evidence_pack(_admin_file(tmp_path), generated_at=FIXED_TS)
    assert validate_learning_evidence_pack_manifest(pack["manifest"]) is True
    broken = dict(pack["manifest"])
    broken.pop("reproducibility_hash")
    assert validate_learning_evidence_pack_manifest(broken) is False


def test_non_mutation_proof(tmp_path):
    pack = build_learning_evidence_pack(_admin_file(tmp_path), generated_at=FIXED_TS)
    nm = pack["non_mutation_proof"]
    assert nm["mutation_supported"] is False
    assert nm["skill_files_written"] is False
    assert nm["apply_candidate_is_dry_run_only"] is True
    assert pack["manifest"]["non_claims"]["automatic_skill_improvement"] is False


def test_write_pack_creates_all_files(tmp_path):
    pack = build_learning_evidence_pack(_admin_file(tmp_path), generated_at=FIXED_TS)
    out_dir = tmp_path / "evidence"
    written = write_learning_evidence_pack(pack, out_dir)
    assert "manifest.json" in written and "non-mutation-proof.json" in written
    for fname in written:
        assert (out_dir / fname).is_file()
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert validate_learning_evidence_pack_manifest(manifest)


def test_reproducibility_hash_stable_for_identical_data(tmp_path):
    f1 = _admin_file(tmp_path, "admin1.json", generated_at=FIXED_TS)
    f2 = _admin_file(tmp_path, "admin2.json", generated_at=OTHER_TS)
    h1 = build_learning_evidence_pack(f1, generated_at=FIXED_TS)["reproducibility_hash"]
    h2 = build_learning_evidence_pack(f2, generated_at=OTHER_TS)["reproducibility_hash"]
    assert h1 == h2


def test_privacy_proof_rejects_unsafe_input(tmp_path):
    f = _admin_file(tmp_path)
    data = json.loads(f.read_text(encoding="utf-8"))
    data["rows_unsafe_local_absolute_paths_included"] = True
    f.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(IncompatibleExportError):
        build_learning_evidence_pack(f, generated_at=FIXED_TS)


def test_no_network_no_egress_boundary(tmp_path):
    manifest = build_learning_evidence_pack(_admin_file(tmp_path), generated_at=FIXED_TS)["manifest"]
    assert manifest["privacy"]["no_egress"] is True
    assert manifest["privacy"]["network_access"] is False
    assert manifest["non_claims"]["sso_scim"] is False
    assert manifest["non_claims"]["signature_enforced"] is False


def test_cli_writes_evidence_dir(tmp_path):
    f = _admin_file(tmp_path)
    out_dir = tmp_path / "evidence-out"
    args = argparse.Namespace(root=str(tmp_path), input=str(f), out=str(out_dir))
    rc = cmd_learning_evidence_pack(args)
    assert rc == 0
    assert (out_dir / "manifest.json").is_file()
    assert (out_dir / "non-mutation-proof.json").is_file()


def test_cli_rejects_incompatible_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "WRONG"}), encoding="utf-8")
    args = argparse.Namespace(root=str(tmp_path), input=str(bad), out=str(tmp_path / "e"))
    rc = cmd_learning_evidence_pack(args)
    assert rc == 2
    assert "incompatible" in capsys.readouterr().out.lower()
