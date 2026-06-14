"""Internal router-invocation counter (`<root>/.learning/router-metrics.json`).

The meter answers "how many times has the router been called, and when/how
fast was the last call?" — the visibility the regression hunt lacked. It must
count every `suggest` invocation, record the last call's timing/outcome/path,
and never leak the query text or filesystem paths.
"""
from __future__ import annotations

from pathlib import Path

from unlimited_skills import suggest as suggest_mod
from unlimited_skills.search_core import read_router_metrics, record_router_call, save_index


def _library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    skill = root / "local" / "skills" / "security-review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: security-review\ndescription: Review code for security "
        "vulnerabilities and authentication.\n---\n\n# security-review\n",
        encoding="utf-8",
    )
    save_index(root)
    return root


def test_record_router_call_increments_and_stamps(tmp_path: Path) -> None:
    root = _library(tmp_path)
    record_router_call(root, elapsed_ms=12.3, reason_code="match_found", path="lexical", top_skill="security-review", top_score=20.0)
    metrics = read_router_metrics(root)
    assert metrics["total_invocations"] == 1
    last = metrics["last_call"]
    assert last["reason_code"] == "match_found"
    assert last["path"] == "lexical"
    assert last["top_skill"] == "security-review"
    assert last["elapsed_ms"] == 12.3
    assert last["iso"].endswith("Z")

    record_router_call(root, path="vector", reason_code="match_found")
    metrics = read_router_metrics(root)
    assert metrics["total_invocations"] == 2
    assert metrics["last_call"]["path"] == "vector"


def test_suggest_increments_counter_with_path(tmp_path: Path) -> None:
    root = _library(tmp_path)
    for _ in range(3):
        suggest_mod.main(["review code security vulnerabilities", "--root", str(root), "--json"])
    metrics = read_router_metrics(root)
    assert metrics["total_invocations"] == 3
    assert metrics["last_call"]["path"] == "lexical"


def test_metrics_file_never_leaks_query_or_paths(tmp_path: Path, monkeypatch) -> None:
    root = _library(tmp_path)
    monkeypatch.setenv("UNLIMITED_SKILLS_NO_VECTOR_FALLBACK", "1")
    suggest_mod.main(["проверь безопасность кода и найди уязвимости", "--root", str(root), "--json"])
    raw = (root / ".learning" / "router-metrics.json").read_text(encoding="utf-8")
    assert "проверь" not in raw          # no raw query text
    assert str(root) not in raw          # no absolute paths
    assert ":\\" not in raw and ":/" not in raw
    metrics = read_router_metrics(root)
    assert metrics["total_invocations"] == 1
    assert metrics["last_call"]["path"] == "none"  # non-English, no sidecar → escalated
