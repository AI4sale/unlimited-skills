"""Language-aware routing for the `suggest` probe (non-English rescue).

Regression guard for the production bug where a non-English (e.g. Russian)
prompt fed straight into the ASCII lexical tokenizer produced an empty query
and therefore zero retrieval. The probe must now:

  1. use cheap lexical retrieval for English;
  2. on a non-English / lexical-empty query, route to the local multilingual
     embedding sidecar when one is installed;
  3. otherwise signal the caller (``needs_english_query``) to re-query with
     English keywords instead of returning silent garbage.
"""
from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills import suggest as suggest_mod
from unlimited_skills.search_core import SkillHit, save_index


def _english_library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    skill = root / "local" / "skills" / "security-review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: security-review\ndescription: Review code for security "
        "vulnerabilities, authentication, injection, and secrets.\n---\n\n# security-review\n",
        encoding="utf-8",
    )
    save_index(root)
    return root


def _run(argv: list[str], capsys) -> dict | None:
    # retrieval_path / needs_english_query ride the --card channel (the hook's mode).
    rc = suggest_mod.main(argv + ["--card"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


RU = "проверь безопасность кода и найди уязвимости в аутентификации"
EN = "review code for security vulnerabilities and authentication"


def test_looks_english_detects_language() -> None:
    le = suggest_mod.looks_english
    assert le(EN) is True
    assert le(RU) is False
    assert le("") is True               # nothing to translate → lexical path
    assert le("1234 !!! --- ") is True  # no letters → lexical path
    assert le("review the react component для рендера") is True  # latin-dominant


def test_english_no_match_does_not_flag_needs_english(tmp_path: Path, capsys) -> None:
    root = _english_library(tmp_path)
    payload = _run(["what is the weather in sydney tomorrow", "--root", str(root), "--json"], capsys)
    assert payload["retrieval_path"] == "none"
    assert "needs_english_query" not in payload  # English: stay silent, do not nag


def test_non_english_without_sidecar_flags_needs_english(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _english_library(tmp_path)  # no vector sidecar created
    monkeypatch.setenv("UNLIMITED_SKILLS_NO_VECTOR_FALLBACK", "1")
    payload = _run([RU, "--root", str(root), "--json"], capsys)
    assert payload["needs_english_query"] is True
    assert payload["retrieval_path"] == "none"
    assert payload["top_3_skill_candidates"] == []


def test_non_english_routes_to_vector_when_sidecar_present(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _english_library(tmp_path)
    from unlimited_skills import cli

    cli.vector_sidecar_path(root).write_text("{}", encoding="utf-8")  # mark sidecar "installed"
    hit = SkillHit(
        name="security-review",
        description="Review code for security issues.",
        collection="local",
        path=str(root / "local" / "skills" / "security-review" / "SKILL.md"),
        score=0.71,
    )
    called: dict = {}

    def fake_vector(r, q, limit, model, collection_name=None):  # no model load in tests
        called["q"] = q
        called["model"] = model
        return [hit]

    monkeypatch.setattr(cli, "vector_search", fake_vector)
    payload = _run([RU, "--root", str(root), "--json"], capsys)
    assert called.get("q"), "vector_search must run for a non-English prompt when a sidecar exists"
    assert payload["retrieval_path"] == "vector"
    assert payload["top_3_skill_candidates"][0]["name"] == "security-review"
    assert "needs_english_query" not in payload


def test_english_query_never_calls_vector(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _english_library(tmp_path)
    from unlimited_skills import cli

    cli.vector_sidecar_path(root).write_text("{}", encoding="utf-8")

    def boom(*args, **kwargs):
        raise AssertionError("vector_search must not run for an English prompt")

    monkeypatch.setattr(cli, "vector_search", boom)
    payload = _run([EN, "--root", str(root), "--json"], capsys)
    assert payload["retrieval_path"] == "lexical"
    assert payload["top_3_skill_candidates"][0]["name"] == "security-review"
