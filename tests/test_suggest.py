from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills import suggest
from unlimited_skills.__main__ import _fast_suggest_argv
from unlimited_skills.search_core import (
    EXPANSION_REVISION,
    INDEX_MANIFEST_NAME,
    INDEX_SCHEMA_VERSION,
    STOPWORD_REVISION,
    TOKENIZER_REVISION,
    SkillHit,
    index_is_current,
    load_records,
    save_index,
    score_skill,
)


def write_skill(root: Path, name: str, description: str, body: str = "") -> None:
    skill_dir = root / "local" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    write_skill(root, "python-patterns", "Pythonic idioms, PEP 8 standards, and code review best practices for Python.")
    write_skill(root, "flutter-dart-code-review", "Flutter and Dart code review checklist with widget best practices.")
    write_skill(root, "react-performance", "React re-render performance optimization with memoization.")
    write_skill(root, "gardening-basics", "Watering schedules for houseplants.")
    save_index(root)
    return root


def test_suggest_hits_respects_floor_and_limit(library: Path) -> None:
    hits = suggest.suggest_hits(library, "python code review pep8", limit=3, floor=1.0)
    assert hits
    assert all(hit.score >= 1.0 for hit in hits)
    assert len(hits) <= 3
    assert not suggest.suggest_hits(library, "python code review pep8", limit=3, floor=10_000.0)
    assert not suggest.suggest_hits(library, "", limit=3, floor=0.0)


def test_lexical_index_carries_precomputed_token_sets_for_fast_probe(library: Path) -> None:
    rows = json.loads((library / ".unlimited-skills-index.json").read_text(encoding="utf-8"))
    assert rows
    for key in ("name_tokens", "description_tokens", "body_tokens"):
        assert isinstance(rows[0][key], list)
    assert "search_text" not in rows[0]
    hit, _body = load_records(library)[0]
    assert getattr(hit, "_name_tokens")
    assert isinstance(getattr(hit, "_body_tokens"), frozenset)


def test_lexical_index_manifest_detects_stale_or_corrupt_indexes(library: Path) -> None:
    manifest = json.loads((library / INDEX_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == INDEX_SCHEMA_VERSION
    assert manifest["tokenizer_revision"] == TOKENIZER_REVISION
    assert manifest["stopword_revision"] == STOPWORD_REVISION
    assert manifest["expansion_revision"] == EXPANSION_REVISION
    assert manifest["complete"] is True
    assert index_is_current(library) is True

    skill = library / "local" / "skills" / "python-patterns" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nchanged inventory generation\n", encoding="utf-8")
    assert index_is_current(library) is False
    # Readers fail open to the current filesystem content, never stale tokens.
    records = load_records(library)
    body = next(body for hit, body in records if hit.name == "python-patterns")
    assert "changed inventory generation" in body


def test_suggest_text_output_is_one_line_per_hit(library: Path, capsys: pytest.CaptureFixture) -> None:
    rc = suggest.main(["python code review pep8", "--root", str(library), "--floor", "1"])
    captured = capsys.readouterr()
    assert rc == 0
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert 1 <= len(lines) <= 3
    # name + source + short description only: no absolute paths, no scores.
    assert lines[0].startswith("python-patterns [local] — ")
    assert str(library) not in captured.out
    assert ":\\" not in captured.out and ":/" not in captured.out


def test_suggest_prints_nothing_below_floor_and_exits_zero(library: Path, capsys: pytest.CaptureFixture) -> None:
    rc = suggest.main(["completely unrelated quantum yodeling", "--root", str(library), "--floor", "50"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""


def test_suggest_prints_nothing_for_weak_partial_match_below_floor(
    library: Path, capsys: pytest.CaptureFixture
) -> None:
    # "watering" has a real lexical overlap with gardening-basics, but the
    # score is intentionally below the calibrated delivery floor. The public
    # text contract promises silence for this case, not a weak false-positive.
    rc = suggest.main(["watering", "--root", str(library)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""


def test_suggest_card_mode_keeps_weak_partial_match_at_tier_one(
    library: Path, capsys: pytest.CaptureFixture
) -> None:
    rc = suggest.main(["watering", "--root", str(library), "--json", "--card"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["reason_code"] == "low_confidence_candidates"
    assert payload["top_3_skill_candidates"] == []
    assert payload["retrieval_candidates"]
    assert payload["delivery_tier"] == suggest.TIER_SILENCE
    assert "skill_card" not in payload


def test_card_mode_delivers_recall_safe_name_hint_below_card_floor(
    library: Path, capsys: pytest.CaptureFixture
) -> None:
    for index in range(8):
        write_skill(library, f"decoy-{index}", f"Unrelated fixture topic {index}.")
    save_index(library)
    rc = suggest.main(["python api", "--root", str(library), "--json", "--card"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["reason_code"] == suggest.REASON_LOW_CONFIDENCE
    assert payload["delivery_tier"] == suggest.TIER_HINT
    assert payload["delivery_candidates"][0]["name"] == "python-patterns"
    assert payload["card_candidates"] == []
    assert "skill_card" not in payload


def test_card_mode_rejects_body_only_noise_even_above_hint_floor(
    library: Path, capsys: pytest.CaptureFixture
) -> None:
    write_skill(
        library,
        "unrelated-procedure",
        "A deliberately generic fixture.",
        body="quasar nebula comet galaxy orbit telescope astronomy",
    )
    save_index(library)
    rc = suggest.main(
        ["quasar nebula comet galaxy orbit telescope astronomy", "--root", str(library), "--json", "--card"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["top_3_skill_candidates"] == []
    assert payload["retrieval_candidates"]
    assert payload["delivery_candidates"] == []
    assert payload["delivery_tier"] == suggest.TIER_SILENCE


def test_hint_predicate_requires_discriminative_description_evidence(
    library: Path, capsys: pytest.CaptureFixture
) -> None:
    write_skill(library, "single-description-hit", "Quasar workflow guidance.")
    write_skill(library, "double-description-hit", "Quasar nebula workflow guidance.")
    for index in range(8):
        write_skill(library, f"generic-decoy-{index}", f"Generic fixture {index}.")
    save_index(library)

    suggest.main(["quasar nebula", "--root", str(library), "--json", "--card"])
    payload = json.loads(capsys.readouterr().out)
    delivered = {row["name"] for row in payload["delivery_candidates"]}
    assert "double-description-hit" in delivered
    assert "single-description-hit" not in delivered


def test_single_generic_name_overlap_does_not_create_ambient_false_positive(
    library: Path, capsys: pytest.CaptureFixture
) -> None:
    write_skill(
        library,
        "plan-orchestrate",
        "Read an implementation plan and orchestrate technical execution.",
    )
    save_index(library)
    suggest.main(
        ["plan a birthday dinner menu for eight guests", "--root", str(library), "--json", "--card"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["retrieval_candidates"]
    assert all(row["name"] != "plan-orchestrate" for row in payload["delivery_candidates"])


def test_description_only_candidate_can_hint_but_never_inject_a_card(
    library: Path, capsys: pytest.CaptureFixture
) -> None:
    write_skill(
        library,
        "workflow-coordinator",
        "Create pull request descriptions and coordinate repository work.",
    )
    save_index(library)
    suggest.main(
        ["create pull request description", "--root", str(library), "--json", "--card", "--high-threshold", "10"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert any(row["name"] == "workflow-coordinator" for row in payload["delivery_candidates"])
    assert payload["delivery_tier"] == suggest.TIER_HINT
    assert "skill_card" not in payload


def test_exact_phrase_expansion_can_qualify_a_safe_name_hint(
    library: Path, capsys: pytest.CaptureFixture
) -> None:
    write_skill(
        library,
        "github-ops",
        "GitHub repository operations and PR management.",
    )
    save_index(library)
    suggest.main(
        ["create pull request description", "--root", str(library), "--json", "--card"]
    )
    payload = json.loads(capsys.readouterr().out)
    github = next(row for row in payload["delivery_candidates"] if row["name"] == "github-ops")
    assert github["phrase_overlap_count"] >= 1
    assert "query_expansion" in github["candidate_sources"]
    assert payload["delivery_tier"] == suggest.TIER_HINT


def test_vector_rank_can_hint_but_never_qualifies_a_card() -> None:
    strong = SkillHit("semantic-strong", "fixture", "local", "unused", score=32.0)
    setattr(strong, "lexical_score", 3.0)
    setattr(strong, "vector_score", 0.56)
    setattr(strong, "vector_rank", 1)
    weak = SkillHit("semantic-weak", "fixture", "local", "unused", score=31.0)
    setattr(weak, "lexical_score", 3.0)
    setattr(weak, "vector_score", 0.36)
    setattr(weak, "vector_rank", 2)

    hints = suggest.recall_safe_hint_hits([strong, weak], "unrelated task")
    assert [hit.name for hit in hints] == ["semantic-strong"]
    assert suggest.card_safe_hits(
        hints, query="semantic strong task", floor=12.0, mixed_language_uncertain=False
    ) == []


def test_card_schema_v2_logs_retrieved_shown_and_card_surfaces_separately(
    library: Path, capsys: pytest.CaptureFixture
) -> None:
    write_skill(
        library,
        "body-only-diagnostic",
        "Generic fixture.",
        body="python pep8 review idioms module",
    )
    save_index(library)
    suggest.main(
        ["python code review pep8", "--root", str(library), "--json", "--card", "--high-threshold", "10"]
    )
    payload = json.loads(capsys.readouterr().out)
    event = json.loads((library / ".learning" / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    event_payload = event["payload"]

    assert payload["schema_version"] == 2
    assert payload["top_3_skill_candidates"] == payload["delivery_candidates"]
    assert event_payload["retrieved_candidates"]
    assert event_payload["shown_candidates"]
    assert set(event_payload["shown_candidates"]) <= set(event_payload["retrieved_candidates"])
    assert event_payload["card_injected_candidate"] in event_payload["shown_candidates"]


def test_suggest_json_contract_is_privacy_hardened(library: Path, capsys: pytest.CaptureFixture) -> None:
    query = "python code review pep8"
    rc = suggest.main([query, "--root", str(library), "--floor", "1", "--json"])
    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert rc == 0
    # ONLY the contract keys — no query echo, no paths, no bodies.
    assert set(payload) == {"task_summary_hash", "top_3_skill_candidates", "reason_code", "recommended_next_action", "latency_ms"}
    assert payload["task_summary_hash"] == suggest.task_summary_hash(query)
    assert query not in raw
    assert str(library) not in raw and ":\\" not in raw
    assert payload["reason_code"] == "match_found"
    assert payload["recommended_next_action"] == "unlimited-skills view python-patterns"
    assert isinstance(payload["latency_ms"], (int, float))
    candidates = payload["top_3_skill_candidates"]
    assert candidates and len(candidates) <= 3
    for candidate in candidates:
        assert set(candidate) == {"name", "source", "score"}
    assert candidates[0]["name"] == "python-patterns"
    assert candidates[0]["source"] == "local"
    assert candidates[0]["score"] >= 1


def test_suggest_json_reason_codes(library: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = suggest.main(["quantum yodeling", "--root", str(library), "--floor", "50", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["top_3_skill_candidates"] == []
    assert payload["reason_code"] == "below_floor"
    assert "proceed with the task" in payload["recommended_next_action"]

    rc = suggest.main(["python code review", "--root", str(tmp_path / "nope"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["top_3_skill_candidates"] == []
    assert payload["reason_code"] == "empty_library"


def test_task_summary_hash_normalizes_and_never_echoes() -> None:
    assert suggest.task_summary_hash("Fix  My   Bug") == suggest.task_summary_hash("fix my bug")
    digest = suggest.task_summary_hash("fix my bug")
    assert len(digest) == 12
    assert all(char in "0123456789abcdef" for char in digest)


def test_suggest_logs_event_best_effort(library: Path, capsys: pytest.CaptureFixture) -> None:
    suggest.main(["python code review pep8", "--root", str(library), "--floor", "1"])
    capsys.readouterr()
    log = library / ".learning" / "events.jsonl"
    assert log.is_file()
    event = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "suggest"
    assert event["payload"]["hits"][0]["name"] == "python-patterns"


def test_suggest_survives_unwritable_event_log(library: Path, capsys: pytest.CaptureFixture) -> None:
    # .learning exists as a FILE -> log_event raises OSError -> still exit 0.
    (library / ".learning").write_text("not a directory", encoding="utf-8")
    rc = suggest.main(["python code review pep8", "--root", str(library), "--floor", "1"])
    assert rc == 0
    assert "python-patterns" in capsys.readouterr().out


def test_suggest_survives_missing_root(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = suggest.main(["python code review", "--root", str(tmp_path / "nope")])
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_ecosystem_guard_demotes_wrong_ecosystem_top_hit(library: Path) -> None:
    hits = suggest.suggest_hits(library, "python idiomatic code review pep8", limit=3, floor=1.0)
    assert hits[0].name == "python-patterns"
    flutter = [hit for hit in hits if hit.name == "flutter-dart-code-review"]
    python = [hit for hit in hits if hit.name == "python-patterns"]
    assert python and (not flutter or flutter[0].score < python[0].score)


def test_score_skill_applies_wrong_ecosystem_penalty() -> None:
    hit = SkillHit(name="flutter-dart-code-review", description="Flutter and Dart code review checklist.", collection="local", path="x")
    neutral = score_skill("code review checklist", hit, "")
    wrong = score_skill("python code review checklist", hit, "")
    assert wrong < neutral


def test_fast_dispatch_routes_only_plain_suggest_calls() -> None:
    assert _fast_suggest_argv(["suggest", "fix bug"]) == ["fix bug"]
    assert _fast_suggest_argv(["--root", "r", "suggest", "fix bug", "--json"]) == ["fix bug", "--json", "--root", "r"]
    assert _fast_suggest_argv(["search", "fix bug"]) is None
    assert _fast_suggest_argv(["--version"]) is None
    assert _fast_suggest_argv([]) is None


# --- F3b ambient injection: tier selection and skill cards ---------------


def scored_hit(score: float, name: str = "skill-x", path: str = "") -> SkillHit:
    return SkillHit(name=name, description="desc", collection="local", path=path, score=score)


def test_select_tier_boundaries() -> None:
    # Tier 1: nothing above the floor.
    assert suggest.select_tier([]) == suggest.TIER_SILENCE
    # Tier 2: below the high threshold (18.0).
    assert suggest.select_tier([scored_hit(17.9)]) == suggest.TIER_HINT
    assert suggest.select_tier([scored_hit(12.0)]) == suggest.TIER_HINT
    # Tier 3: at/above the threshold with no runner-up.
    assert suggest.select_tier([scored_hit(18.0)]) == suggest.TIER_CARD
    # Margin: top must be >= 1.5x the runner-up.
    assert suggest.select_tier([scored_hit(18.0), scored_hit(12.1)]) == suggest.TIER_HINT  # 18 < 1.5*12.1
    assert suggest.select_tier([scored_hit(27.0), scored_hit(18.0)]) == suggest.TIER_CARD  # exactly 1.5x
    assert suggest.select_tier([scored_hit(26.9), scored_hit(18.0)]) == suggest.TIER_HINT
    # Runner-up below the floor does not block the card.
    assert suggest.select_tier([scored_hit(20.0), scored_hit(11.0)]) == suggest.TIER_CARD
    # Custom threshold/margin parameters are honored.
    assert suggest.select_tier([scored_hit(10.0)], high_threshold=10.0) == suggest.TIER_CARD
    assert suggest.select_tier([scored_hit(16.0), scored_hit(12.0)], floor=12.0, high_threshold=10.0, margin=1.2) == suggest.TIER_CARD


def card_hit(root: Path, name: str) -> SkillHit:
    path = root / "local" / "skills" / name / "SKILL.md"
    return SkillHit(name=name, description="fixture desc", collection="local", path=str(path), score=30.0)


def test_build_skill_card_contents_and_footer(library: Path) -> None:
    write_skill(library, "card-skill", "When the task needs the card fixture.", body="Step 1: do the thing.\nStep 2: verify it.")
    hit = card_hit(library, "card-skill")
    card = suggest.build_skill_card(hit)
    assert card is not None
    assert card.startswith("Skill card: card-skill (source: local)")
    assert "When to use: When the task needs the card fixture." in card
    assert "Step 1: do the thing." in card
    assert card.rstrip().endswith("Full skill body: unlimited-skills view card-skill")
    assert "(card truncated" not in card  # fits: no truncation note
    # Never any local path — not even the skill's own.
    assert str(library) not in card
    assert ":\\" not in card and ":/" not in card


def test_build_skill_card_truncates_keeping_head(library: Path) -> None:
    body = "PROCEDURE-HEAD first line.\n" + ("filler line\n" * 600)
    write_skill(library, "long-skill", "Long body fixture.", body=body)
    hit = card_hit(library, "long-skill")
    card = suggest.build_skill_card(hit, max_chars=500)
    assert card is not None
    assert len(card) <= 500
    assert "PROCEDURE-HEAD first line." in card  # head of the body survives
    assert "(card truncated — full skill: unlimited-skills view long-skill)" in card
    assert card.rstrip().endswith("Full skill body: unlimited-skills view long-skill")
    # Default cap is the documented constant.
    full = suggest.build_skill_card(hit)
    assert full is not None and len(full) <= suggest.CARD_MAX_CHARS


def test_build_skill_card_fails_open(library: Path) -> None:
    missing = SkillHit(name="ghost", description="", collection="local", path=str(library / "nope" / "SKILL.md"), score=30.0)
    assert suggest.build_skill_card(missing) is None
    # Pathological cap with no room even for the header/footer.
    write_skill(library, "tiny-cap", "Cap fixture.", body="body")
    assert suggest.build_skill_card(card_hit(library, "tiny-cap"), max_chars=10) is None


def test_suggest_json_card_mode_injects_at_high_confidence(library: Path, capsys: pytest.CaptureFixture) -> None:
    query = "python code review pep8"
    rc = suggest.main([query, "--root", str(library), "--floor", "1", "--json", "--card", "--high-threshold", "10"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["delivery_tier"] == 3
    card = payload["skill_card"]
    assert set(card) == {"name", "source", "card"}
    assert card["name"] == "python-patterns"
    assert card["source"] == "local"
    assert card["card"].startswith("Skill card: python-patterns (source: local)")
    assert "unlimited-skills view python-patterns" in card["card"]
    # The card never echoes the query and never carries local paths.
    assert query not in card["card"]
    assert str(library) not in card["card"]
    assert ":\\" not in card["card"] and ":/" not in card["card"]
    # The base contract keys are unchanged alongside the card fields
    # (retrieval_path/vector_status are added on the --card channel; see language-routing tests).
    assert set(payload) == {"task_summary_hash", "top_3_skill_candidates", "reason_code", "recommended_next_action", "latency_ms", "schema_version", "delivery_tier", "skill_card", "retrieval_path", "vector_status", "minimum_score", "hint_policy_revision", "hint_minimum_score", "retrieval_candidates", "delivery_candidates", "card_candidates", "delivery"}
    assert payload["retrieval_path"] == "lexical"
    assert payload["vector_status"] == "not_requested"
    assert payload["minimum_score"] == 1
    assert payload["hint_minimum_score"] == suggest.HINT_FLOOR
    assert payload["delivery_candidates"]
    assert payload["card_candidates"]
    assert payload["top_3_skill_candidates"] == payload["delivery_candidates"]
    assert payload["delivery"]["mode"] == "card"


def test_suggest_card_mode_degrades_to_hint_without_confidence_or_margin(library: Path, capsys: pytest.CaptureFixture) -> None:
    query = "python code review pep8"
    # Below the high threshold -> tier 2 (default threshold 18 > fixture score).
    rc = suggest.main([query, "--root", str(library), "--floor", "1", "--json", "--card"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["delivery_tier"] == 2
    assert "skill_card" not in payload
    # Confident top but insufficient margin over the runner-up -> tier 2.
    rc = suggest.main([query, "--root", str(library), "--floor", "1", "--json", "--card", "--high-threshold", "10", "--high-margin", "5"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["delivery_tier"] == 2
    assert "skill_card" not in payload


def test_suggest_card_margin_uses_runner_up_even_with_limit_one(library: Path, capsys: pytest.CaptureFixture) -> None:
    # The hook calls --limit 1; the margin check must still see candidate #2.
    rc = suggest.main(["python code review pep8", "--root", str(library), "--floor", "1", "--json", "--card", "--limit", "1", "--high-threshold", "10", "--high-margin", "5"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert len(payload["top_3_skill_candidates"]) == 1
    assert len(payload["delivery_candidates"]) == 1
    assert payload["delivery_tier"] == 2  # blocked by the runner-up margin
    assert "skill_card" not in payload


def test_suggest_card_kill_switch_downgrades_to_tier_two(library: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(suggest.KILL_SWITCH_ENV, "1")
    rc = suggest.main(["python code review pep8", "--root", str(library), "--floor", "1", "--json", "--card", "--high-threshold", "10"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["delivery_tier"] == 2
    assert "skill_card" not in payload


def test_suggest_card_invalidates_index_when_skill_file_disappears(library: Path, capsys: pytest.CaptureFixture) -> None:
    (library / "local" / "skills" / "python-patterns" / "SKILL.md").unlink()
    rc = suggest.main(["python code review pep8", "--root", str(library), "--floor", "1", "--json", "--card", "--high-threshold", "10"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["delivery_tier"] in {suggest.TIER_SILENCE, suggest.TIER_HINT}
    assert "skill_card" not in payload
    assert all(candidate["name"] != "python-patterns" for candidate in payload["top_3_skill_candidates"])
    assert all(candidate["name"] != "python-patterns" for candidate in payload["delivery_candidates"])


def test_suggest_default_json_has_no_card_fields(library: Path, capsys: pytest.CaptureFixture) -> None:
    rc = suggest.main(["python code review pep8", "--root", str(library), "--floor", "1", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "delivery_tier" not in payload
    assert "skill_card" not in payload
