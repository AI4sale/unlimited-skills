from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from unlimited_skills import cli
from unlimited_skills import suggest
from unlimited_skills.search_core import SkillHit, candidate_debug_payload, candidate_sources, event_safe_payload, shared_candidate_family, write_jsonl

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify-v065-shared-candidate-family.py"
spec = importlib.util.spec_from_file_location("verify_v065_shared_candidate_family", SCRIPT_PATH)
shared_family = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(shared_family)


def test_shared_candidate_family_verifier_passes_fixture(tmp_path: Path) -> None:
    root = shared_family.zero_gate.build_fixture_library(tmp_path / "library")
    report = shared_family.build_report(root, read_only_root=False)
    assert report["ok"] is True, json.dumps(report, ensure_ascii=False, indent=2)
    assert report["ranking"]["hit_at_3"] == 1.0
    assert report["ranking"]["mean_reciprocal_rank"] > 0
    assert report["learning_lift"]["target_has_learning_boost_source"] is True
    assert report["learning_lift"]["rank_improved"] is True


def test_suggest_card_candidates_expose_shared_sources(tmp_path: Path, capsys) -> None:
    root = shared_family.zero_gate.build_fixture_library(tmp_path / "library")
    rc = suggest.main(["write LinkedIn post", "--root", str(root), "--json", "--card", "--limit", "3"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    candidates = payload["top_3_skill_candidates"]
    assert candidates
    assert all(candidate.get("candidate_sources") for candidate in candidates)
    assert {candidate["name"] for candidate in candidates} <= {
        hit.name for hit in shared_candidate_family(root, "write LinkedIn post", 10)
    }
    assert all("candidate_rank" in candidate for candidate in candidates)
    assert all("confidence" in candidate for candidate in candidates)
    assert payload["vector_status"] == "not_requested"


def test_search_json_exposes_comparable_candidate_sources(tmp_path: Path, capsys) -> None:
    root = shared_family.zero_gate.build_fixture_library(tmp_path / "library")
    rc = cli.main(
        [
            "--root",
            str(root),
            "search",
            "write LinkedIn post",
            "--mode",
            "hybrid",
            "--json",
            "--limit",
            "3",
            "--no-native-sync",
        ]
    )
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows
    assert all(row.get("candidate_sources") for row in rows)
    assert all("candidate_rank" in row for row in rows)
    assert all("confidence" in row for row in rows)


def test_vector_only_fixture_reaches_suggest_and_hook(tmp_path: Path) -> None:
    report = shared_family._vector_only_probe(tmp_path)
    assert report["ok"] is True, json.dumps(report, ensure_ascii=False, indent=2)
    assert report["target"] not in report["lexical_top"]
    assert report["vector_top"][0] == report["target"]
    assert report["target"] in report["hybrid_top"][:3]
    assert report["target"] in report["suggest_top"]
    assert report["target"] in report["hook_candidates"]
    assert report["suggest_vector_status"] == "available_used"
    assert "vector" in report["target_suggest_sources"]
    assert "vector" in report["target_search_sources"]


def test_learning_feedback_marks_boost_without_new_search_path(tmp_path: Path) -> None:
    root = shared_family.zero_gate.build_fixture_library(tmp_path / "library")
    query = "write LinkedIn post"
    before = [hit.name for hit in shared_candidate_family(root, query, 5)]
    assert "content-engine" in before
    for _index in range(2):
        write_jsonl(
            root / ".learning" / "feedback.jsonl",
            event_safe_payload(root, "feedback", {"name": "content-engine", "query": query, "verdict": "accepted"}),
        )
    after = shared_candidate_family(root, query, 5)
    after_names = [hit.name for hit in after]
    boosted = next(hit for hit in after if hit.name == "content-engine")
    assert "learning_boost" in candidate_sources(boosted)
    assert after_names.index("content-engine") < before.index("content-engine")


def test_rrf_uses_ranks_not_raw_vector_score_scale(tmp_path: Path) -> None:
    root = shared_family.zero_gate.build_fixture_library(tmp_path / "library")
    query = "write LinkedIn post"
    paths = {hit.name: hit.path for hit in shared_candidate_family(root, query, 10)}

    def vectors(scale: float) -> list[SkillHit]:
        return [
            SkillHit("content-engine", "fixture", "ecc", paths["content-engine"], 0.9 * scale),
            SkillHit("social-publisher", "fixture", "ecc", paths["social-publisher"], 0.6 * scale),
        ]

    normal = shared_candidate_family(root, query, 5, vector_hits=vectors(1.0))
    rescaled = shared_candidate_family(root, query, 5, vector_hits=vectors(100.0))
    assert [hit.name for hit in normal] == [hit.name for hit in rescaled]
    assert [round(hit.score, 6) for hit in normal] == [round(hit.score, 6) for hit in rescaled]
    assert all(candidate_debug_payload(hit)["fusion_method"] == "rrf" for hit in normal)


def test_query_expansion_never_claims_exact_skill_identity(tmp_path: Path) -> None:
    root = shared_family.zero_gate.build_fixture_library(tmp_path / "library")
    hits = shared_candidate_family(root, "create social media content", 5)
    marketing = next(hit for hit in hits if hit.name == "marketing-campaign")
    evidence = candidate_debug_payload(marketing)
    assert "query_expansion" in evidence["candidate_sources"]
    assert evidence["exact_match"] is False
