"""Tests for the Enterprise-tier router-health evidence pack (O062-TIER-ENTERPRISE-IMPL).

Proves the pack is generated with manifest / method / privacy-proof / schema-proof,
a reproducibility hash that is stable for identical input data, privacy-proof
rejection of unsafe input, and a no-network / no-egress boundary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from unlimited_skills.router_health import (
    IncompatibleExportError,
    build_router_health_admin_export,
    build_router_health_evidence_pack,
    build_router_health_export,
    build_router_health_team_rollup,
    router_health_admin_export_json,
    router_health_export_json,
    router_health_team_rollup_json,
    validate_evidence_pack_manifest,
    write_router_health_evidence_pack,
)
from unlimited_skills.commands.router_health import cmd_router_health_evidence_pack

FIXED_TS = "2026-01-01T00:00:00Z"
OTHER_TS = "2026-09-09T09:09:09Z"
LABELS = {"alice": {"team": "core", "workspace": "ws1", "agent_class": "builder"}}


def _admin_export(tmp_path: Path, *, generated_at: str) -> dict:
    root = tmp_path / "alice"
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    (learning / "router-metrics.json").write_text(
        json.dumps({"total_invocations": 5, "last_call": {"iso": "2026-01-02T00:00:00Z", "path": "lexical", "reason_code": "match_found"}}),
        encoding="utf-8",
    )
    (root / ".chroma-skills").mkdir(exist_ok=True)
    export = build_router_health_export(root, generated_at=generated_at)
    exp_file = tmp_path / "alice.json"
    exp_file.write_text(router_health_export_json(export), encoding="utf-8")
    rollup = build_router_health_team_rollup([exp_file], generated_at=generated_at)
    rollup_file = tmp_path / "team.json"
    rollup_file.write_text(router_health_team_rollup_json(rollup), encoding="utf-8")
    return build_router_health_admin_export(rollup_file, labels=LABELS, generated_at=generated_at)


def _admin_export_file(tmp_path: Path, name: str = "admin.json", *, generated_at: str = FIXED_TS) -> Path:
    export = _admin_export(tmp_path, generated_at=generated_at)
    out = tmp_path / name
    out.write_text(router_health_admin_export_json(export), encoding="utf-8")
    return out


def test_pack_generated(tmp_path):
    pack = build_router_health_evidence_pack(_admin_export_file(tmp_path), generated_at=FIXED_TS)
    assert pack["manifest"]["schema_version"] == "router-health-evidence-pack-v1"
    assert pack["manifest"]["tier"] == "enterprise"
    assert set(pack["files"]) == {"method-and-assumptions.md", "privacy-proof.json", "schema-version-proof.json"}
    assert pack["reproducibility_hash"]


def test_manifest_validates(tmp_path):
    pack = build_router_health_evidence_pack(_admin_export_file(tmp_path), generated_at=FIXED_TS)
    assert validate_evidence_pack_manifest(pack["manifest"]) is True
    # A broken manifest fails validation.
    broken = dict(pack["manifest"])
    broken.pop("reproducibility_hash")
    assert validate_evidence_pack_manifest(broken) is False


def test_write_pack_creates_all_files(tmp_path):
    pack = build_router_health_evidence_pack(_admin_export_file(tmp_path), generated_at=FIXED_TS)
    out_dir = tmp_path / "evidence"
    written = write_router_health_evidence_pack(pack, out_dir)
    assert set(written) == {"manifest.json", "method-and-assumptions.md", "privacy-proof.json", "schema-version-proof.json"}
    for fname in written:
        assert (out_dir / fname).is_file()
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert validate_evidence_pack_manifest(manifest)


def test_reproducibility_hash_stable_for_identical_data(tmp_path):
    # Same underlying data, different generation timestamps -> same evidence hash.
    f1 = _admin_export_file(tmp_path, "admin1.json", generated_at=FIXED_TS)
    f2 = _admin_export_file(tmp_path, "admin2.json", generated_at=OTHER_TS)
    h1 = build_router_health_evidence_pack(f1, generated_at=FIXED_TS)["reproducibility_hash"]
    h2 = build_router_health_evidence_pack(f2, generated_at=OTHER_TS)["reproducibility_hash"]
    assert h1 == h2


def test_privacy_proof_rejects_unsafe_input(tmp_path):
    f = _admin_export_file(tmp_path)
    data = json.loads(f.read_text(encoding="utf-8"))
    data["rows_unsafe_local_absolute_paths_included"] = True  # forbidden *_included flag
    f.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(IncompatibleExportError):
        build_router_health_evidence_pack(f, generated_at=FIXED_TS)


def test_no_network_no_egress_boundary(tmp_path):
    pack = build_router_health_evidence_pack(_admin_export_file(tmp_path), generated_at=FIXED_TS)
    manifest = pack["manifest"]
    assert manifest["privacy"]["no_egress"] is True
    assert manifest["privacy"]["network_access"] is False
    assert manifest["non_claims"] == {
        "sso_scim": False,
        "hosted_governance": False,
        "enforced_policy": False,
        "signature_enforced": False,
    }


def test_source_inventory_uses_safe_label_only(tmp_path):
    pack = build_router_health_evidence_pack(_admin_export_file(tmp_path, "admin.json"), generated_at=FIXED_TS)
    inv = pack["source_inventory"]
    assert inv and inv[0]["label"] == "admin.json"  # basename, not an absolute path
    assert "/" not in inv[0]["label"] and "\\" not in inv[0]["label"]


def test_cli_writes_evidence_dir(tmp_path):
    f = _admin_export_file(tmp_path)
    out_dir = tmp_path / "evidence-out"
    args = argparse.Namespace(root=str(tmp_path), input=str(f), out=str(out_dir))
    rc = cmd_router_health_evidence_pack(args)
    assert rc == 0
    assert (out_dir / "manifest.json").is_file()
    assert (out_dir / "privacy-proof.json").is_file()


def test_cli_rejects_incompatible_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "WRONG"}), encoding="utf-8")
    args = argparse.Namespace(root=str(tmp_path), input=str(bad), out=str(tmp_path / "e"))
    rc = cmd_router_health_evidence_pack(args)
    assert rc == 2
    assert "incompatible" in capsys.readouterr().out.lower()
