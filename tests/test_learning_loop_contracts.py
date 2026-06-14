from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_script(name: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / name)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout)


def assert_private_needles_absent(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for needle in [
        "prompt secret",
        "raw customer task",
        "operator secret note",
        "C:\\Users\\tedja\\private",
        "ghp_secretTOKEN123456",
        "-----BEGIN PRIVATE KEY-----",
        "Private customer incident playbook",
    ]:
        assert needle not in text
    assert ":\\" not in text and ":/" not in text


def test_v063_feedback_signal_contract_fixtures_validate() -> None:
    result = run_script("verify-learning-feedback-contract.py")

    assert result["ok"] is True
    assert result["valid_rows"] == 7
    assert result["invalid_rows"] == 4
    assert result["valid_errors"] == []
    assert result["invalid_rows_that_passed"] == []


def test_v063_closed_loop_proof_is_redacted_and_non_mutating() -> None:
    result = run_script("verify-learning-loop-closed-loop-proof.py")

    assert result["report_type"] == "learning_loop_closed_loop_proof"
    assert result["learning_doctor"]["feedback_outcomes"]["wrong"] == 1
    assert result["improvement_candidates"]["candidate_count"] == 1
    assert result["dry_run_preview"]["written"] is False
    assert result["dry_run_preview"]["mutated_files"] == []
    assert result["verification"]["skill_file_unchanged"] is True
    assert_private_needles_absent(result)
