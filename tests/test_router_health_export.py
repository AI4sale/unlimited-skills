"""Tests for the Registered-tier router-health export (O062-TIER-REG-IMPL).

Proves the export is a real, runnable, schema-versioned local artifact over the
privacy-safe router metrics, with non-English fallback readiness, a fail-closed
privacy gate, and no upload/id surface.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from unlimited_skills.router_health import (
    ROUTER_HEALTH_EXPORT_SCHEMA_VERSION,
    build_router_health_export,
    router_health_export_json,
)
from unlimited_skills.commands.router_health import cmd_router_health_export

FIXED_TS = "2026-01-01T00:00:00Z"
INDEX_NAME = ".unlimited-skills-index.json"
CHROMA_DIR_NAME = ".chroma-skills"


def _write_metrics(root: Path, data: dict) -> None:
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    (learning / "router-metrics.json").write_text(json.dumps(data), encoding="utf-8")


def _export(root: Path) -> dict:
    return build_router_health_export(root, generated_at=FIXED_TS)


def test_schema_and_tier(tmp_path):
    export = _export(tmp_path)
    assert export["schema_version"] == ROUTER_HEALTH_EXPORT_SCHEMA_VERSION == "router-health-export-v1"
    assert export["report_type"] == "router_health_export"
    assert export["tier"] == "registered"
    assert export["source"] == "router_metrics"


def test_empty_state(tmp_path):
    export = _export(tmp_path)
    assert export["router"]["total_invocations"] == 0
    assert export["router"]["router_invoked"] is False
    assert export["last_call_summary"]["present"] is False
    assert export["readiness"]["non_english_fallback_readiness"] == "unavailable_no_index"


def test_metrics_present(tmp_path):
    _write_metrics(
        tmp_path,
        {
            "total_invocations": 7,
            "first_call_iso": "2026-01-01T00:00:00Z",
            "updated_iso": "2026-01-02T00:00:00Z",
            "by_day": {"2026-01-01": 3, "2026-01-02": 4},
            "last_call": {
                "iso": "2026-01-02T00:00:00Z",
                "reason_code": "match_found",
                "injected": True,
                "path": "lexical",
                "elapsed_ms": 12.0,
                "top_skill": "some-skill-name",
                "top_score": 9.0,
            },
        },
    )
    export = _export(tmp_path)
    assert export["router"]["total_invocations"] == 7
    assert export["router"]["router_invoked"] is True
    assert export["retrieval_path_aggregates"]["by_day_invocation_counts"] == {"2026-01-01": 3, "2026-01-02": 4}
    assert export["retrieval_path_aggregates"]["last_call_retrieval_path"] == "lexical"
    last = export["last_call_summary"]
    assert last["present"] is True
    assert last["retrieval_path"] == "lexical"
    assert last["reason_code"] == "match_found"
    assert last["top_skill"] == "some-skill-name"


def test_non_english_fallback_states(tmp_path):
    # No index -> unavailable.
    assert _export(tmp_path)["readiness"]["non_english_fallback_readiness"] == "unavailable_no_index"
    # Lexical only -> fallback only.
    (tmp_path / INDEX_NAME).write_text("{}", encoding="utf-8")
    assert _export(tmp_path)["readiness"]["non_english_fallback_readiness"] == "lexical_fallback_only"
    # Vector present -> multilingual ready.
    (tmp_path / CHROMA_DIR_NAME).mkdir()
    ready = _export(tmp_path)["readiness"]
    assert ready["non_english_fallback_readiness"] == "multilingual_vector_ready"
    assert ready["vector_index_present"] is True


def test_privacy_block_fail_safe(tmp_path):
    priv = _export(tmp_path)["privacy"]
    assert priv["local_only"] is True
    assert priv["upload"] is False
    for key, value in priv.items():
        if key.endswith("_included"):
            assert value is False, key


def test_forbidden_needles_absent(tmp_path):
    _write_metrics(
        tmp_path,
        {"total_invocations": 1, "last_call": {"iso": "2026-01-02T00:00:00Z", "path": "hybrid", "reason_code": "match_found"}},
    )
    blob = router_health_export_json(_export(tmp_path)).lower()
    # No raw query/prompt/path leakage; only safe aggregate fields present.
    assert "raw_query" not in blob.replace("raw_queries_included", "")
    assert "raw_prompt" not in blob.replace("raw_prompts_included", "")
    assert "c:\\" not in blob and "/home/" not in blob and "/users/" not in blob


def test_json_contract_stable(tmp_path):
    a = router_health_export_json(build_router_health_export(tmp_path, generated_at=FIXED_TS))
    b = router_health_export_json(build_router_health_export(tmp_path, generated_at=FIXED_TS))
    assert a == b
    assert json.loads(a)["schema_version"] == "router-health-export-v1"


def test_fail_closed_on_injected_forbidden_flag(tmp_path):
    export = _export(tmp_path)
    export["router"]["local_absolute_paths_included"] = True
    with pytest.raises(RuntimeError):
        router_health_export_json(export)


def test_cli_writes_file_and_stdout(tmp_path, capsys):
    out = tmp_path / "router-health.json"
    args = argparse.Namespace(root=str(tmp_path), out=str(out), json_status=True)
    rc = cmd_router_health_export(args)
    assert rc == 0
    assert out.is_file()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["schema_version"] == "router-health-export-v1"
    assert written["tier"] == "registered"

    capsys.readouterr()  # clear the --json-status line from the first call
    args2 = argparse.Namespace(root=str(tmp_path), out="", json_status=False)
    rc2 = cmd_router_health_export(args2)
    assert rc2 == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report_type"] == "router_health_export"
