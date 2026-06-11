from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp_smoke_support import (
    LOCAL_PATH_MARKER,
    PRIVATE_KEY_MARKER,
    PRIVATE_PACK_MARKER,
    PROMPT_MARKER,
    PROOF_MARKER,
    SEARCH_QUERY_MARKER,
    SKILL_BODY_MARKER,
    TOKEN_MARKER,
    JsonRpcProcess,
    assert_no_markers,
    call_tool,
    write_fake_upstream,
    write_gateway_config,
    write_skill,
)


def _tool_names(listing: dict[str, Any]) -> list[str]:
    return sorted(tool["name"] for tool in listing["result"]["tools"])


def run_smoke(repo: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="uls-mcp-smoke-") as temp:
        temp_root = Path(temp)
        library = temp_root / "library"
        write_skill(library)
        upstream_script, spawn_marker = write_fake_upstream(temp_root)
        gateway_config = write_gateway_config(temp_root, upstream_script, spawn_marker)
        audit_path = temp_root / "mcp-audit.jsonl"

        skills = JsonRpcProcess(
            [sys.executable, "-m", "unlimited_skills.cli", "--root", str(library), "mcp", "serve"],
            cwd=repo,
            env={"PYTHONPATH": str(repo)},
        )
        gateway = JsonRpcProcess(
            [
                sys.executable,
                "-m",
                "unlimited_skills.cli",
                "--root",
                str(library),
                "mcp",
                "gateway",
                "--config",
                str(gateway_config),
                "--audit-log",
                str(audit_path),
            ],
            cwd=repo,
            env={
                TOKEN_MARKER: TOKEN_MARKER,
                "FAKE_UPSTREAM_TOKEN": TOKEN_MARKER,
                "PYTHONPATH": str(repo),
            },
        )
        try:
            skills_init = skills.request("initialize", {"capabilities": {}})
            gateway_init = gateway.request("initialize", {"capabilities": {}})
            skills.notify("notifications/initialized")
            gateway.notify("notifications/initialized")

            skills_listing = skills.request("tools/list")
            gateway_listing = gateway.request("tools/list")
            assert _tool_names(skills_listing) == ["skills_search", "skills_use", "skills_view"]
            assert _tool_names(gateway_listing) == ["tools_call", "tools_schema", "tools_search"]

            search_response, search_payload = call_tool(
                skills,
                "skills_search",
                {"query": "debug build", "mode": "lexical", "limit": 5},
            )
            search_text = json.dumps(search_response)
            if SKILL_BODY_MARKER in search_text or str(library) in search_text:
                raise AssertionError("skills_search leaked a skill body or absolute local path")
            if not search_payload["hits"] or search_payload["hits"][0]["name"] != "debug-build":
                raise AssertionError("skills_search did not find the fixture skill")

            view_response, view_payload = call_tool(skills, "skills_view", {"name": "debug-build"})
            if SKILL_BODY_MARKER not in json.dumps(view_payload):
                raise AssertionError("skills_view must return the selected skill body")
            if view_payload["truncated"]:
                raise AssertionError("fixture skill should not be truncated")

            use_response, use_payload = call_tool(
                skills,
                "skills_use",
                {"name": "debug-build", "query": "debug build", "task": "mcp-smoke"},
            )
            if use_payload.get("use_logged") is not True:
                raise AssertionError("skills_use must log a use event")

            malformed_refusal = skills.raw_request({"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": []})
            if malformed_refusal.get("error", {}).get("code") != -32602:
                raise AssertionError("malformed params must be refused")
            unknown_refusal = skills.request(
                "tools/call",
                {"name": "missing_skill_tool", "arguments": {}},
            )
            if unknown_refusal.get("error", {}).get("code") != -32602:
                raise AssertionError("unknown tool must be refused")

            gateway_search_response, gateway_search_payload = call_tool(
                gateway,
                "tools_search",
                {"query": SEARCH_QUERY_MARKER, "limit": 5},
            )
            gateway_search_text = json.dumps(gateway_search_response)
            if "inputSchema" in gateway_search_text:
                raise AssertionError("tools_search must not include tool schemas")
            if spawn_marker.exists():
                raise AssertionError("tools_search without refresh must not spawn upstreams")

            schema_response, schema_payload = call_tool(gateway, "tools_schema", {"tool": "fake.add"})
            if not spawn_marker.exists():
                raise AssertionError("tools_schema must lazily spawn the selected upstream")
            if schema_payload["inputSchema"]["properties"]["a"]["type"] != "integer":
                raise AssertionError("tools_schema returned the wrong schema")

            call_response, call_payload = call_tool(
                gateway,
                "tools_call",
                {
                    "tool": "fake.echo",
                    "arguments": {
                        "text": "visible-result",
                        "api_token": TOKEN_MARKER,
                        "proof": PROOF_MARKER,
                        "private_key": f"-----BEGIN RSA PRIVATE KEY-----{PRIVATE_KEY_MARKER}",
                        "prompt": PROMPT_MARKER,
                        "private_pack_body": PRIVATE_PACK_MARKER,
                        "local_path": LOCAL_PATH_MARKER,
                    },
                },
            )
            if call_payload != "echo:visible-result":
                raise AssertionError("tools_call did not relay the fixture upstream result")

            unavailable = gateway.request(
                "tools/call",
                {"name": "tools_schema", "arguments": {"tool": "ghost.missing"}},
            )
            if unavailable.get("error", {}).get("code") != -32001:
                raise AssertionError("unavailable upstream must be a structured refusal")

            audit_text = audit_path.read_text(encoding="utf-8")
            assert_no_markers(audit_text)
            if "echo:visible-result" in audit_text:
                raise AssertionError("audit log must not include upstream tool results")
            rows = [json.loads(line) for line in audit_text.splitlines() if line.strip()]
            if not any(row["tool"] == "tools_call" and row["ok"] for row in rows):
                raise AssertionError("audit log must contain a successful tools_call row")
            if not any(row["tool"] == "tools_schema" and not row["ok"] for row in rows):
                raise AssertionError("audit log must contain the unavailable-upstream refusal row")

            report = {
                "status": "passed",
                "skills_server": {
                    "serverInfo": skills_init["result"]["serverInfo"],
                    "tools": _tool_names(skills_listing),
                    "skills_search_metadata_only": True,
                    "skills_view_single_body": view_payload["name"],
                    "skills_use_logged": use_payload["use_logged"],
                    "malformed_request_refused": malformed_refusal["error"]["code"],
                    "unknown_tool_refused": unknown_refusal["error"]["code"],
                },
                "gateway": {
                    "serverInfo": gateway_init["result"]["serverInfo"],
                    "tools": _tool_names(gateway_listing),
                    "tools_search_no_schema_dump": True,
                    "tools_search_no_spawn": True,
                    "tools_schema_lazy_spawn": True,
                    "tools_call_result": call_payload,
                    "upstream_unavailable_refusal": unavailable["error"]["code"],
                    "audit_rows": len(rows),
                    "audit_redaction": True,
                },
                "boundaries": {
                    "no_full_tool_schema_dump": True,
                    "no_skill_body_in_search": True,
                    "no_private_pack_body_leak": True,
                    "no_token_private_key_proof_prompt_local_path_or_query_leak": True,
                    "production_hosted_calls": False,
                    "automatic_telemetry": False,
                    "oauth_upstreams": False,
                    "mcp_resources_or_prompts": False,
                },
            }
        finally:
            skills.close()
            gateway.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the fixture-only Unlimited Tools MCP stdio smoke.")
    parser.add_argument("--fixture-mode", action="store_true", help="Required explicit fixture mode; no hosted calls.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    args = parser.parse_args(argv)
    if not args.fixture_mode:
        raise SystemExit("--fixture-mode is required; MCP smoke never calls production hosted services.")
    repo = Path(__file__).resolve().parents[1]
    report = run_smoke(repo)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("MCP fixture smoke passed")
        print("skills:", ", ".join(report["skills_server"]["tools"]))
        print("gateway:", ", ".join(report["gateway"]["tools"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
