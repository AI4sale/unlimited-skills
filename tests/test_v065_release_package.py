from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v065_release_package_manifest_and_claim_boundaries() -> None:
    manifest_path = REPO_ROOT / "docs" / "releases" / "v0.6.5-alpha.release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["release"] == "v0.6.5-alpha"
    assert manifest["package_version"] == "0.6.5"
    assert manifest["distribution"] == "retrieval-learning-reliability"
    assert manifest["status"] == "release_execution_ready"
    assert manifest["release_execution"]["package_ready"] is True
    assert manifest["release_execution"]["executed_in_this_pr"] is False
    assert manifest["git"]["tag_status"] == "blocked_until_pypi_upload_clean_install_and_post_publish_verifier"
    assert manifest["held_prs"] == [195]
    assert manifest["excluded_prs"] == [119]
    assert manifest["safety_boundary"]["marketplace_submission"] is False
    assert manifest["safety_boundary"]["hosted_readiness_claim"] is False
    assert manifest["safety_boundary"]["paid_tier_feature_claim"] is False
    assert manifest["safety_boundary"]["exact_money_claim"] is False
    assert manifest["safety_boundary"]["exact_revenue_claim"] is False
    assert manifest["safety_boundary"]["perfect_search_claim"] is False
    assert manifest["safety_boundary"]["top_1_guarantee_claim"] is False

    tracked = {row["number"] for row in manifest["tracked_prs"]}
    assert {228, 229, 230, 231, 232, 233}.issubset(tracked)

    for raw in manifest["release_package_files"] + manifest["verifier_scripts"] + manifest["tests"]:
        assert (REPO_ROOT / raw).exists(), raw

    release_docs = [
        "docs/releases/v0.6.5-alpha.md",
        "docs/releases/v0.6.5-alpha-checklist.md",
        "docs/releases/v0.6.5-alpha-upgrade-notes.md",
        "docs/releases/v0.6.5-alpha-known-issues.md",
        "docs/releases/v0.6.5-alpha-pypi-publishing.md",
        "docs/releases/v0.6.5-personal-verification.md",
        "docs/reports/v0.6.5-release-decision-package.md",
    ]
    text = "\n".join((REPO_ROOT / raw).read_text(encoding="utf-8") for raw in release_docs).lower()

    for required in [
        "unlimited-skills==0.6.5",
        "technical-debt / reliability release",
        "zero-candidate delivery fixed",
        "recall-first candidate delivery",
        "shared candidate family",
        "learning loop repaired",
        "100-step / 10-phase",
        "combined release smoke",
        "python scripts/verify-v065-retrieval-learning-release-smoke.py --json",
        "python scripts/verify-v065-alpha-release-execution.py --json",
        "python scripts/run-v065-alpha-package-smoke.py --json",
        "python scripts/verify-v06-frozen-contracts.py --expected-version 0.6.5 --json",
        "no pypi publish",
        "no tag",
        "no github release",
        "no marketplace",
        "no hosted rollout",
        "no paid-tier work",
        "no exact revenue/money claim",
        "#195",
        "#119",
    ]:
        assert required in text


def test_v065_release_execution_verifier_lightweight(monkeypatch, capsys) -> None:
    verifier_path = REPO_ROOT / "scripts" / "verify-v065-alpha-release-execution.py"
    spec = importlib.util.spec_from_file_location("verify_v065_alpha_release_execution_test", verifier_path)
    assert spec is not None
    assert spec.loader is not None
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)

    monkeypatch.setattr(verifier, "run_json", lambda args, label, **kwargs: {"ok": True, "status_counts": {"pass": 11}, "installed_library": {"mutated": False}})

    rc = verifier.main(["--allow-dirty", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["release"] == "v0.6.5-alpha"
    assert payload["version"] == "0.6.5"
    assert payload["status"] == "passed"
    assert payload["release_smoke"]["ok"] is True
    assert payload["frozen_contracts"]["ok"] is True


def test_v065_package_smoke_report_validation() -> None:
    from scripts.run_v065_alpha_package_smoke import verify_report

    report = {
        "version": "0.6.5",
        "dist": {"wheel": "unlimited_skills-0.6.5-py3-none-any.whl"},
        "clean_install_retrieval_learning": {
            "version_output": "unlimited-skills 0.6.5",
            "suggest_reason_code": "match_found",
            "suggest_candidate_names": ["marketing-campaign", "content-engine"],
            "search_candidate_names": ["marketing-campaign", "content-engine"],
            "search_candidate_sources_present": True,
            "learning_summary_has_effectiveness": True,
        },
        "source_release_gates": {
            "release_smoke_ok": True,
            "learning_loop_ok": True,
            "learning_loop_manual_no_query": True,
        },
    }

    assert verify_report(report, "0.6.5") == []
    report["clean_install_retrieval_learning"]["suggest_candidate_names"] = []
    assert any("suggest smoke" in error for error in verify_report(report, "0.6.5"))
