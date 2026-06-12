from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from unlimited_skills.search_core import save_index

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "scripts" / "check-skill-effectiveness.py"
SCENARIOS_FILE = REPO_ROOT / "evals" / "invocation-scenarios.json"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_skill_effectiveness", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return load_checker()


def make_library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    skills = {
        "python-patterns": "Pythonic idioms, PEP 8 standards, and code review best practices for Python.",
        "react-performance": "React re-render performance optimization with memoization and profiling.",
        "git-workflow": "Git workflow patterns: branching strategies, merge vs rebase, conflict resolution.",
    }
    for name, description in skills.items():
        skill_dir = root / "local" / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
            encoding="utf-8",
        )
    save_index(root)
    return root


def make_scenarios(tmp_path: Path) -> Path:
    payload = {
        "name": "fixture",
        "scenarios": [
            {"id": "P1", "category": "code-review", "prompt": "x", "query": "python code review pep8 idioms", "expected_skills": ["python-patterns"]},
            {"id": "P2", "category": "code-write", "prompt": "x", "query": "React rerender performance optimization", "expected_skills": ["react-performance"], "forbidden_top1": ["python-patterns"]},
            {"id": "P3", "category": "git-pr", "prompt": "x", "query": "git branch merge rebase workflow", "expected_skills": ["git-workflow"]},
            {"id": "N1", "category": "none", "prompt": "x", "query": "what is the capital of Australia", "expected_skills": [], "expect_no_skill": True},
        ],
    }
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_frozen_scenario_file_shape() -> None:
    payload = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
    scenarios = payload["scenarios"]
    assert len(scenarios) == 35
    ids = [scenario["id"] for scenario in scenarios]
    assert len(set(ids)) == 35
    negatives = [scenario for scenario in scenarios if scenario.get("expect_no_skill")]
    assert len(negatives) >= 5
    for scenario in scenarios:
        assert scenario["query"].strip()
        assert "category" in scenario
        if scenario.get("expect_no_skill"):
            assert scenario["expected_skills"] == []
        else:
            assert scenario["expected_skills"]


def test_checker_full_run_writes_record_and_passes(tmp_path: Path, checker, capsys) -> None:
    library = make_library(tmp_path)
    scenarios = make_scenarios(tmp_path)
    record = tmp_path / "last-run.json"
    rc = checker.main(
        [
            "--scenarios", str(scenarios),
            "--root", str(library),
            "--record", str(record),
            "--max-p90-ms", "30000",
            "--json",
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    assert rc == 0, summary
    assert summary["pass"] is True
    assert summary["results"]["top1_hit_rate"] == 1.0
    assert summary["results"]["top3_hit_rate"] == 1.0
    assert summary["results"]["false_positive_rate"] == 0.0
    assert summary["results"]["forbidden_top1_violations"] == []
    assert summary["results"]["latency_ms"]["p90"] > 0

    saved = json.loads(record.read_text(encoding="utf-8"))
    assert saved["version"]
    assert saved["date"]
    assert saved["results"]["top3_hit_rate"] == 1.0
    assert "scenarios" not in saved  # the record stays compact


def test_checker_fails_when_thresholds_not_met(tmp_path: Path, checker, capsys) -> None:
    library = make_library(tmp_path)
    scenarios = make_scenarios(tmp_path)
    rc = checker.main(
        [
            "--scenarios", str(scenarios),
            "--root", str(library),
            "--no-record",
            "--max-p90-ms", "0.001",
        ]
    )
    capsys.readouterr()
    assert rc == 1


def test_parse_version(checker) -> None:
    assert checker.parse_version("v0.4.9-alpha.release-manifest.json") == (0, 4, 9)
    assert checker.parse_version("0.3.13") == (0, 3, 13)
    assert checker.parse_version("garbage") is None


def make_releases(tmp_path: Path, versions: list[str]) -> Path:
    releases = tmp_path / "releases"
    releases.mkdir(exist_ok=True)
    for version in versions:
        (releases / f"v{version}-alpha.release-manifest.json").write_text("{}", encoding="utf-8")
    return releases


def test_cadence_check_fails_without_record(tmp_path: Path, checker) -> None:
    ok, message = checker.cadence_check(tmp_path / "missing.json", make_releases(tmp_path, ["0.4.0"]), 10)
    assert ok is False
    assert "No recorded effectiveness run" in message


def test_cadence_check_fails_at_gap_of_ten(tmp_path: Path, checker) -> None:
    record = tmp_path / "record.json"
    record.write_text(json.dumps({"version": "0.3.9", "date": "2026-01-01"}), encoding="utf-8")
    versions = [f"0.4.{i}" for i in range(10)]  # ten releases after 0.3.9
    ok, message = checker.cadence_check(record, make_releases(tmp_path, versions), 10)
    assert ok is False
    assert "10 releases" in message


def test_cadence_check_passes_below_gap(tmp_path: Path, checker) -> None:
    record = tmp_path / "record.json"
    record.write_text(json.dumps({"version": "0.4.5", "date": "2026-06-01"}), encoding="utf-8")
    versions = [f"0.4.{i}" for i in range(10)]  # only 0.4.6-0.4.9 are newer
    ok, message = checker.cadence_check(record, make_releases(tmp_path, versions), 10)
    assert ok is True
    assert "4 release(s)" in message


def test_cadence_check_cli_mode(tmp_path: Path, checker, capsys) -> None:
    record = tmp_path / "record.json"
    record.write_text(json.dumps({"version": "0.4.9", "date": "2026-06-12"}), encoding="utf-8")
    releases = make_releases(tmp_path, ["0.4.9"])
    rc = checker.main(["--cadence-check", "--record", str(record), "--releases-dir", str(releases)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK:" in out


def test_repo_record_exists_and_cadence_is_green(checker) -> None:
    # The committed record must keep the cadence gate green for the current tree.
    record = REPO_ROOT / "evals" / "last-effectiveness-run.json"
    assert record.is_file(), "run scripts/check-skill-effectiveness.py and commit the record"
    ok, message = checker.cadence_check(record, REPO_ROOT / "docs" / "releases", 10)
    assert ok is True, message
