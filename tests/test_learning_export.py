"""Tests for the Registered-tier Learning Loop export (O063-TIER-REG-IMPL).

Proves the export is a real, runnable, schema-versioned local artifact over the
Learning Loop state (feedback outcomes, candidate counts, non-mutating dry-run),
with a fail-closed privacy gate and no upload/mutation surface.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from unlimited_skills.learning_tiers import (
    LEARNING_EXPORT_SCHEMA_VERSION,
    build_learning_export,
    learning_export_json,
)
from unlimited_skills.commands.learning import cmd_learning_export

FIXED_TS = "2026-01-01T00:00:00Z"


def _write_feedback(root: Path, rows: list[dict]) -> None:
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    (learning / "feedback.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def _export(root: Path) -> dict:
    return build_learning_export(root, generated_at=FIXED_TS)


def test_schema_and_tier(tmp_path):
    export = _export(tmp_path)
    assert export["schema_version"] == LEARNING_EXPORT_SCHEMA_VERSION == "learning-export-v1"
    assert export["report_type"] == "learning_export"
    assert export["tier"] == "registered"
    assert export["source"] == "learning_loop"


def test_empty_state(tmp_path):
    export = _export(tmp_path)
    assert export["feedback"]["feedback_count"] == 0
    assert export["candidates"]["candidate_count"] == 0
    assert export["readiness"]["has_feedback"] is False


def test_feedback_present(tmp_path):
    _write_feedback(
        tmp_path,
        [
            {"verdict": "wrong", "skill": "alpha"},
            {"verdict": "missed", "skill": "beta"},
            {"verdict": "wrong", "skill": "alpha"},
        ],
    )
    export = _export(tmp_path)
    assert export["feedback"]["feedback_count"] == 3
    assert export["readiness"]["has_feedback"] is True
    assert isinstance(export["feedback"]["outcome_counts"], dict)
    assert sum(export["feedback"]["outcome_counts"].values()) == 3


def test_dry_run_is_non_mutating(tmp_path):
    dry = _export(tmp_path)["dry_run"]
    assert dry["mutation_supported"] is False
    assert dry["dry_run_only"] is True


def test_candidate_block_present(tmp_path):
    export = _export(tmp_path)
    assert "candidate_count" in export["candidates"]
    assert "candidate_ids" in export["candidates"]


def test_privacy_block_fail_safe(tmp_path):
    priv = _export(tmp_path)["privacy"]
    assert priv["local_only"] is True
    assert priv["upload"] is False
    for key, value in priv.items():
        if key.endswith("_included"):
            assert value is False, key


def test_forbidden_needles_absent(tmp_path):
    _write_feedback(tmp_path, [{"verdict": "wrong", "skill": "alpha"}])
    blob = learning_export_json(_export(tmp_path)).lower()
    assert "raw_query" not in blob.replace("raw_queries_included", "")
    assert "raw_prompt" not in blob.replace("raw_prompts_included", "")
    assert "c:\\" not in blob and "/home/" not in blob and "/users/" not in blob


def test_json_contract_stable(tmp_path):
    a = learning_export_json(build_learning_export(tmp_path, generated_at=FIXED_TS))
    b = learning_export_json(build_learning_export(tmp_path, generated_at=FIXED_TS))
    assert a == b
    assert json.loads(a)["schema_version"] == "learning-export-v1"


def test_fail_closed_on_injected_forbidden_flag(tmp_path):
    export = _export(tmp_path)
    export["feedback"]["local_absolute_paths_included"] = True
    with pytest.raises(RuntimeError):
        learning_export_json(export)


def test_cli_writes_file_and_stdout(tmp_path, capsys):
    out = tmp_path / "learning.json"
    args = argparse.Namespace(root=str(tmp_path), out=str(out), json_status=True)
    rc = cmd_learning_export(args)
    assert rc == 0
    assert out.is_file()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["schema_version"] == "learning-export-v1"
    assert written["tier"] == "registered"

    capsys.readouterr()
    args2 = argparse.Namespace(root=str(tmp_path), out="", json_status=False)
    rc2 = cmd_learning_export(args2)
    assert rc2 == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report_type"] == "learning_export"
