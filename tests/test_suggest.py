from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills import suggest
from unlimited_skills.__main__ import _fast_suggest_argv
from unlimited_skills.search_core import save_index, score_skill, SkillHit


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
    # (retrieval_path is added on the --card channel; see language-routing tests).
    assert set(payload) == {"task_summary_hash", "top_3_skill_candidates", "reason_code", "recommended_next_action", "latency_ms", "delivery_tier", "skill_card", "retrieval_path"}
    assert payload["retrieval_path"] == "lexical"


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
    assert payload["delivery_tier"] == 2  # blocked by the runner-up margin
    assert "skill_card" not in payload


def test_suggest_card_kill_switch_downgrades_to_tier_two(library: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(suggest.KILL_SWITCH_ENV, "1")
    rc = suggest.main(["python code review pep8", "--root", str(library), "--floor", "1", "--json", "--card", "--high-threshold", "10"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["delivery_tier"] == 2
    assert "skill_card" not in payload


def test_suggest_card_degrades_on_unreadable_skill_file(library: Path, capsys: pytest.CaptureFixture) -> None:
    # The index still scores the skill, but its SKILL.md is gone: fail open to tier 2.
    (library / "local" / "skills" / "python-patterns" / "SKILL.md").unlink()
    rc = suggest.main(["python code review pep8", "--root", str(library), "--floor", "1", "--json", "--card", "--high-threshold", "10"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["delivery_tier"] == 2
    assert "skill_card" not in payload
    assert payload["top_3_skill_candidates"][0]["name"] == "python-patterns"


def test_suggest_default_json_has_no_card_fields(library: Path, capsys: pytest.CaptureFixture) -> None:
    rc = suggest.main(["python code review pep8", "--root", str(library), "--floor", "1", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "delivery_tier" not in payload
    assert "skill_card" not in payload
