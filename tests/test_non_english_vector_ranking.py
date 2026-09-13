from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills import suggest
from unlimited_skills.search_core import SkillHit, candidate_debug_payload, save_index, shared_candidate_family


@pytest.fixture
def wordpress_library(tmp_path: Path) -> tuple[Path, dict[str, SkillHit]]:
    root = tmp_path / "library"
    names = ["wp-abilities-verify", "wp-blocks", "wp-cache", "wp-debug", "wp-editor", "wp-hooks", "wp-performance"]
    hits = {}
    for name in names:
        path = root / "local" / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(f"---\nname: {name}\ndescription: WordPress workflow.\n---\n", encoding="utf-8")
        hits[name] = SkillHit(name, "WordPress workflow.", "local", str(path))
    save_index(root)
    hits["wp-performance"].score = 0.6374
    hits["wp-abilities-verify"].score = 0.5930
    return root, hits


@pytest.mark.parametrize("query", [
    "проверить производительность WordPress",
    "تحقق من أداء موقع WordPress",
    "检查并优化网站的运行性能 WordPress",
])
def test_non_english_preserves_vector_ranking_despite_lexical_ties(wordpress_library, query):
    root, hits = wordpress_library
    vectors = [hits["wp-performance"], hits["wp-abilities-verify"]]
    result = shared_candidate_family(root, query, 10, vector_hits=iter(reversed(vectors)))
    assert [hit.name for hit in result] == ["wp-performance", "wp-abilities-verify"]
    assert [hit.score for hit in result] == pytest.approx([0.6374, 0.5930])
    assert all(candidate_debug_payload(hit)["fusion_method"] == "vector" for hit in result)


def test_english_keeps_rrf_ranking(wordpress_library):
    root, hits = wordpress_library
    result = shared_candidate_family(root, "check WordPress workflow", 10,
                                     vector_hits=[hits["wp-performance"], hits["wp-abilities-verify"]])
    assert result[0].name == "wp-abilities-verify"
    assert all(candidate_debug_payload(hit)["fusion_method"] == "rrf" for hit in result)


def test_non_english_empty_vectors_keep_lexical_fallback(wordpress_library):
    root, _hits = wordpress_library
    result = shared_candidate_family(root, "проверить производительность WordPress", 3, vector_hits=iter([]))
    assert result
    assert all(candidate_debug_payload(hit)["fusion_method"] == "lexical" for hit in result)


def test_non_english_vectors_respect_collection_and_deduplicate(wordpress_library):
    root, hits = wordpress_library
    target = hits["wp-performance"]
    weaker_copy = SkillHit(target.name, target.description, target.collection, target.path, 0.5)
    outside = SkillHit("outside", "WordPress workflow.", "other", "/outside/SKILL.md", 0.99)
    result = shared_candidate_family(root, "проверить производительность WordPress", 1, collection="local",
                                     vector_hits=[outside, weaker_copy, target])
    assert len(result) == 1
    assert result[0].name == "wp-performance"
    assert result[0].score == pytest.approx(0.6374)


def test_non_english_suggest_limit_one_delivers_vector_winner(wordpress_library, monkeypatch, capsys):
    root, hits = wordpress_library
    monkeypatch.delenv("UNLIMITED_SKILLS_NO_VECTOR_FALLBACK", raising=False)
    monkeypatch.setattr(suggest, "vector_probe", lambda *_args: [hits["wp-performance"], hits["wp-abilities-verify"]])
    assert suggest.main(["проверить производительность WordPress", "--root", str(root), "--json", "--card", "--limit", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["top_3_skill_candidates"][0]["name"] == "wp-performance"
    assert payload["retrieval_path"] == "vector"
    assert payload["reason_code"] == "match_found"
    assert payload["delivery"]["mode"] == "hint"
    assert "skill_card" not in payload
    assert "needs_english_query" not in payload


def test_non_english_weak_vector_does_not_bypass_hint_threshold(wordpress_library, monkeypatch, capsys):
    root, hits = wordpress_library
    hits["wp-performance"].score = 0.49
    monkeypatch.delenv("UNLIMITED_SKILLS_NO_VECTOR_FALLBACK", raising=False)
    monkeypatch.setattr(suggest, "vector_probe", lambda *_args: [hits["wp-performance"]])
    assert suggest.main(["проверить производительность WordPress", "--root", str(root), "--json", "--card", "--limit", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["top_3_skill_candidates"] == []
    assert payload["reason_code"] != "match_found"
    assert payload["needs_english_query"] is True
