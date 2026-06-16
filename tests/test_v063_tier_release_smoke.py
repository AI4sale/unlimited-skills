from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from scripts.verify_v063_tier_release_smoke import RELEASE, run_smoke, validate_report

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v063_tier_release_smoke_passes(tmp_path: Path) -> None:
    report = run_smoke(tmp_path / "smoke")

    assert report["ok"] is True
    assert report["release"] == RELEASE
    assert report["privacy"]["no_egress_asserted"] is True
    assert report["mutation"]["apply_candidate_dry_run_only"] is True

    surfaces = set(report["surfaces_checked"])
    assert {
        "learning doctor",
        "feedback contract",
        "improvement candidates",
        "apply candidate dry-run",
        "learning export",
        "learning team rollup",
        "learning admin export",
        "learning evidence pack",
        "learning verify evidence pack",
        "learning evidence pack tamper check",
        "router-health export",
        "router-health team rollup",
        "router-health admin export",
        "router-health evidence pack",
        "router-health verify evidence pack",
    }.issubset(surfaces)

    tamper = next(row for row in report["rows"] if row["surface"] == "learning evidence pack tamper check")
    assert tamper["ok"] is True
    assert tamper["expected_success"] is False
    assert tamper["returncode"] != 0


def test_v063_tier_release_smoke_validation_fails_for_missing_artifact(tmp_path: Path) -> None:
    report = run_smoke(tmp_path / "smoke")
    export_row = next(row for row in report["rows"] if row["artifact_paths"])
    export_row["artifact_paths"] = [str(tmp_path / "missing-artifact.json")]

    errors = validate_report(report)

    assert any("artifact missing" in error for error in errors)


def test_v063_tier_release_smoke_validation_fails_for_failed_row(tmp_path: Path) -> None:
    report = run_smoke(tmp_path / "smoke")
    report["rows"][0]["ok"] = False

    errors = validate_report(report)

    assert any("row failed" in error for error in errors)
    json.dumps(report, sort_keys=True)


def test_v063_release_package_manifest_and_claim_boundaries() -> None:
    manifest_path = REPO_ROOT / "docs" / "releases" / "v0.6.3-alpha.release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["release"] == RELEASE
    assert manifest["package_version"] == "0.6.3"
    assert manifest["status"] == "release_execution_ready"
    assert manifest["release_execution"]["package_ready"] is True
    assert manifest["release_execution"]["executed_in_this_pr"] is False
    assert (
        manifest["release_execution"]["stale_owner_gap_marker"]
        == "closed_reconciled_by_release_execution_package_if_all_gates_pass"
    )
    assert manifest["value_frame"]["v0_6_2_router_health"] == "compatibility_tier_debt_closure_only_not_v0_6_3_vfp"
    assert "v0.6.4 Money Saved Meter" in manifest["value_frame"]["excluded"]
    assert manifest["excluded_prs"] == [119]

    for raw in manifest["release_package_files"] + manifest["verifier_scripts"] + manifest["tests"]:
        assert (REPO_ROOT / raw).exists(), raw

    release_docs = [
        "docs/releases/v0.6.3-alpha.md",
        "docs/releases/v0.6.3-alpha-checklist.md",
        "docs/releases/v0.6.3-alpha-upgrade-notes.md",
        "docs/releases/v0.6.3-alpha-known-issues.md",
        "docs/releases/v0.6.3-alpha-pypi-publishing.md",
        "docs/releases/v0.6.3-personal-verification.md",
    ]
    text = "\n".join((REPO_ROOT / raw).read_text(encoding="utf-8") for raw in release_docs).lower()

    for command in [
        "unlimited-skills learning doctor",
        "unlimited-skills improvement-candidates",
        "unlimited-skills apply-candidate --dry-run",
        "unlimited-skills learning export",
        "unlimited-skills learning team-rollup",
        "unlimited-skills learning admin-export",
        "unlimited-skills learning evidence-pack",
        "unlimited-skills learning verify-evidence-pack",
        "python scripts/verify-v063-tier-release-smoke.py --json",
        "python scripts/run-v063-alpha-package-smoke.py --json",
        "python scripts/verify-v063-alpha-release-execution.py --json",
    ]:
        assert command in text

    assert "no docs-only tier value claim" in text
    assert "v0.6.4 money saved meter is out of scope" in text
    assert "release_owner_go_with_limits_acceptance" in text
    assert "hosted dashboard" in text
    assert "live sync" in text
    assert "sso/scim" in text
    assert "compatibility evidence only" in text
    assert "learning loop value frame" in text


def test_v063_release_execution_verifier_lightweight(monkeypatch, capsys) -> None:
    verifier_path = REPO_ROOT / "scripts" / "verify-v063-alpha-release-execution.py"
    spec = importlib.util.spec_from_file_location("verify_v063_alpha_release_execution_test", verifier_path)
    assert spec is not None
    assert spec.loader is not None
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)

    monkeypatch.setattr(verifier, "run_frozen_contracts", lambda: {"ok": True, "status_counts": {"pass": 11}})

    rc = verifier.main(["--allow-dirty", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["release"] == RELEASE
    assert payload["version"] == "0.6.3"
    assert payload["manifest_status"] == "release_execution_ready"
    assert payload["release_execution"]["package_ready"] is True
