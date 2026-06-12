from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from unlimited_skills import cli
from unlimited_skills.skill_effectiveness import (
    evaluate_skill_effectiveness,
    suggest_report_to_json,
    suggest_skills,
    write_fixture_library,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    write_fixture_library(root)
    cli.save_index(root)
    return root


def test_suggest_is_redacted_and_actionable(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    report = suggest_skills(root, "review this repository for exposed secrets", limit=3, fresh=True)
    payload = suggest_report_to_json(report)
    dumped = json.dumps(payload, ensure_ascii=False)

    assert payload["task_summary_hash"]
    assert "review this repository" not in dumped
    assert str(root) not in dumped
    assert "SKILL.md" not in dumped
    assert payload["no_skill_body_leak"] is True
    assert payload["no_prompt_upload"] is True
    assert payload["no_tool_output_upload"] is True
    assert payload["no_local_path_leak"] is True
    assert payload["top_3_skill_candidates"][0]["name"] == "security-review"


def test_a0_fixture_gate_passes(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    report = evaluate_skill_effectiveness(root, gate="a0-merge", fresh=True)

    assert report.status == "passed"
    assert report.positive_scenarios == 30
    assert report.negative_scenarios == 10
    assert report.top_3_hit_rate >= 0.83
    assert report.false_positive_rate <= 0.10


def test_v05_fixture_gate_passes(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    report = evaluate_skill_effectiveness(root, gate="v0.5-release", fresh=True)

    assert report.status == "passed"
    assert report.top_1_hit_rate >= 0.65
    assert report.top_3_hit_rate >= 0.90
    assert report.p95_suggest_latency_ms <= 2000


def test_cli_suggest_prints_no_paths(tmp_path: Path, capsys) -> None:
    root = _fixture_root(tmp_path)
    code = cli.main(["--root", str(root), "suggest", "check CI for PR 42", "--json", "--fresh", "--no-native-sync"])
    captured = capsys.readouterr()

    assert code == 0
    payload = json.loads(captured.out)
    assert payload["top_3_skill_candidates"][0]["name"] == "github-ops"
    assert str(root) not in captured.out
    assert "SKILL.md" not in captured.out


def test_check_effectiveness_script_fixture_mode() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/check-skill-effectiveness.py", "--fixture-mode", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["status"] == "passed"
    assert payload["positive_scenarios"] == 30
    assert payload["negative_scenarios"] == 10


def test_verify_skill_effectiveness_gate() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/verify-skill-effectiveness-gate.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    assert "Skill effectiveness gate passed" in proc.stdout
