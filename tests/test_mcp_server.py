from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills.mcp.protocol import StdioServer, ToolError
from unlimited_skills.mcp.server import (
    MAX_SEARCH_LIMIT,
    VIEW_CHAR_CAP,
    build_skills_registry,
)
from unlimited_skills.search_core import task_summary_hash

BODY_MARKER = "BODYSECRETMARKER-not-for-search-results"


def write_skill(root: Path, collection: str, name: str, description: str, body: str) -> None:
    skill_file = root / collection / "skills" / name / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    write_skill(root, "alpha", "release-checklist", "Release checklist procedure", f"Step one. {BODY_MARKER}")
    write_skill(root, "alpha", "debug-build", "Fix build failures fast", f"Run the build. {BODY_MARKER}")
    write_skill(root, "beta", "giant-skill", "A very long skill", "x" * (VIEW_CHAR_CAP + 500))
    return root


def test_skills_search_metadata_only(library: Path) -> None:
    registry = build_skills_registry(library)
    result = registry["skills_search"]["handler"]({"query": "release checklist", "mode": "lexical"})
    dumped = json.dumps(result)
    assert result["hits"], "expected at least one hit"
    top = result["hits"][0]
    assert top["name"] == "release-checklist"
    assert top["collection"] == "alpha"
    assert top["description"] == "Release checklist procedure"
    assert top["score"] > 0
    # No skill bodies and no absolute local paths may leak from search.
    assert BODY_MARKER not in dumped
    assert str(library) not in dumped
    assert top["library_path"] == "alpha/skills/release-checklist/SKILL.md"


def test_skills_search_limit_clamped_and_mode_validated(library: Path) -> None:
    root = library
    for index in range(25):
        write_skill(root, "alpha", f"release-extra-{index}", "release helper", "release body")
    registry = build_skills_registry(root)
    result = registry["skills_search"]["handler"]({"query": "release", "limit": 100})
    assert len(result["hits"]) <= MAX_SEARCH_LIMIT
    with pytest.raises(ToolError):
        registry["skills_search"]["handler"]({"query": "release", "mode": "vector"})
    with pytest.raises(ToolError):
        registry["skills_search"]["handler"]({"query": ""})
    with pytest.raises(ToolError):
        registry["skills_search"]["handler"]({"query": "release", "limit": "many"})


def test_skills_view_returns_capped_body(library: Path) -> None:
    registry = build_skills_registry(library)
    result = registry["skills_view"]["handler"]({"name": "release-checklist"})
    assert result["name"] == "release-checklist"
    assert result["metadata"]["description"] == "Release checklist procedure"
    assert BODY_MARKER in result["body"]
    assert result["truncated"] is False
    assert "_abs_path" not in result

    capped = registry["skills_view"]["handler"]({"name": "giant-skill"})
    assert capped["truncated"] is True
    assert "[truncated:" in capped["body"]
    assert len(capped["body"]) <= VIEW_CHAR_CAP + 200

    with pytest.raises(ToolError):
        registry["skills_view"]["handler"]({"name": "no-such-skill"})


def test_skills_use_logs_event_and_never_executes(library: Path) -> None:
    registry = build_skills_registry(library)
    description = registry["skills_use"]["description"]
    assert "never executes" in description
    result = registry["skills_use"]["handler"](
        {"name": "debug-build", "query": "fix the build", "task": "ci"}
    )
    assert result["use_logged"] is True
    assert BODY_MARKER in result["body"]
    events_file = library / ".learning" / "events.jsonl"
    rows = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    used = [row for row in rows if row["type"] == "skill_used"]
    assert used, "skills_use must log a skill_used event"
    payload = used[-1]["payload"]
    assert payload["name"] == "debug-build"
    assert payload["query_summary_hash"] == task_summary_hash("fix the build")
    assert payload["query_present"] is True
    assert payload["task_summary_hash"] == task_summary_hash("ci")
    assert "query" not in payload
    assert "task" not in payload
    assert "path" not in payload
    assert str(library) not in json.dumps(payload)
    assert payload["source"] == "mcp"


def test_skills_server_via_stdio_dispatch(library: Path) -> None:
    server = StdioServer(build_skills_registry(library), server_name="unlimited-skills")
    listing = server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )["result"]["tools"]
    assert [tool["name"] for tool in listing] == ["skills_search", "skills_use", "skills_view"]
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "skills_search", "arguments": {"query": "debug build"}},
        }
    )
    result = response["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["hits"][0]["name"] == "debug-build"
    assert BODY_MARKER not in result["content"][0]["text"]
