from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify-v065-retrieval-learning-release-smoke.py"
spec = importlib.util.spec_from_file_location("verify_v065_retrieval_learning_release_smoke", SCRIPT_PATH)
release_smoke = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release_smoke
assert spec.loader is not None
spec.loader.exec_module(release_smoke)


def _base_payloads() -> dict[str, dict[str, Any]]:
    return {
        "zero_candidate": {
            "ok": True,
            "loss_count": 0,
            "failures": [],
        },
        "shared_candidate_family": {
            "ok": True,
            "ranking": {"hit_at_3": 1.0, "mean_reciprocal_rank": 1.0},
            "failures": [],
        },
        "shared_retrieval_family": {
            "ok": True,
            "ranking": {"hit_at_3": 1.0, "mean_reciprocal_rank": 1.0},
            "failures": [],
        },
        "learning_loop": {
            "ok": True,
            "rows": {
                "manual_search_view_use_without_query": {
                    "query_on_use": False,
                    "rank_before": 2,
                    "rank_after": 1,
                    "sources": ["description", "learning_boost", "lexical"],
                }
            },
            "privacy": {
                "ok": True,
                "raw_query_phrases_absent": True,
            },
            "failures": [],
        },
        "long_run": {
            "ok": True,
            "step_count": 100,
            "phase_count": 10,
            "zero_candidate_losses": 0,
            "negative_controls": {
                "zero_candidate_regression": {"detected": True, "matched_reasons": ["retrieval_zero_candidates"]},
                "no_phase_boundary_requery": {"detected": True, "matched_reasons": ["unexpected_phase_boundary_requery_count"]},
            },
            "privacy": {
                "ok": True,
                "raw_query_phrases_absent": True,
                "absolute_root_absent": True,
            },
            "failures": [],
        },
    }


def _runner(payloads: dict[str, dict[str, Any]], *, returncodes: dict[str, int] | None = None):
    returncodes = returncodes or {}

    def run(spec: Any, extra_args: list[str]) -> dict[str, Any]:
        assert "--json" not in extra_args
        payload = json.loads(json.dumps(payloads[spec.key]))
        return {
            "command": ["python", spec.script, *extra_args, "--json"],
            "returncode": returncodes.get(spec.key, 0),
            "stdout": json.dumps(payload),
            "stderr": "",
            "payload": payload,
        }

    return run


def test_combined_release_smoke_passes_when_all_child_gates_pass() -> None:
    report = release_smoke.build_report(installed_root=None, runner=_runner(_base_payloads()))
    assert report["ok"] is True, json.dumps(report, indent=2)
    assert report["schema_version"] == release_smoke.SCHEMA_VERSION
    assert report["gates"]["zero_candidate"]["loss_count"] == 0
    assert report["gates"]["shared_candidate_family"]["hit_at_3"] == 1.0
    assert report["gates"]["shared_retrieval_family"]["mrr"] == 1.0
    assert report["gates"]["learning_loop"]["manual_search_view_use_without_query"] is True
    assert report["gates"]["long_run"]["negative_controls_all_detected"] is True
    assert report["installed_library"]["checked"] is False
    assert report["failures"] == []


def test_combined_release_smoke_fails_if_zero_candidate_child_reports_loss() -> None:
    payloads = _base_payloads()
    payloads["zero_candidate"]["loss_count"] = 1
    payloads["zero_candidate"]["ok"] = False
    report = release_smoke.build_report(installed_root=None, runner=_runner(payloads))
    assert report["ok"] is False
    assert any(row["reason"] == "zero_candidate_loss_count_nonzero" for row in report["failures"])


def test_combined_release_smoke_fails_if_shared_family_child_reports_failures() -> None:
    payloads = _base_payloads()
    payloads["shared_candidate_family"]["ok"] = False
    payloads["shared_candidate_family"]["failures"] = [{"id": "x", "reason": "shared_family_missing"}]
    report = release_smoke.build_report(installed_root=None, runner=_runner(payloads))
    assert report["ok"] is False
    failure = next(row for row in report["failures"] if row["id"] == "shared_candidate_family")
    assert failure["reason"] == "shared_family_child_failures"
    assert failure["child_failures"][0]["reason"] == "shared_family_missing"


def test_combined_release_smoke_fails_if_learning_loop_misses_manual_no_query_path() -> None:
    payloads = _base_payloads()
    payloads["learning_loop"]["rows"]["manual_search_view_use_without_query"]["query_on_use"] = True
    report = release_smoke.build_report(installed_root=None, runner=_runner(payloads))
    assert report["ok"] is False
    assert any(row["reason"] == "learning_loop_manual_no_query_missing_or_not_boosted" for row in report["failures"])


def test_combined_release_smoke_fails_if_long_run_negative_controls_are_absent() -> None:
    payloads = _base_payloads()
    payloads["long_run"]["negative_controls"] = {
        "zero_candidate_regression": {"detected": False, "matched_reasons": []}
    }
    report = release_smoke.build_report(installed_root=None, runner=_runner(payloads))
    assert report["ok"] is False
    assert any(row["reason"] == "long_run_negative_controls_missing_or_not_detected" for row in report["failures"])


def test_combined_release_smoke_preserves_child_exit_failure_details() -> None:
    payloads = _base_payloads()
    payloads["learning_loop"]["ok"] = False
    payloads["learning_loop"]["failures"] = [{"id": "privacy", "reason": "learning_log_privacy_failure"}]
    report = release_smoke.build_report(
        installed_root=None,
        runner=_runner(payloads, returncodes={"learning_loop": 1}),
    )
    assert report["ok"] is False
    exit_failure = next(row for row in report["failures"] if row["reason"] == "child_gate_exited_nonzero")
    assert exit_failure["id"] == "learning_loop"
    assert exit_failure["child_failures"][0]["reason"] == "learning_log_privacy_failure"


def test_installed_library_smoke_uses_disposable_copy(tmp_path: Path) -> None:
    installed_root = tmp_path / "installed-library"
    installed_root.mkdir()
    (installed_root / "SKILL.md").write_text("stable", encoding="utf-8")
    seen_roots: list[Path] = []

    def runner(spec: Any, extra_args: list[str]) -> dict[str, Any]:
        if "--root" in extra_args:
            seen_roots.append(Path(extra_args[extra_args.index("--root") + 1]))
        return _runner(_base_payloads())(spec, extra_args)

    before = (installed_root / "SKILL.md").read_text(encoding="utf-8")
    report = release_smoke.build_report(installed_root=installed_root, runner=runner)
    after = (installed_root / "SKILL.md").read_text(encoding="utf-8")
    assert report["ok"] is True, json.dumps(report, indent=2)
    assert report["installed_library"]["checked"] is True
    assert report["installed_library"]["mutated"] is False
    assert report["installed_library"]["smoke_root_mode"] == "disposable_copy"
    assert before == after == "stable"
    assert seen_roots
    assert all(root != installed_root for root in seen_roots)
