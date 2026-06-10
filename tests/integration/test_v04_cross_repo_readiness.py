from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_runner():
    path = ROOT / "scripts" / "run-v04-cross-repo-readiness-suite.py"
    spec = importlib.util.spec_from_file_location("v04_cross_repo_readiness", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v04_cross_repo_readiness_fixture_mode(tmp_path: Path) -> None:
    runner = load_runner()

    report = runner.build_report(mode="fixture", registry_repo=None, temp_home=True)

    assert report["status"] == "passed"
    assert report["mode"] == "fixture"
    assert report["implementation_approval"]["approved"] is False
    assert set(report["blocker_closure_inputs"]) == {"B-01", "B-02", "B-03", "B-04"}
    assert report["checks"]["signed_skillops_metadata_contract"] is True
    assert report["checks"]["unsigned_metadata_rejection"] is True
    assert report["checks"]["forbidden_field_rejection"] is True
    assert report["checks"]["policy_aware_recommendation_refusal_codes"] is True
    assert report["checks"]["eval_release_gate_outcomes"] is True
    assert report["checks"]["maintainer_queue_transitions"] is True
    assert report["checks"]["skill_improvement_workflow"] is True
    assert report["checks"]["support_bundle_redaction"] is True
    assert report["checks"]["no_automatic_install_update_remove"] is True
    assert report["checks"]["no_automatic_skill_rewriting"] is True
    assert report["checks"]["no_auto_publish"] is True
    assert report["checks"]["no_production_hosted_calls"] is True
    assert report["checks"]["no_production_signing_key_required"] is True
    assert report["checks"]["no_live_billing"] is True
    assert report["checks"]["no_pypi"] is True
    assert report["checks"]["no_full_catalog_distribution"] is True
    assert report["public_client"]["skill_improvement_e2e"]["update_recommendations_preview_only"] is True
    assert report["public_client"]["skill_improvement_e2e"]["update_preview_will_update"] is False

    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    runner.write_report(report, out_json=out_json, out_md=out_md)
    assert json.loads(out_json.read_text(encoding="utf-8"))["status"] == "passed"
    assert "technical readiness evidence only" in out_md.read_text(encoding="utf-8")


def test_v04_cross_repo_readiness_external_registry_mode_when_available() -> None:
    registry_repo = ROOT.parent / "unlimited-skills-registry-cleanup"
    if not (registry_repo / "scripts" / "validate-skillops-contracts.py").is_file():
        pytest.skip("local private registry checkout is not available")

    runner = load_runner()
    report = runner.build_report(mode="external-local-registry", registry_repo=registry_repo, temp_home=True)

    assert report["status"] == "passed"
    assert report["mode"] == "external-local-registry"
    assert report["registry"]["skillops_contracts"]["unsigned_rejection"] is True
    assert report["registry"]["skillops_contracts"]["forbidden_field_rejection"] is True
    assert "rollback_recommended" in report["registry"]["eval_release_gates"]["covered_outcomes"]
    assert report["registry"]["maintainer_queue"]["automatic_skill_rewrite"] is False
    assert report["registry"]["maintainer_queue"]["auto_publish"] is False


def test_v04_cross_repo_readiness_verifier_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/verify-v04-cross-repo-readiness.py"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "v0.4 cross-repo readiness verification passed" in completed.stdout
