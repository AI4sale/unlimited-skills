from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_json(command: list[str]) -> dict:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(result.stdout)


def test_v042_mcp_smoke_emits_release_evidence() -> None:
    report = run_json([sys.executable, "scripts/run-v042-alpha-mcp-smoke.py", "--fixture-mode", "--json"])
    assert report["status"] == "passed"
    assert report["release"] == "v0.4.2-alpha"
    assert report["mode"] == "fixture"
    assert report["production_hosted_calls"] is False
    assert report["mcp_resources_or_prompts"] is False
    assert report["oauth_upstreams"] is False
    assert report["skills_server_transcript"]["skills_search_metadata_only"] is True
    assert report["skills_server_transcript"]["skills_view_single_body"] == "debug-build"
    assert report["skills_server_transcript"]["skills_use_logged"] is True
    assert report["gateway_transcript"]["tools_search_no_schema_dump"] is True
    assert report["gateway_transcript"]["tools_schema_lazy_spawn"] is True
    assert report["gateway_transcript"]["tools_call_result"] == "echo:visible-result"
    assert report["gateway_transcript"]["audit_redaction"] is True
    assert report["boundary_verifier"]["status"] == "passed"


def test_v042_release_verifier_proves_mcp_and_e07_boundaries() -> None:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    report = run_json([sys.executable, "scripts/verify-v042-alpha-mcp.py", "--expected-sha", sha, "--json"])
    assert report["status"] == "passed"
    assert report["release"] == "v0.4.2-alpha"
    assert report["current_checkout_sha"] == sha
    assert report["mcp_server_fixture_transcript"]["malformed_request_refused"] == -32602
    assert report["mcp_server_fixture_transcript"]["unknown_tool_refused"] == -32602
    assert report["mcp_gateway_fixture_transcript"]["upstream_unavailable_refusal"] == -32001
    assert report["mcp_gateway_fixture_transcript"]["tools_search_no_schema_dump"] is True
    assert report["upstream_security_model"]["local_restricted_default"] is True
    assert report["upstream_security_model"]["env_allowlist_only"] is True
    assert report["upstream_security_model"]["wildcard_env_forwarding_impossible"] is True
    assert report["upstream_security_model"]["audit_cannot_be_off"] is True
    assert report["upstream_security_model"]["oauth_remote_out_of_scope"] is True
    assert report["upstream_security_model"]["resources_prompts_out_of_scope"] is True
    assert report["production_hosted_calls"] is False
    assert report["codex_pushes_tag"] is False
