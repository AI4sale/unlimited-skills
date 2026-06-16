from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v064_release_package_manifest_and_claim_boundaries() -> None:
    manifest_path = REPO_ROOT / "docs" / "releases" / "v0.6.4-alpha.release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["release"] == "v0.6.4-alpha"
    assert manifest["package_version"] == "0.6.4"
    assert manifest["status"] == "release_execution_ready"
    assert manifest["release_execution"]["package_ready"] is True
    assert manifest["release_execution"]["executed_in_this_pr"] is False
    assert manifest["git"]["tag_status"] == "blocked_until_pypi_upload_clean_install_and_post_publish_verifier"
    assert manifest["held_prs"] == [195]
    assert manifest["excluded_prs"] == [119]
    assert manifest["safety_boundary"]["exact_money_claim"] is False
    assert manifest["safety_boundary"]["exact_token_claim"] is False
    assert manifest["safety_boundary"]["guaranteed_bill_reduction_claim"] is False

    tracked = {row["number"] for row in manifest["tracked_prs"]}
    assert {210, 211, 212, 213, 214}.issubset(tracked)

    for raw in manifest["release_package_files"] + manifest["verifier_scripts"] + manifest["tests"]:
        assert (REPO_ROOT / raw).exists(), raw

    release_docs = [
        "docs/releases/v0.6.4-alpha.md",
        "docs/releases/v0.6.4-alpha-checklist.md",
        "docs/releases/v0.6.4-alpha-upgrade-notes.md",
        "docs/releases/v0.6.4-alpha-known-issues.md",
        "docs/releases/v0.6.4-alpha-pypi-publishing.md",
        "docs/releases/v0.6.4-personal-verification.md",
        "docs/reports/v0.6.4-release-decision-package.md",
    ]
    text = "\n".join((REPO_ROOT / raw).read_text(encoding="utf-8") for raw in release_docs).lower()

    for required in [
        "unlimited-skills==0.6.4",
        "unlimited-skills money-saved meter",
        "unlimited-skills money-saved registered-export",
        "unlimited-skills money-saved team-rollup",
        "unlimited-skills money-saved admin-export",
        "unlimited-skills money-saved evidence-pack",
        "unlimited-skills money-saved verify-evidence-pack",
        "python scripts/verify-v064-money-saved-tier-smoke.py --json",
        "python scripts/run-v064-alpha-package-smoke.py --json",
        "python scripts/verify-v064-alpha-release-execution.py --json",
        "no exact money",
        "no exact token",
        "no guaranteed bill reduction",
        "no hosted dashboard",
        "#195",
        "#119",
    ]:
        assert required in text


def test_v064_release_execution_verifier_lightweight(monkeypatch, capsys) -> None:
    verifier_path = REPO_ROOT / "scripts" / "verify-v064-alpha-release-execution.py"
    spec = importlib.util.spec_from_file_location("verify_v064_alpha_release_execution_test", verifier_path)
    assert spec is not None
    assert spec.loader is not None
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)

    monkeypatch.setattr(verifier, "run_frozen_contracts", lambda: {"ok": True, "status_counts": {"pass": 11}})
    monkeypatch.setattr(verifier, "run_tier_smoke", lambda: {"ok": True})

    rc = verifier.main(["--allow-dirty", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["release"] == "v0.6.4-alpha"
    assert payload["version"] == "0.6.4"
    assert payload["manifest_status"] == "release_execution_ready"
    assert payload["release_execution"]["package_ready"] is True
    assert payload["tier_smoke"]["ok"] is True


def test_v064_package_smoke_report_validation() -> None:
    from scripts.run_v064_alpha_package_smoke import verify_report

    report = {
        "version": "0.6.4",
        "dist": {"wheel": "unlimited_skills-0.6.4-py3-none-any.whl"},
        "clean_install_money_saved_tiers": {
            "version_output": "unlimited-skills 0.6.4",
            "free_report_written": True,
            "registered_export_written": True,
            "team_rollup_written": True,
            "business_json_written": True,
            "business_csv_written": True,
            "enterprise_manifest_written": True,
            "enterprise_privacy_proof_written": True,
            "enterprise_measurement_proof_written": True,
            "enterprise_claim_boundary_proof_written": True,
            "enterprise_verify_ok": True,
            "enterprise_tamper_returncode": 1,
            "enterprise_tamper_ok": False,
        },
    }

    assert verify_report(report) == []
    report["clean_install_money_saved_tiers"]["enterprise_tamper_ok"] = True
    assert any("tamper check" in error for error in verify_report(report))
