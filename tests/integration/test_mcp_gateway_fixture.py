from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def run_json_script(*args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_mcp_fixture_smoke_subprocess() -> None:
    report = run_json_script("scripts/run-mcp-smoke.py", "--fixture-mode", "--json")
    assert report["status"] == "passed"
    assert report["skills_server"]["tools"] == ["skills_search", "skills_use", "skills_view"]
    assert report["gateway"]["tools"] == ["tools_call", "tools_schema", "tools_search"]
    assert report["gateway"]["tools_search_no_schema_dump"] is True
    assert report["gateway"]["tools_search_no_spawn"] is True
    assert report["gateway"]["tools_schema_lazy_spawn"] is True
    assert report["gateway"]["audit_redaction"] is True
    assert report["boundaries"]["production_hosted_calls"] is False


def test_mcp_boundary_verifier_subprocess() -> None:
    report = run_json_script("scripts/verify-mcp-boundaries.py", "--json")
    assert report["status"] == "passed"
    assert report["failures"] == []
    assert report["proofs"]["mcp_stdio_handshake_fixture"] is True
    assert report["proofs"]["no_sensitive_marker_grep"] is True
    assert report["proofs"]["production_hosted_calls"] is False
