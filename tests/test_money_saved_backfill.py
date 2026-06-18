from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.cli import main
from unlimited_skills.money_events import load_summary


def _write_skill(root: Path) -> None:
    path = root / "registry" / "ecc" / "skills" / "python-testing"
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        "---\nname: python-testing\ndescription: Use when testing Python code.\n---\n\n# python-testing\n",
        encoding="utf-8",
    )


def _json_objects(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    rows = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        row, index = decoder.raw_decode(text, index)
        rows.append(row)
    return rows


def _session_log(root: Path) -> Path:
    path = root / "2026" / "06" / "18" / "session.jsonl"
    path.parent.mkdir(parents=True)
    rows = [
        {"type": "event_msg", "timestamp": "2026-06-18T10:00:00Z", "payload": {"type": "context_compacted"}},
        {"type": "compacted", "timestamp": "2026-06-18T10:00:00Z", "payload": {"reason": "paired_full_event"}},
        {"type": "event_msg", "timestamp": "2026-06-18T10:05:00Z", "payload": {"type": "user_message"}},
        {"type": "event_msg", "timestamp": "2026-06-18T10:10:00Z", "payload": {"type": "context_compacted"}},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_money_events_store_follows_library_root_without_home_env(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_HOME", raising=False)
    install_root = tmp_path / ".unlimited-skills"
    library = install_root / "library"
    _write_skill(library)

    assert main(["--root", str(library), "money-saved", "events", "record-fixture", "--event-count", "2"]) == 0
    payload = _json_objects(capsys.readouterr().out)[0]

    assert payload["dir"] == str(install_root / "money_saved")
    assert (install_root / "money_saved" / "summary.json").is_file()


def test_codex_log_backfill_dry_run_apply_and_dedupe(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_HOME", raising=False)
    install_root = tmp_path / ".unlimited-skills"
    library = install_root / "library"
    sessions = tmp_path / "sessions"
    _write_skill(library)
    _session_log(sessions)

    base = ["--root", str(library), "money-saved", "events", "backfill-codex-logs", "--sessions-root", str(sessions)]
    assert main([*base, "--since", "all"]) == 0
    dry = _json_objects(capsys.readouterr().out)[0]
    assert dry["mode"] == "dry_run"
    assert dry["markers_found"] == 2
    assert dry["eligible_new_markers"] == 2
    assert dry["recorded"] == 0
    assert not (install_root / "money_saved" / "summary.json").exists()

    assert main([*base, "--since", "all", "--apply"]) == 0
    applied = _json_objects(capsys.readouterr().out)[0]
    assert applied["mode"] == "apply"
    assert applied["recorded"] == 2
    assert applied["event_types"] == {"compaction": 2}

    summary = load_summary(install_root / "money_saved")
    assert sum(bucket["event_count"] for bucket in summary["buckets"].values()) == 2
    assert {bucket["basis"]["agent"] for bucket in summary["buckets"].values()} == {"codex"}
    event_types = {}
    for bucket in summary["buckets"].values():
        event_types.update(bucket["event_types"])
    assert event_types == {"compaction": 2}

    assert main([*base, "--since", "all", "--apply"]) == 0
    second = _json_objects(capsys.readouterr().out)[0]
    assert second["recorded"] == 0
    assert second["already_recorded"] == 2
    assert sum(bucket["event_count"] for bucket in load_summary(install_root / "money_saved")["buckets"].values()) == 2
