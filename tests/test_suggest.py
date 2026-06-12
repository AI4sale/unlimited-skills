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
    assert lines[0].startswith("python-patterns — ")
    assert lines[0].rstrip().endswith(")")


def test_suggest_prints_nothing_below_floor_and_exits_zero(library: Path, capsys: pytest.CaptureFixture) -> None:
    rc = suggest.main(["completely unrelated quantum yodeling", "--root", str(library), "--floor", "50"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""


def test_suggest_json_contract(library: Path, capsys: pytest.CaptureFixture) -> None:
    rc = suggest.main(["python code review pep8", "--root", str(library), "--floor", "1", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(payload, list) and payload
    assert {"name", "description", "collection", "path", "score"} <= set(payload[0])

    rc = suggest.main(["quantum yodeling", "--root", str(library), "--floor", "50", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


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
