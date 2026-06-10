from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_runner():
    path = ROOT / "scripts" / "run-v040-alpha-e01-e04-cross-repo-e2e.py"
    spec = importlib.util.spec_from_file_location("v040_alpha_e01_e04", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v040_alpha_e01_e04_fixture_mode(tmp_path: Path) -> None:
    runner = load_runner()

    report = runner.build_report(mode="fixture", registry_repo=None, temp_home=True)

    assert report["status"] == "passed"
    assert report["release"] == "v0.4.0-alpha"
    assert report["mode"] == "fixture"
    assert report["checks"]["E01_policy_aware_recommendation_preview"] is True
    assert report["checks"]["E02_eval_release_operator_workflow"] is True
    assert report["checks"]["E03_maintainer_queue_runtime_and_public_status"] is True
    assert report["checks"]["E04_governance_dashboard_signed_summary"] is True
    assert report["checks"]["no_automatic_install_update_remove"] is True
    assert report["checks"]["no_automatic_rewrite"] is True
    assert report["checks"]["no_auto_publish"] is True
    assert report["checks"]["no_production_hosted_calls"] is True
    assert report["checks"]["no_private_registry_content_in_public_repo"] is True
    assert report["release_boundary"]["final_tag_created"] is False
    assert report["release_boundary"]["task3_publication_gate_required"] is True
    assert report["public_client"]["E01_policy_aware_recommendation_preview"]["preview_only"] is True
    assert report["public_client"]["E03_public_maintainer_queue_client"]["metadata_only"] is True
    assert report["registry"]["E03_maintainer_queue_runtime_api"]["mutates_queue"] is False
    assert report["registry"]["E04_governance_dashboard_summary_api"]["admin_console_read_only"] is True

    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    runner.write_report(report, out_json=out_json, out_md=out_md)
    assert json.loads(out_json.read_text(encoding="utf-8"))["status"] == "passed"
    assert "alpha integration gate" in out_md.read_text(encoding="utf-8")


def test_v040_alpha_e01_e04_external_registry_mode_when_available() -> None:
    registry_repo = ROOT.parent / "unlimited-skills-registry-cleanup"
    if not (registry_repo / "scripts" / "validate-governance-dashboard-summary.py").is_file():
        pytest.skip("local private registry checkout with E04 is not available")

    runner = load_runner()
    report = runner.build_report(mode="external-local-registry", registry_repo=registry_repo, temp_home=True)

    assert report["status"] == "passed"
    assert report["mode"] == "external-local-registry"
    assert report["registry"]["E02_eval_release_operator_workflow"]["release_owner_decides"] is True
    assert report["registry"]["E03_maintainer_queue_runtime_api"]["metadata_only"] is True
    assert report["registry"]["E03_maintainer_queue_runtime_api"]["mutates_queue"] is False
    assert report["registry"]["E04_governance_dashboard_summary_api"]["mutates_policies"] is False
    assert report["registry"]["E04_governance_dashboard_summary_api"]["mutates_private_packs"] is False


def test_v040_alpha_e01_e04_verifier_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/verify-v040-alpha-e01-e04.py"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "v0.4.0-alpha E01-E04 integration verification passed" in completed.stdout
