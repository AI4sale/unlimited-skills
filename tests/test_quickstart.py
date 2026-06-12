"""Tests for `unlimited-skills quickstart` (A1 golden path).

Covers: bundled-pack import when the library is empty, skip when populated,
idempotency across reruns, the first-search step (including the demo-query
fallback), the savings step wiring, and the CLI `--json` report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills import cli
from unlimited_skills import quickstart as quickstart_mod
from unlimited_skills.quickstart import (
    DEFAULT_QUERY,
    ensure_bundled_library,
    find_repo_root,
    first_search,
    format_quickstart_text,
    run_quickstart,
)


def make_skill(root: Path, name: str, description: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


@pytest.fixture()
def fixture_repo(tmp_path: Path) -> Path:
    """A minimal repo checkout shape: pyproject.toml + bundled packs/."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    make_skill(repo / "packs" / "ecc" / "skills", "code-review", "Code review checklist for pull requests")
    make_skill(repo / "packs" / "superpowers" / "skills", "debugging-loop", "Systematic debugging workflow")
    return repo


def test_find_repo_root_walks_up(fixture_repo: Path) -> None:
    nested = fixture_repo / "unlimited_skills" / "deep"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) == fixture_repo
    assert find_repo_root(fixture_repo.parent / "nowhere") is None


def test_empty_library_imports_bundled_packs(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "library"
    result = ensure_bundled_library(root, repo_root=fixture_repo)
    assert result["status"] == "imported"
    assert result["imported"] == {"ecc": 1, "superpowers": 1}
    assert result["skill_count"] == 2
    assert (root / "registry" / "ecc" / "skills" / "code-review" / "SKILL.md").is_file()
    assert (root / ".unlimited-skills-index.json").is_file()


def test_populated_library_skips_import(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "library"
    make_skill(root / "local" / "skills", "existing-skill", "Already here")
    result = ensure_bundled_library(root, repo_root=fixture_repo)
    assert result["status"] == "ready"
    assert result["imported"] == {}
    assert result["skill_count"] == 1
    # The bundled packs were NOT imported over a populated library.
    assert not (root / "registry" / "ecc").exists()


def test_empty_library_without_packs_reports_hint(tmp_path: Path) -> None:
    root = tmp_path / "library"
    no_packs = tmp_path / "no-repo"
    no_packs.mkdir()
    result = ensure_bundled_library(root, repo_root=no_packs)
    assert result["status"] == "empty_no_packs"
    text = format_quickstart_text(
        {
            "library": result,
            "search": {"query": DEFAULT_QUERY, "fallback_to_demo_query": False, "hits": []},
            "savings": None,
            "savings_error": "",
        }
    )
    assert "install-pack" in text


def test_first_search_falls_back_to_demo_query(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "library"
    ensure_bundled_library(root, repo_root=fixture_repo)
    result = first_search(root, "zzz-completely-unrelated-nonsense-query")
    assert result["fallback_to_demo_query"] is True
    assert result["query"] == DEFAULT_QUERY
    assert result["hits"], "demo query must hit the bundled fixture skills"


def test_run_quickstart_is_idempotent(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "library"
    missing_config = tmp_path / "no-claude.json"
    first = run_quickstart(root, repo_root=fixture_repo, claude_config=missing_config)
    assert first["library"]["status"] == "imported"
    assert first["search"]["hits"]
    # No MCP servers in the (missing) config: the savings step still answers
    # with the lab benchmark instead of failing.
    assert first["savings"] is not None
    assert first["savings"]["benchmark"]["full_dump_bytes"] == 90_420

    second = run_quickstart(root, repo_root=fixture_repo, claude_config=missing_config)
    assert second["library"]["status"] == "ready"
    assert second["library"]["imported"] == {}
    assert second["library"]["skill_count"] == first["library"]["skill_count"]
    assert second["search"]["hits"] == first["search"]["hits"]

    events = (root / ".learning" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in events if line.strip()]
    assert sum(1 for row in rows if row.get("type") == "quickstart") == 2


def test_quickstart_cli_json(
    fixture_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(quickstart_mod, "find_repo_root", lambda start=None: fixture_repo)
    root = tmp_path / "library"
    code = cli.main(["--root", str(root), "quickstart", "--json", "--skip-mcp-check"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["library"]["status"] == "imported"
    assert report["search"]["hits"]
    assert report["root"] == "<local-library>"
    assert "path" not in report["search"]["hits"][0]
    assert str(root) not in json.dumps(report)
    assert report["savings"] is None
    assert report["next_steps"]

    # Rerun: idempotent, text mode, library untouched.
    code = cli.main(["--root", str(root), "quickstart", "--skip-mcp-check"])
    assert code == 0
    out = capsys.readouterr().out
    assert "import skipped" in out
    assert "Next steps" in out


def test_quickstart_text_renders_all_steps(fixture_repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "library"
    report = run_quickstart(
        root,
        repo_root=fixture_repo,
        claude_config=tmp_path / "no-claude.json",
        query="debugging workflow",
    )
    text = format_quickstart_text(report)
    assert "[1/4] Library" in text
    assert "[2/4] First search" in text
    assert "[3/4] MCP context savings" in text
    assert "[4/4] Next steps" in text
    assert "unlimited-skills mcp gateway" in text
    assert "unlimited-skills setup --local-only" in text
