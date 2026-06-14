from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills import cli as _cli
from unlimited_skills.search_core import save_index


PRIVATE_NEEDLES = [
    "prompt secret",
    "raw customer task",
    "operator secret note",
    "C:\\Users\\tedja\\private",
    "ghp_secretTOKEN123456",
    "-----BEGIN PRIVATE KEY-----",
]


def write_skill(root: Path, name: str = "python-patterns") -> Path:
    skill = root / "local" / "skills" / name / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        f"---\nname: {name}\ndescription: Python implementation patterns.\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    save_index(root)
    return skill


def payload(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def assert_private_needles_absent(value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    for needle in PRIVATE_NEEDLES:
        assert needle not in text
    assert ":\\" not in text and ":/" not in text


def test_v063_learning_doctor_empty_state_is_helpful(tmp_path: Path, capsys) -> None:
    root = tmp_path / "library"

    assert _cli.main(["--root", str(root), "learning", "doctor"]) == 0

    result = payload(capsys)
    assert result["schema_version"] == 1
    assert result["status"] == "ok"
    assert result["feedback_count"] == 0
    assert result["candidate_count"] == 0
    assert result["message"] == "No learning feedback found yet."
    assert result["privacy"]["local_only"] is True


def test_v063_wrong_missed_rejected_feedback_becomes_private_candidates(tmp_path: Path, capsys) -> None:
    root = tmp_path / "library"
    write_skill(root)

    for verdict in ("wrong", "missed", "rejected"):
        assert (
            _cli.main(
                [
                    "--root",
                    str(root),
                    "feedback",
                    "record",
                    "python-patterns",
                    "--verdict",
                    verdict,
                    "--query",
                    "prompt secret raw customer task C:\\Users\\tedja\\private ghp_secretTOKEN123456",
                    "--notes",
                    "operator secret note -----BEGIN PRIVATE KEY-----",
                ]
            )
            == 0
        )
        capsys.readouterr()

    assert _cli.main(["--root", str(root), "improvement-candidates"]) == 0

    result = payload(capsys)
    assert result["schema_version"] == 1
    assert result["candidate_count"] == 3
    assert {item["candidate_type"] for item in result["candidates"]} == {
        "missed_skill",
        "rejected_suggestion",
        "wrong_skill",
    }
    assert all(item["privacy"]["prompts_included"] is False for item in result["candidates"])
    assert_private_needles_absent(result)


def test_v063_apply_candidate_dry_run_is_non_mutating(tmp_path: Path, capsys) -> None:
    root = tmp_path / "library"
    skill = write_skill(root)
    before = skill.read_text(encoding="utf-8")

    assert _cli.main(["--root", str(root), "feedback", "record", "python-patterns", "--verdict", "wrong"]) == 0
    capsys.readouterr()
    assert _cli.main(["--root", str(root), "improvement-candidates"]) == 0
    candidate_id = payload(capsys)["candidates"][0]["candidate_id"]

    assert _cli.main(["--root", str(root), "apply-candidate", "--dry-run", candidate_id]) == 0

    result = payload(capsys)
    assert result["status"] == "dry_run"
    assert result["written"] is False
    assert result["mutated_files"] == []
    assert "no skill files were modified" in result["message"]
    assert skill.read_text(encoding="utf-8") == before
    assert_private_needles_absent(result)


def test_v063_candidate_serialization_redacts_privacy_unsafe_skill_names(tmp_path: Path, capsys) -> None:
    root = tmp_path / "library"
    unsafe_name = "C:\\Users\\tedja\\private\\SKILL.md"

    assert _cli.main(["--root", str(root), "feedback", "record", unsafe_name, "--verdict", "wrong"]) == 0
    capsys.readouterr()
    assert _cli.main(["--root", str(root), "improvement-candidates"]) == 0

    result = payload(capsys)
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["skill_label"].startswith("skill-")
    assert "skill_name" not in result["candidates"][0]
    assert unsafe_name not in json.dumps(result, ensure_ascii=False)
    assert_private_needles_absent(result)


def test_v063_candidate_serialization_redacts_arbitrary_sensitive_skill_labels(tmp_path: Path, capsys) -> None:
    root = tmp_path / "library"
    private_label = "customer-acme-private-incident"

    assert _cli.main(["--root", str(root), "feedback", "record", private_label, "--verdict", "wrong"]) == 0
    capsys.readouterr()
    assert _cli.main(["--root", str(root), "improvement-candidates"]) == 0

    result = payload(capsys)
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["skill_label"].startswith("skill-")
    assert private_label not in json.dumps(result, ensure_ascii=False)


def test_v063_candidate_id_stays_stable_when_signal_count_changes(tmp_path: Path, capsys) -> None:
    root = tmp_path / "library"
    write_skill(root)

    assert _cli.main(["--root", str(root), "feedback", "record", "python-patterns", "--verdict", "wrong"]) == 0
    capsys.readouterr()
    assert _cli.main(["--root", str(root), "improvement-candidates"]) == 0
    first = payload(capsys)["candidates"][0]

    assert _cli.main(["--root", str(root), "feedback", "record", "python-patterns", "--verdict", "wrong"]) == 0
    capsys.readouterr()
    assert _cli.main(["--root", str(root), "improvement-candidates"]) == 0
    second = payload(capsys)["candidates"][0]

    assert second["candidate_id"] == first["candidate_id"]
    assert second["signal_count"] == 2
    assert _cli.main(["--root", str(root), "apply-candidate", "--dry-run", first["candidate_id"]]) == 0
    assert payload(capsys)["status"] == "dry_run"


def test_v063_feedback_record_missing_verdict_mentions_missed_wrong(tmp_path: Path, capsys) -> None:
    root = tmp_path / "library"

    assert _cli.main(["--root", str(root), "feedback", "record", "python-patterns"]) == 2

    captured = capsys.readouterr()
    assert "accepted|rejected|neutral|missed|wrong" in captured.err


def test_v063_learning_summary_counts_missed_and_wrong(tmp_path: Path, capsys) -> None:
    root = tmp_path / "library"
    write_skill(root)

    for verdict in ("accepted", "rejected", "neutral", "missed", "wrong"):
        assert _cli.main(["--root", str(root), "feedback", "record", "python-patterns", "--verdict", verdict]) == 0
        capsys.readouterr()

    assert _cli.main(["--root", str(root), "learning-summary", "--events", "--json"]) == 0

    result = payload(capsys)
    assert result["feedback"]["python-patterns"] == {
        "accepted": 1,
        "rejected": 1,
        "neutral": 1,
        "missed": 1,
        "wrong": 1,
    }
