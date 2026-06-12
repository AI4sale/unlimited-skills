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
        # "pep8" (not "PEP 8") so the P1 fixture clears the tier-3 high threshold (18.0).
        "python-patterns": "Pythonic idioms, pep8 standards, and code review best practices for Python.",
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
            {"id": "P1", "category": "code-review", "prompt": "x", "query": "python code review pep8 idioms", "expected_skills": ["python-patterns"], "expected_tier": 3},
            {"id": "P2", "category": "code-write", "prompt": "x", "query": "React rerender performance optimization", "expected_skills": ["react-performance"], "forbidden_top1": ["python-patterns"], "expected_tier": 3},
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
    assert len(scenarios) == 40
    ids = [scenario["id"] for scenario in scenarios]
    assert len(set(ids)) == 40
    negatives = [scenario for scenario in scenarios if scenario.get("expect_no_skill")]
    assert len(negatives) >= 12  # S18, S28 + N1-N10 (Hermes gate: >= 10 added negatives)
    for scenario in scenarios:
        assert scenario["query"].strip()
        assert "category" in scenario
        if scenario.get("expect_no_skill"):
            assert scenario["expected_skills"] == []
            assert "expected_tier" not in scenario  # negatives must never expect a card
        else:
            assert scenario["expected_skills"]
        if "expected_tier" in scenario:
            assert scenario["expected_tier"] == 3
    # F3b: a handful of unambiguous positives assert tier-3 card injection.
    tier3 = [scenario for scenario in scenarios if scenario.get("expected_tier") == 3]
    assert len(tier3) >= 3


def test_checker_full_run_writes_record_and_passes(tmp_path: Path, checker, capsys, monkeypatch) -> None:
    library = make_library(tmp_path)
    scenarios = make_scenarios(tmp_path)
    record = tmp_path / "last-run.json"
    # The hook-side kill switch must not mask the injection gates: the
    # checker strips it from the probe environment.
    monkeypatch.setenv("UNLIMITED_SKILLS_NO_INJECT", "1")
    rc = checker.main(
        [
            "--scenarios", str(scenarios),
            "--root", str(library),
            "--record", str(record),
            "--max-p90-ms", "30000",
            "--max-p95-ms", "30000",
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
    assert summary["results"]["latency_ms"]["p95"] >= summary["results"]["latency_ms"]["p90"]
    # F3b injection gates: the unambiguous fixture queries score far above
    # the high threshold with no contesting runner-up, so cards fire and all
    # name the expected skill; the negative never gets one.
    assert summary["results"]["cards_shown"] >= 2
    assert summary["results"]["injection_precision"] == 1.0
    assert summary["results"]["negatives_injected"] == []
    assert summary["results"]["expected_tier3_misses"] == []
    # Privacy invariants are verified by scanning every actual probe output;
    # the tier-3 card is the only sanctioned body channel.
    assert summary["results"]["privacy"] == {
        "no_unintended_body_leak": True,
        "no_prompt_upload": True,
        "no_local_path_leak": True,
    }
    assert summary["thresholds"]["min_top1"] == 0.55
    assert summary["thresholds"]["min_top3"] == 0.83
    assert summary["thresholds"]["max_fp"] == 0.10
    assert summary["thresholds"]["max_p90_ms"] == 30000
    assert summary["thresholds"]["max_p95_ms"] == 30000
    assert summary["thresholds"]["min_injection_precision"] == 0.90
    assert summary["thresholds"]["max_negatives_injected"] == 0

    saved = json.loads(record.read_text(encoding="utf-8"))
    assert saved["version"]
    assert saved["date"]
    assert saved["results"]["top3_hit_rate"] == 1.0
    assert saved["results"]["privacy"]["no_prompt_upload"] is True
    assert saved["results"]["injection_precision"] == 1.0
    assert saved["results"]["negatives_injected"] == []
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


def test_scan_privacy_detects_each_leak_class(checker) -> None:
    snippets = frozenset({"a long enough normalized chunk of some skill body text to be unmistakable"})
    clean = checker.scan_privacy('{"top_3_skill_candidates": [{"name": "python-patterns", "source": "local", "score": 18.0}]}', "fix python bug", snippets)
    assert clean == {"prompt_leak": False, "path_leak": False, "body_leak": False}
    assert checker.scan_privacy("Fix Python  Bug", "fix python bug", snippets)["prompt_leak"] is True
    assert checker.scan_privacy(r'{"path": "C:\\Users\\someone\\skills"}', "q", snippets)["path_leak"] is True
    assert checker.scan_privacy('{"path": "/home/someone/skills"}', "q", snippets)["path_leak"] is True
    assert checker.scan_privacy("see https://example.com/docs", "q", snippets)["path_leak"] is False  # URLs are not local paths
    assert checker.scan_privacy("A LONG ENOUGH normalized chunk of some skill body text to be unmistakable", "q", snippets)["body_leak"] is True


def test_checker_fails_when_privacy_invariant_violated(tmp_path: Path, checker, capsys, monkeypatch) -> None:
    library = make_library(tmp_path)
    scenarios = make_scenarios(tmp_path)

    real_run_scenario = checker.run_scenario

    def leaky_run_scenario(python_exe, root, scenario, limit, floor, body_snippets):
        row = real_run_scenario(python_exe, root, scenario, limit, floor, body_snippets)
        row["privacy"]["path_leak"] = True  # simulate a path leaking into the output
        return row

    monkeypatch.setattr(checker, "run_scenario", leaky_run_scenario)
    rc = checker.main(
        [
            "--scenarios", str(scenarios),
            "--root", str(library),
            "--no-record",
            "--max-p90-ms", "30000",
            "--max-p95-ms", "30000",
            "--json",
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert summary["pass"] is False
    assert summary["results"]["privacy"]["no_local_path_leak"] is False


def _run_with_patched_scenario(tmp_path: Path, checker, capsys, monkeypatch, mutate) -> dict:
    """Full fixture run with one row mutated after the real probe."""
    library = make_library(tmp_path)
    scenarios = make_scenarios(tmp_path)
    real_run_scenario = checker.run_scenario

    def patched(python_exe, root, scenario, limit, floor, body_snippets):
        row = real_run_scenario(python_exe, root, scenario, limit, floor, body_snippets)
        mutate(row)
        return row

    monkeypatch.setattr(checker, "run_scenario", patched)
    rc = checker.main(
        [
            "--scenarios", str(scenarios),
            "--root", str(library),
            "--no-record",
            "--max-p90-ms", "30000",
            "--max-p95-ms", "30000",
            "--json",
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    summary["_rc"] = rc
    return summary


def test_checker_fails_when_a_negative_gets_a_card(tmp_path: Path, checker, capsys, monkeypatch) -> None:
    def mutate(row):
        if row["id"] == "N1":  # simulate a card injected on a no-skill scenario
            row["card_skill"] = "python-patterns"
            row["card_correct"] = False

    summary = _run_with_patched_scenario(tmp_path, checker, capsys, monkeypatch, mutate)
    assert summary["_rc"] == 1
    assert summary["pass"] is False
    assert summary["results"]["negatives_injected"] == ["N1"]


def test_checker_fails_when_expected_tier3_scenario_misses(tmp_path: Path, checker, capsys, monkeypatch) -> None:
    def mutate(row):
        if row["id"] == "P1":  # simulate the card not firing where asserted
            row["card_skill"] = None
            row["card_correct"] = False
            row["tier"] = 2

    summary = _run_with_patched_scenario(tmp_path, checker, capsys, monkeypatch, mutate)
    assert summary["_rc"] == 1
    assert summary["pass"] is False
    assert summary["results"]["expected_tier3_misses"] == ["P1"]


def test_checker_fails_below_injection_precision_gate(tmp_path: Path, checker, capsys, monkeypatch) -> None:
    def mutate(row):
        if row["id"] == "P3":  # simulate a card naming the WRONG skill
            row["card_skill"] = "python-patterns"
            row["card_correct"] = False

    summary = _run_with_patched_scenario(tmp_path, checker, capsys, monkeypatch, mutate)
    assert summary["_rc"] == 1
    assert summary["pass"] is False
    assert summary["results"]["injection_precision"] < 0.90


def test_cli_alias_skills_check_effectiveness(capsys) -> None:
    # `unlimited-skills skills check-effectiveness` wraps the script logic;
    # cadence mode is deterministic against the committed record.
    from unlimited_skills import cli

    rc = cli.main(["skills", "check-effectiveness", "--cadence-check", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0, payload
    assert payload["ok"] is True


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
