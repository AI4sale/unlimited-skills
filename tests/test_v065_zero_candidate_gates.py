from __future__ import annotations

import json
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify-v065-zero-candidate-gates.py"
spec = importlib.util.spec_from_file_location("verify_v065_zero_candidate_gates", SCRIPT_PATH)
gate_audit = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(gate_audit)


def test_zero_candidate_fixture_contains_required_queries() -> None:
    queries = gate_audit.load_fixture()
    ids = {row["id"] for row in queries}
    assert {
        "ru_linkedin_post",
        "en_linkedin_post",
        "ru_linkedin_release_post",
        "en_social_media_content",
        "ru_stale_launcher_upgrade",
        "en_router_inject_refresh",
    } <= ids


def test_zero_candidate_report_shape(tmp_path: Path) -> None:
    root = gate_audit.build_fixture_library(tmp_path / "library")
    report = gate_audit.build_report(root, gate_audit.load_fixture(), tmp_path)
    assert report["query_count"] == 6
    assert report["loss_count"] == 0
    row = next(item for item in report["rows"] if item["id"] == "ru_linkedin_post")
    assert row["library_skill_count"] >= 5
    assert row["english_hybrid_search_top_10"]["hits"]
    assert len(row["suggest_json"]["payload"]["top_3_skill_candidates"]) >= 3
    assert row["hook_candidate_count"] >= 3
    assert row["zero_candidate_loss"] is False
    assert row["insufficient_candidate_delivery"] is False


def test_zero_candidate_audit_invariant_passes(tmp_path: Path) -> None:
    root = gate_audit.build_fixture_library(tmp_path / "library")
    report = gate_audit.build_report(root, gate_audit.load_fixture(), tmp_path)
    assert report["ok"] is True, json.dumps(report, ensure_ascii=False, indent=2)
