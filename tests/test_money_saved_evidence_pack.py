"""Tests for the Enterprise-tier Money Saved evidence pack + verifier
(O064-MSM-ENTERPRISE-IMPL).

Proves the pack is generated with all proof files, is independently verifiable,
is tamper-evident (any edited/missing file -> ok=false), produces a stable
reproducibility hash for identical input, rejects unsafe input, and makes no
hosted / SSO / SCIM / governance / signature-enforced claim.
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
    MSM_EVIDENCE_PACK_SCHEMA_VERSION,
    IncompatibleExportError,
    build_money_saved_admin_export,
    build_money_saved_evidence_pack,
    build_money_saved_team_rollup,
    money_saved_admin_export_json,
    money_saved_team_rollup_json,
    verify_money_saved_evidence_pack,
    write_money_saved_evidence_pack,
)
from unlimited_skills.commands.money_saved import (
    cmd_money_saved_evidence_pack,
    cmd_money_saved_verify_evidence_pack,
)

FIXED_TS = "2026-01-01T00:00:00Z"
LABELS = {"alice": {"team": "core", "workspace": "ws1", "agent_class": "builder", "project": "alpha"}}
_PACK_FILES = {
    "manifest.json",
    "method-and-assumptions.md",
    "privacy-proof.json",
    "schema-version-proof.json",
    "measurement-proof.json",
    "claim-boundary-proof.json",
    "reproducibility-proof.json",
}


def _admin_file(tmp_path: Path) -> Path:
    from unlimited_skills.money_saved_meter import fixture_100_call_mcp_savings_payload

    export = build_registered_export(
        tmp_path,
        mode="fixture_100_call",
        mcp_savings_report=fixture_100_call_mcp_savings_payload(),
        generated_at=FIXED_TS,
    )
    export["body"]["window"]["window_call_count"] = 100
    reg = tmp_path / "alice.json"
    reg.write_text(registered_export_json(export), encoding="utf-8")
    rollup = build_money_saved_team_rollup([reg], aliases=["alice"], generated_at=FIXED_TS)
    rf = tmp_path / "team.json"
    rf.write_text(money_saved_team_rollup_json(rollup), encoding="utf-8")
    admin = build_money_saved_admin_export(rf, labels=LABELS, generated_at=FIXED_TS)
    af = tmp_path / "admin.json"
    af.write_text(money_saved_admin_export_json(admin), encoding="utf-8")
    return af


def _written_pack(tmp_path: Path) -> Path:
    pack = build_money_saved_evidence_pack(_admin_file(tmp_path), generated_at=FIXED_TS)
    out_dir = tmp_path / "evidence"
    write_money_saved_evidence_pack(pack, out_dir)
    return out_dir


def test_pack_generated_with_all_files(tmp_path):
    out_dir = _written_pack(tmp_path)
    present = {p.name for p in out_dir.iterdir()}
    assert _PACK_FILES.issubset(present)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == MSM_EVIDENCE_PACK_SCHEMA_VERSION


def test_verifier_passes_clean_pack(tmp_path):
    report = verify_money_saved_evidence_pack(_written_pack(tmp_path))
    assert report["ok"] is True
    assert all(c["ok"] for c in report["checks"])
    names = {c["check"] for c in report["checks"]}
    assert {
        "manifest_schema",
        "files_exist_and_hashes_match",
        "schema_version_proof_matches_chain",
        "privacy_proof_passes_and_fail_closed_enforced",
        "measured_vs_estimated_proof_and_dollars_disabled",
        "no_exact_money_token_or_bill_reduction_claim",
        "reproducibility_hash_matches_inventory",
        "local_only_no_egress",
    }.issubset(names)


def test_verifier_fails_tampered_file(tmp_path):
    out_dir = _written_pack(tmp_path)
    (out_dir / "privacy-proof.json").write_text('{"tampered": true}', encoding="utf-8")
    report = verify_money_saved_evidence_pack(out_dir)
    assert report["ok"] is False
    hash_check = next(c for c in report["checks"] if c["check"] == "files_exist_and_hashes_match")
    assert hash_check["ok"] is False


def test_verifier_fails_missing_file(tmp_path):
    out_dir = _written_pack(tmp_path)
    (out_dir / "measurement-proof.json").unlink()
    assert verify_money_saved_evidence_pack(out_dir)["ok"] is False


def test_stable_hash_for_identical_input(tmp_path):
    af = _admin_file(tmp_path)
    p1 = build_money_saved_evidence_pack(af, generated_at="2026-01-01T00:00:00Z")
    p2 = build_money_saved_evidence_pack(af, generated_at="2026-12-31T23:59:59Z")
    assert p1["reproducibility_hash"] == p2["reproducibility_hash"]


def test_unsafe_input_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "money-saved-admin-export-v1", "raw_prompts_included": True}), encoding="utf-8")
    with pytest.raises(IncompatibleExportError):
        build_money_saved_evidence_pack(bad)


def test_no_hosted_sso_scim_governance_signature_claim(tmp_path):
    out_dir = _written_pack(tmp_path)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    nc = manifest["non_claims"]
    for key in ("exact_money", "exact_tokens", "bill_reduction", "sso_scim", "hosted_governance", "enforced_policy", "signature_enforced"):
        assert nc[key] is False
    allowed = " ".join(manifest["claim_boundary"]["allowed_claims"]).lower()
    for needle in ("sso", "scim", "hosted governance", "signature"):
        assert needle not in allowed


def test_cli_returns_0_then_1(tmp_path, capsys):
    out_dir = _written_pack(tmp_path)
    args = argparse.Namespace(root=str(tmp_path), input=str(out_dir), json=True)
    assert cmd_money_saved_verify_evidence_pack(args) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    (out_dir / "manifest.json").unlink()
    args2 = argparse.Namespace(root=str(tmp_path), input=str(out_dir), json=True)
    assert cmd_money_saved_verify_evidence_pack(args2) == 1


def test_cli_evidence_pack_writes_and_bad_input(tmp_path, capsys):
    af = _admin_file(tmp_path)
    out_dir = tmp_path / "ev2"
    args = argparse.Namespace(root=str(tmp_path), input=str(af), out=str(out_dir))
    assert cmd_money_saved_evidence_pack(args) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["evidence_pack_written"] is True
    # missing input -> exit 2
    args_bad = argparse.Namespace(root=str(tmp_path), input="", out=str(out_dir))
    assert cmd_money_saved_evidence_pack(args_bad) == 2


def test_cli_verify_missing_input_exit_2(tmp_path):
    args = argparse.Namespace(root=str(tmp_path), input="", json=True)
    assert cmd_money_saved_verify_evidence_pack(args) == 2
