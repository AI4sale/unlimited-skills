from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify-v065-long-run-retrieval-learning.py"
spec = importlib.util.spec_from_file_location("verify_v065_long_run_retrieval_learning", SCRIPT_PATH)
long_run = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(long_run)


def test_long_run_fixture_has_required_shape() -> None:
    fixture = long_run.load_fixture()
    steps = long_run._all_steps(fixture)
    languages = long_run._phase_language_counts(fixture)
    assert fixture["schema_version"] == "v065-long-run-retrieval-learning-fixture-v1"
    assert len(fixture["phases"]) == 10
    assert len(steps) == 100
    assert languages["en"] > 0
    assert languages["ru"] > 0
    assert languages["mixed"] > 0
    domains = {phase["domain"] for phase in fixture["phases"]}
    assert {
        "linkedin-social-writing",
        "stale-launcher-repair",
        "money-saved-evidence",
        "generic-decoy-tasks",
    } <= domains


def test_long_run_verifier_passes_fixture(tmp_path: Path) -> None:
    report = long_run.build_report(tmp_path / "library")
    assert report["ok"] is True, json.dumps(report, ensure_ascii=False, indent=2)
    assert report["step_count"] == 100
    assert report["phase_count"] == 10
    assert report["zero_candidate_losses"] == 0
    assert report["phase_boundary_requeries"] == 9
    assert report["accepted_rank_lift_cases"] >= 3
    assert report["similar_query_lift_cases"] >= 3
    assert report["cross_language_lift_cases"] >= 1
    assert report["wrong_skill_demotion_cases"] >= 2
    assert report["long_delay_lift_cases"] >= 1
    assert report["manual_filesystem_skill_walk_detected"] is False
    assert report["privacy_ok"] is True


def test_long_run_negative_controls_are_detected() -> None:
    controls = long_run._negative_controls_detected()
    assert controls
    assert {
        "zero_candidate_regression",
        "no_phase_boundary_requery",
        "accepted_feedback_does_not_improve_rank",
        "wrong_feedback_does_not_demote",
        "use_without_query_does_not_correlate",
        "raw_query_leak",
        "manual_skill_directory_walk",
    } <= set(controls)
    for name, result in controls.items():
        assert result["failure_count"] > 0, result
        assert result["matched_reasons"], result
        assert result["detected"] is True, f"{name}: {json.dumps(result, indent=2)}"


def test_long_run_privacy_scan_rejects_raw_query(tmp_path: Path) -> None:
    fixture = long_run.load_fixture()
    root = long_run.build_fixture_library(tmp_path / "library")
    privacy = long_run._scan_privacy(root, fixture, extra_text="write linkedin launch article")
    assert privacy["ok"] is False
    assert "write linkedin launch article" in privacy["leaks"]
