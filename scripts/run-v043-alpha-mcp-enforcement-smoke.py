from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.3-alpha"


def _load_enforcement_helpers():
    path = ROOT / "tests" / "test_mcp_upstream_enforcement.py"
    spec = importlib.util.spec_from_file_location("v043_enforcement_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load enforcement helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(command: list[str], *, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print("+ " + " ".join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=quiet,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        if quiet:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
        result.check_returncode()
    return result


def _expect_error(func, code: int) -> str:
    from unlimited_skills.mcp.gateway import UpstreamError

    try:
        func()
    except UpstreamError as exc:
        if exc.code != code:
            raise AssertionError(f"Expected refusal {code}, got {exc.code}: {exc}") from exc
        return str(exc)
    raise AssertionError(f"Expected refusal {code}")


def _expect_config_error(func) -> str:
    from unlimited_skills.mcp.gateway import GatewayConfigError

    try:
        func()
    except GatewayConfigError as exc:
        return str(exc)
    raise AssertionError("Expected GatewayConfigError")


def collect_evidence(*, run_pytest: bool = False) -> dict[str, Any]:
    from unlimited_skills.mcp.audit import AuditLog, REDACTED
    from unlimited_skills.mcp.gateway import (
        COMMAND_NOT_ALLOWED,
        ENV_FORWARDING_DENIED,
        RESPONSE_TOO_LARGE,
        SCHEMA_TOO_LARGE,
        TRUST_LEVEL_VIOLATION,
        UPSTREAM_DISABLED,
        Gateway,
        UpstreamClient,
        build_gateway_registry,
        load_gateway_config,
    )

    helpers = _load_enforcement_helpers()
    pytest_results: dict[str, str] = {}
    if run_pytest:
        run([sys.executable, "-m", "pytest", "tests/test_mcp_upstream_enforcement.py", "-q"], quiet=True)
        pytest_results["tests/test_mcp_upstream_enforcement.py"] = "passed"

    with tempfile.TemporaryDirectory(prefix="uls-v043-mcp-") as temp:
        tmp = Path(temp)
        script = helpers.write_upstream_script(tmp)

        disabled_marker = tmp / "disabled.spawned"
        disabled_gateway = helpers.gateway_from_config(
            tmp,
            {
                "upstreams": [
                    helpers.upstream_spec(
                        script,
                        disabled_marker,
                        enabled=False,
                        tools=[{"name": "echo", "description": "Echo text back"}],
                    )
                ]
            },
        )
        try:
            disabled_search = disabled_gateway.tools_search({"query": "echo"})
            disabled_message = _expect_error(
                lambda: disabled_gateway.tools_schema({"tool": "fake.echo"}),
                UPSTREAM_DISABLED,
            )
        finally:
            disabled_gateway.shutdown()

        future_marker = tmp / "future.spawned"
        future_gateway = helpers.gateway_from_config(
            tmp,
            {
                "upstreams": [
                    helpers.upstream_spec(
                        script,
                        future_marker,
                        trust_level="future-remote-placeholder",
                        tools=[{"name": "search_web", "description": "Search the web"}],
                    )
                ]
            },
        )
        try:
            future_search = future_gateway.tools_search({"query": "web"})
            future_message = _expect_error(
                lambda: future_gateway.tools_call({"tool": "fake.search_web", "arguments": {}}),
                TRUST_LEVEL_VIOLATION,
            )
        finally:
            future_gateway.shutdown()

        command_message = _expect_error(
            lambda: UpstreamClient({"name": "shell", "command": "bash", "trust_level": "local-trusted"})._validate_command(),
            COMMAND_NOT_ALLOWED,
        )

        env_runtime_gateway = Gateway(
            {"upstreams": [helpers.upstream_spec(script, env_allowlist=["TOKEN_*"])]},
            AuditLog(tmp / "env-runtime-audit.jsonl"),
        )
        try:
            env_runtime_message = _expect_error(
                lambda: env_runtime_gateway.tools_schema({"tool": "fake.echo"}),
                ENV_FORWARDING_DENIED,
            )
        finally:
            env_runtime_gateway.shutdown()
        env_config_path = tmp / "env-config.json"
        env_config_path.write_text(
            json.dumps({"upstreams": [{"name": "wild", "command": str(script), "env_allowlist": ["AWS_*"]}]}),
            encoding="utf-8",
        )
        env_config_message = _expect_config_error(lambda: load_gateway_config(env_config_path))

        schema_gateway = helpers.gateway_from_config(
            tmp,
            {"upstreams": [helpers.upstream_spec(script, max_schema_bytes=2048)]},
        )
        try:
            schema_message = _expect_error(
                lambda: schema_gateway.tools_schema({"tool": "fake.huge_schema"}),
                SCHEMA_TOO_LARGE,
            )
        finally:
            schema_gateway.shutdown()

        response_gateway = helpers.gateway_from_config(
            tmp,
            {"upstreams": [helpers.upstream_spec(script, max_response_bytes=65536)]},
        )
        try:
            response_message = _expect_error(
                lambda: response_gateway.tools_call({"tool": "fake.blob", "arguments": {}}),
                RESPONSE_TOO_LARGE,
            )
        finally:
            response_gateway.shutdown()

        timeout_config_path = tmp / "timeout-config.json"
        timeout_config_path.write_text(
            json.dumps(
                {
                    "upstreams": [{"name": "slow", "command": str(script), "request_timeout_seconds": 301}]
                }
            ),
            encoding="utf-8",
        )
        timeout_message = _expect_config_error(lambda: load_gateway_config(timeout_config_path))

        audit_path = tmp / "mcp-audit.jsonl"
        audit = AuditLog(audit_path, max_bytes=400, max_files=2)
        for index in range(60):
            audit.record(
                tool="tools_call",
                upstream="fake",
                duration_ms=1,
                ok=index % 7 != 0,
                arguments={
                    "tool": f"fake.echo_{index}",
                    "api_token": "tok_live_value",
                    "prompt": "should not be written",
                    "local_path": r"C:\Users\example\secret.txt",
                },
                error=r"failed at C:\Users\example\secret.txt",
            )
        audit_files = [audit_path, tmp / "mcp-audit.jsonl.1", tmp / "mcp-audit.jsonl.2"]
        audit_text = "\n".join(path.read_text(encoding="utf-8") for path in audit_files if path.exists())
        audit_redaction = (
            REDACTED in audit_text
            and "tok_live_value" not in audit_text
            and "should not be written" not in audit_text
            and r"C:\Users\example" not in audit_text
        )
        audit_rotation = audit_path.exists() and (tmp / "mcp-audit.jsonl.1").exists() and (tmp / "mcp-audit.jsonl.2").exists() and not (tmp / "mcp-audit.jsonl.3").exists()

        registry = build_gateway_registry(Gateway({"upstreams": []}, AuditLog(tmp / "empty-audit.jsonl")))
        gateway_tool_names = sorted(registry.keys())

    report: dict[str, Any] = {
        "status": "passed",
        "release": RELEASE,
        "mode": "fixture",
        "production_hosted_calls": False,
        "hosted_gateway": False,
        "oauth": False,
        "remote_upstreams": False,
        "mcp_resources": False,
        "mcp_prompts": False,
        "arbitrary_shell_execution": False,
        "automatic_telemetry": False,
        "pytest": pytest_results,
        "gateway_tools": gateway_tool_names,
        "proofs": {
            "disabled_refusal": {
                "code": UPSTREAM_DISABLED,
                "not_indexed": disabled_search["hits"] == [],
                "not_spawned": not disabled_marker.exists(),
                "message_mentions_disabled": "disabled" in disabled_message.lower(),
            },
            "future_remote_refusal": {
                "code": TRUST_LEVEL_VIOLATION,
                "not_indexed": future_search["hits"] == [],
                "not_spawned": not future_marker.exists(),
                "message_mentions_unopened_gate": "gate" in future_message.lower(),
            },
            "command_not_allowed": {"code": COMMAND_NOT_ALLOWED, "message": command_message},
            "env_forwarding_denied": {
                "code": ENV_FORWARDING_DENIED,
                "runtime_message": env_runtime_message,
                "config_message": env_config_message,
            },
            "schema_too_large": {"code": SCHEMA_TOO_LARGE, "message": schema_message, "no_schema_content": "BBBB" not in schema_message},
            "response_too_large": {"code": RESPONSE_TOO_LARGE, "message": response_message, "no_response_content": "yyyy" not in response_message},
            "timeout_hard_bound": {"message": timeout_message, "request_timeout_seconds_max": 300},
            "audit_rotation": audit_rotation,
            "audit_redaction": audit_redaction,
            "no_resources_or_prompts": gateway_tool_names == ["tools_call", "tools_schema", "tools_search"],
            "no_shell_execution": True,
        },
    }
    if not all(
        [
            report["proofs"]["disabled_refusal"]["not_indexed"],
            report["proofs"]["disabled_refusal"]["not_spawned"],
            report["proofs"]["future_remote_refusal"]["not_indexed"],
            report["proofs"]["future_remote_refusal"]["not_spawned"],
            report["proofs"]["schema_too_large"]["no_schema_content"],
            report["proofs"]["response_too_large"]["no_response_content"],
            report["proofs"]["audit_rotation"],
            report["proofs"]["audit_redaction"],
            report["proofs"]["no_resources_or_prompts"],
        ]
    ):
        raise AssertionError("v0.4.3 enforcement smoke evidence is incomplete")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the v0.4.3-alpha MCP enforcement fixture smoke.")
    parser.add_argument("--fixture-mode", action="store_true", help="Required; no hosted calls are made.")
    parser.add_argument("--json", action="store_true", help="Print a JSON evidence report.")
    args = parser.parse_args(argv)
    if not args.fixture_mode:
        raise SystemExit("--fixture-mode is required; v0.4.3 MCP enforcement smoke is fixture-only.")
    report = collect_evidence(run_pytest=True)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        print("v0.4.3-alpha MCP enforcement fixture smoke passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
