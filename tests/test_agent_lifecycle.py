"""Agent lifecycle wrappers for non-Claude hosts (Codex/Hermes/OpenClaw)."""

from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.cli import main
from unlimited_skills.money_events import load_summary


def _json_objects(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    out = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        obj, index = decoder.raw_decode(text, index)
        out.append(obj)
    return out


def _write_skill(root: Path, name: str = "python-testing") -> None:
    path = root / "registry" / "ecc" / "skills" / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing Python code.\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def test_agent_lifecycle_record_accepts_wrapper_aliases(tmp_path: Path, monkeypatch, capsys) -> None:
    library = tmp_path / "library"
    home = tmp_path / "home"
    _write_skill(library)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))

    assert main(["--root", str(library), "agent-lifecycle", "record", "session-start", "--agent", "codex"]) == 0
    assert main(["--root", str(library), "agent-lifecycle", "record", "pre-compact", "--agent", "codex"]) == 0

    lines = _json_objects(capsys.readouterr().out)
    assert [line["event_type"] for line in lines] == ["session_start", "compaction"]
    assert all(line["agent"] == "codex" and line["ok"] is True for line in lines)

    summary = load_summary()
    event_types = {}
    for bucket in summary["buckets"].values():
        event_types.update(bucket["event_types"])
    assert event_types == {"session_start": 1, "compaction": 1}


def test_agent_lifecycle_records_supported_wrappers_separately(tmp_path: Path, monkeypatch, capsys) -> None:
    library = tmp_path / "library"
    home = tmp_path / "home"
    _write_skill(library)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))

    for agent in ("codex", "openclaw", "hermes"):
        assert main(["--root", str(library), "agent-lifecycle", "record", "session-start", "--agent", agent]) == 0

    rows = _json_objects(capsys.readouterr().out)
    assert {row["agent"] for row in rows} == {"codex", "openclaw", "hermes"}
    assert all(row["event_type"] == "session_start" and row["ok"] is True for row in rows)

    summary = load_summary()
    bucket_agents = {bucket["basis"]["agent"] for bucket in summary["buckets"].values()}
    assert bucket_agents == {"codex", "openclaw", "hermes"}
    assert sum(bucket["event_count"] for bucket in summary["buckets"].values()) == 3
    assert len(summary["buckets"]) == 3  # same model can still be audited per host wrapper
