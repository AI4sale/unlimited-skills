from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills import cli as _cli
from unlimited_skills.search_core import EVENT_LOG, save_index, task_summary_hash


def write_skill(root: Path, name: str = "privacy-skill") -> Path:
    skill_file = root / "local" / "skills" / name / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(
        (
            "---\n"
            f"name: {name}\n"
            "description: Privacy-safe local diagnostics workflow.\n"
            "---\n\n"
            "# Privacy Skill\n\n"
            "Keep local event logs privacy-safe.\n"
        ),
        encoding="utf-8",
    )
    save_index(root)
    return skill_file


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def assert_no_private_needles(text: str, needles: list[str]) -> None:
    for needle in needles:
        assert needle not in text


def test_cli_events_and_feedback_rows_redact_query_task_notes_paths(tmp_path: Path, capsys) -> None:
    root = tmp_path / "library"
    skill_file = write_skill(root)
    raw_query = "customer secret launch query zz-needle"
    raw_task = "private customer task yy-needle"
    raw_notes = "operator notes with sensitive detail xx-needle"

    assert _cli.main(["--root", str(root), "search", raw_query, "--mode", "lexical", "--json"]) == 0
    capsys.readouterr()
    assert _cli.main(["--root", str(root), "list", "--filter", raw_query, "--json"]) == 0
    capsys.readouterr()
    assert _cli.main(["--root", str(root), "view", "privacy-skill"]) == 0
    capsys.readouterr()
    assert _cli.main(["--root", str(root), "use", "privacy-skill", "--query", raw_query, "--task", raw_task]) == 0
    capsys.readouterr()
    assert _cli.main(["--root", str(root), "feedback", "privacy-skill", "--query", raw_query, "--verdict", "accepted", "--notes", raw_notes]) == 0
    capsys.readouterr()

    event_text = (root / ".learning" / EVENT_LOG).read_text(encoding="utf-8")
    feedback_text = (root / ".learning" / "feedback.jsonl").read_text(encoding="utf-8")
    assert_no_private_needles(
        event_text + feedback_text,
        [raw_query, raw_task, raw_notes, str(root), str(skill_file)],
    )

    rows = read_jsonl(root / ".learning" / EVENT_LOG)
    search = next(row for row in rows if row["type"] == "search")["payload"]
    assert search["query_summary_hash"] == task_summary_hash(raw_query)
    assert search["query_present"] is True
    assert "query" not in search
    assert all("path" not in hit and "score" not in hit for hit in search["hits"])
    assert all("score_bucket" in hit for hit in search["hits"])

    view = next(row for row in rows if row["type"] == "view")["payload"]
    assert view["library_path"] == "local/skills/privacy-skill/SKILL.md"
    assert "path" not in view

    used = next(row for row in rows if row["type"] == "skill_used")["payload"]
    assert used["query_summary_hash"] == task_summary_hash(raw_query)
    assert used["task_summary_hash"] == task_summary_hash(raw_task)
    assert used["library_path"] == "local/skills/privacy-skill/SKILL.md"
    assert "query" not in used and "task" not in used and "path" not in used

    feedback = read_jsonl(root / ".learning" / "feedback.jsonl")[-1]
    assert feedback["query_summary_hash"] == task_summary_hash(raw_query)
    assert feedback["query_token_hashes"]
    assert feedback["notes_present"] is True
    assert feedback["notes_length_bucket"] in {"short", "medium", "long"}
    assert "query" not in feedback and "notes" not in feedback
    assert "secret" not in json.dumps(feedback, ensure_ascii=False)


def test_suggest_event_has_safe_query_fingerprint(tmp_path: Path, capsys) -> None:
    root = tmp_path / "library"
    write_skill(root)
    raw_query = "private suggest query qq-needle"

    assert _cli.main(["--root", str(root), "suggest", raw_query, "--json"]) == 0
    capsys.readouterr()

    event_text = (root / ".learning" / EVENT_LOG).read_text(encoding="utf-8")
    assert raw_query not in event_text
    rows = read_jsonl(root / ".learning" / EVENT_LOG)
    suggest = next(row for row in rows if row["type"] == "suggest")["payload"]
    assert suggest["query_summary_hash"] == task_summary_hash(raw_query)
    assert suggest["query_token_hashes"]
    assert "query" not in suggest


def test_daemon_events_redact_query_task_notes_paths(tmp_path: Path) -> None:
    root = tmp_path / "library"
    write_skill(root, "daemon-privacy")

    from unlimited_skills import server

    server.ROOT = root
    raw_query = "daemon private query aa-needle"
    raw_task = "daemon customer task bb-needle"
    raw_notes = "daemon operator notes cc-needle"

    server.search(server.SearchRequest(query=raw_query, mode="lexical", limit=3))
    server.skill("daemon-privacy")
    server.use(server.UseRequest(name="daemon-privacy", query=raw_query, task=raw_task))
    server.feedback(server.FeedbackRequest(name="daemon-privacy", query=raw_query, verdict="accepted", notes=raw_notes))

    event_text = (root / ".learning" / EVENT_LOG).read_text(encoding="utf-8")
    assert_no_private_needles(event_text, [raw_query, raw_task, raw_notes, str(root)])

    rows = read_jsonl(root / ".learning" / EVENT_LOG)
    by_type = {row["type"]: row["payload"] for row in rows}
    assert by_type["daemon_search"]["query_summary_hash"] == task_summary_hash(raw_query)
    assert "query" not in by_type["daemon_search"]
    assert all("path" not in hit and "score" not in hit for hit in by_type["daemon_search"]["hits"])
    assert by_type["daemon_view"]["library_path"] == "local/skills/daemon-privacy/SKILL.md"
    assert "path" not in by_type["daemon_view"]
    assert by_type["daemon_skill_used"]["query_summary_hash"] == task_summary_hash(raw_query)
    assert by_type["daemon_skill_used"]["task_summary_hash"] == task_summary_hash(raw_task)
    assert "query" not in by_type["daemon_skill_used"]
    assert "task" not in by_type["daemon_skill_used"]
    assert "path" not in by_type["daemon_skill_used"]
    assert by_type["daemon_feedback"]["query_summary_hash"] == task_summary_hash(raw_query)
    assert by_type["daemon_feedback"]["notes_present"] is True
    assert "query" not in by_type["daemon_feedback"]
    assert "notes" not in by_type["daemon_feedback"]
