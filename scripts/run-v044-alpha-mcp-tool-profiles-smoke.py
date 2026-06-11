from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.4-alpha"


def _load_helpers():
    path = ROOT / "tests" / "test_mcp_tool_profile_enforcement.py"
    spec = importlib.util.spec_from_file_location("v044_profile_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load profile helpers: {path}")
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


def _write_fixture(tmp: Path) -> dict[str, Path]:
    helpers = _load_helpers()
    script = tmp / "fake_upstream.py"
    script.write_text(helpers.FAKE_UPSTREAM, encoding="utf-8")
    marker = tmp / "spawned-fake.marker"
    other_marker = tmp / "spawned-other.marker"
    config = {
        "schema_version": 1,
        "upstreams": [
            {
                "name": "fake",
                "command": sys.executable,
                "args": [str(script), str(marker)],
                "tools": [
                    {"name": "echo", "description": "Echo text back"},
                    {"name": "add", "description": "Add two integers"},
                    {"name": "secret_wipe", "description": "Wipe the secret data storage"},
                ],
            },
            {
                "name": "other",
                "command": sys.executable,
                "args": [str(script), str(other_marker)],
                "tools": [{"name": "shred", "description": "Shred documents permanently"}],
            },
        ],
    }
    config_path = tmp / "gateway-config.json"
    profile_path = tmp / "tool-profiles.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    profile_path.write_text(json.dumps(helpers.PROFILE_DOCUMENT), encoding="utf-8")
    return {
        "config_path": config_path,
        "profile_path": profile_path,
        "marker": marker,
        "other_marker": other_marker,
        "audit": tmp / "mcp-audit.jsonl",
    }


def _gateway(paths: dict[str, Path], profile_name: str | None):
    from unlimited_skills.mcp.audit import AuditLog
    from unlimited_skills.mcp.gateway import Gateway, load_gateway_config
    from unlimited_skills.mcp.profiles import resolve_profile_state

    profile = None
    if profile_name is not None:
        profile = resolve_profile_state(paths["profile_path"], cli_name=profile_name, env_name="")
    return Gateway(load_gateway_config(paths["config_path"]), AuditLog(paths["audit"]), profile=profile)


def _audit_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def collect_evidence(*, run_pytest: bool = False) -> dict[str, Any]:
    from unlimited_skills.mcp.gateway import (
        PROFILE_INVALID,
        PROFILE_NOT_FOUND,
        TOOL_NOT_CALLABLE,
        TOOL_NOT_VISIBLE,
        build_gateway_registry,
    )
    from unlimited_skills.mcp.profiles import ActiveProfile, FailClosedProfile, resolve_profile_state

    pytest_results: dict[str, str] = {}
    if run_pytest:
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_mcp_tool_profile_schema.py",
                "tests/test_mcp_tool_profiles.py",
                "tests/test_mcp_gateway.py",
                "-q",
            ],
            quiet=True,
        )
        pytest_results[
            "tests/test_mcp_tool_profile_schema.py tests/test_mcp_tool_profiles.py tests/test_mcp_gateway.py"
        ] = "passed"

    with tempfile.TemporaryDirectory(prefix="uls-v044-profiles-") as temp:
        tmp = Path(temp)
        paths = _write_fixture(tmp)

        default_deny_gateway = _gateway(paths, "empty")
        try:
            default_search = default_deny_gateway.tools_search({"query": "echo"})
            default_message = _expect_error(
                lambda: default_deny_gateway.tools_call({"tool": "fake.echo", "arguments": {}}),
                TOOL_NOT_VISIBLE,
            )
            default_not_spawned = not paths["marker"].exists()
        finally:
            default_deny_gateway.shutdown()

        cli_profile = resolve_profile_state(paths["profile_path"], cli_name="reviewer", env_name="dev")
        env_profile = resolve_profile_state(paths["profile_path"], cli_name="", env_name="reviewer")
        if not isinstance(cli_profile, ActiveProfile) or not isinstance(env_profile, ActiveProfile):
            raise AssertionError("profile selection did not resolve active profiles")

        visible_gateway = _gateway(paths, "reviewer")
        try:
            echo_hits = visible_gateway.tools_search({"query": "echo text"})["hits"]
            add_hits = visible_gateway.tools_search({"query": "add integers"})["hits"]
            secret_hits = visible_gateway.tools_search({"query": "secret wipe"})["hits"]
            hidden_schema_message = _expect_error(
                lambda: visible_gateway.tools_schema({"tool": "fake.secret_wipe"}),
                TOOL_NOT_VISIBLE,
            )
            hidden_no_spawn = not paths["marker"].exists()
            non_callable_message = _expect_error(
                lambda: visible_gateway.tools_call({"tool": "fake.add", "arguments": {"a": 1, "b": 2}}),
                TOOL_NOT_CALLABLE,
            )
            non_callable_no_spawn = not paths["marker"].exists()
            schema = visible_gateway.tools_schema({"tool": "fake.add"})
            call = visible_gateway.tools_call({"tool": "fake.echo", "arguments": {"text": "ok"}})
        finally:
            visible_gateway.shutdown()

        narrow_gateway = _gateway(paths, "wide-child")
        try:
            inheritance_message = _expect_error(
                lambda: narrow_gateway.tools_schema({"tool": "fake.add"}),
                TOOL_NOT_VISIBLE,
            )
            inheritance_call = narrow_gateway.tools_call({"tool": "fake.echo", "arguments": {"text": "ok"}})
        finally:
            narrow_gateway.shutdown()

        missing_state = resolve_profile_state(paths["profile_path"], cli_name="ghost", env_name="")
        bad_profile_path = tmp / "bad-profiles.json"
        bad_profile_path.write_text(
            json.dumps({"schema_version": 1, "profiles": {"dev": {"visible": ["fake.create_*"]}}}),
            encoding="utf-8",
        )
        invalid_state = resolve_profile_state(bad_profile_path, cli_name="dev", env_name="")
        if not isinstance(missing_state, FailClosedProfile) or not isinstance(invalid_state, FailClosedProfile):
            raise AssertionError("fail-closed states did not resolve")

        if paths["audit"].exists():
            paths["audit"].unlink()
        audit_gateway = _gateway(paths, "reviewer")
        registry = build_gateway_registry(audit_gateway)
        try:
            registry["tools_search"]["handler"]({"query": "echo"})
            registry["tools_call"]["handler"]({"tool": "fake.echo", "arguments": {"text": "hello"}})
            _expect_error(
                lambda: registry["tools_call"]["handler"]({"tool": "fake.add", "arguments": {}}),
                TOOL_NOT_CALLABLE,
            )
        finally:
            audit_gateway.shutdown()
        rows = _audit_rows(paths["audit"])
        profile_loaded = rows[0]
        expected_sha = hashlib.sha256(paths["profile_path"].read_bytes()).hexdigest()
        registry_gateway = _gateway(paths, None)
        try:
            registry_names = sorted(build_gateway_registry(registry_gateway).keys())
        finally:
            registry_gateway.shutdown()

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
        "proofs": {
            "default_deny": {
                "hits": default_search["hits"],
                "code": TOOL_NOT_VISIBLE,
                "message": default_message,
                "not_spawned": default_not_spawned,
            },
            "selected_profile_by_cli": cli_profile.name == "reviewer",
            "selected_profile_by_env": env_profile.name == "reviewer",
            "visible_only_search": {
                "visible": [hit["tool"] for hit in echo_hits + add_hits],
                "hidden_hits": secret_hits,
                "view_only_marked": bool(add_hits and add_hits[0].get("callable") is False),
            },
            "hidden_schema_refusal": {
                "code": TOOL_NOT_VISIBLE,
                "message": hidden_schema_message,
                "not_spawned": hidden_no_spawn,
            },
            "non_callable_call_refusal": {
                "code": TOOL_NOT_CALLABLE,
                "message": non_callable_message,
                "not_spawned": non_callable_no_spawn,
                "schema_visible": schema["tool"] == "fake.add",
                "callable_tool_result": call.get("isError") is False,
            },
            "inheritance_narrowing": {
                "code": TOOL_NOT_VISIBLE,
                "message": inheritance_message,
                "callable_tool_result": inheritance_call.get("isError") is False,
            },
            "fail_closed": {
                "missing_code": missing_state.code,
                "invalid_code": invalid_state.code,
                "missing_expected": missing_state.code == PROFILE_NOT_FOUND,
                "invalid_expected": invalid_state.code == PROFILE_INVALID,
            },
            "profile_audit": {
                "profile_loaded_row": profile_loaded.get("tool") == "profile_loaded",
                "profile": profile_loaded.get("profile"),
                "profile_sha256": profile_loaded.get("profile_sha256"),
                "profile_sha256_expected": expected_sha,
                "calls_carry_profile": all(row.get("profile") == "reviewer" for row in rows),
            },
            "no_resources_or_prompts": registry_names == ["tools_call", "tools_schema", "tools_search"],
        },
    }
    checks = {
        "default_deny_hits": report["proofs"]["default_deny"]["hits"] == [],
        "default_deny_not_spawned": report["proofs"]["default_deny"]["not_spawned"],
        "selected_profile_by_cli": report["proofs"]["selected_profile_by_cli"],
        "selected_profile_by_env": report["proofs"]["selected_profile_by_env"],
        "visible_only_search": report["proofs"]["visible_only_search"]["visible"] == ["fake.echo", "fake.add"],
        "visible_only_hidden_hits": report["proofs"]["visible_only_search"]["hidden_hits"] == [],
        "view_only_marked": report["proofs"]["visible_only_search"]["view_only_marked"],
        "hidden_schema_not_spawned": report["proofs"]["hidden_schema_refusal"]["not_spawned"],
        "non_callable_not_spawned": report["proofs"]["non_callable_call_refusal"]["not_spawned"],
        "schema_visible": report["proofs"]["non_callable_call_refusal"]["schema_visible"],
        "callable_tool_result": report["proofs"]["non_callable_call_refusal"]["callable_tool_result"],
        "inheritance_call_result": report["proofs"]["inheritance_narrowing"]["callable_tool_result"],
        "missing_fail_closed": report["proofs"]["fail_closed"]["missing_expected"],
        "invalid_fail_closed": report["proofs"]["fail_closed"]["invalid_expected"],
        "profile_loaded_row": report["proofs"]["profile_audit"]["profile_loaded_row"],
        "profile_name": report["proofs"]["profile_audit"]["profile"] == "reviewer",
        "profile_sha": report["proofs"]["profile_audit"]["profile_sha256"]
        == report["proofs"]["profile_audit"]["profile_sha256_expected"],
        "calls_carry_profile": report["proofs"]["profile_audit"]["calls_carry_profile"],
        "no_resources_or_prompts": report["proofs"]["no_resources_or_prompts"],
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise AssertionError("v0.4.4 profile enforcement smoke evidence is incomplete: " + ", ".join(failed))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the v0.4.4-alpha MCP tool-profile fixture smoke.")
    parser.add_argument("--fixture-mode", action="store_true", help="Required; no hosted calls are made.")
    parser.add_argument("--json", action="store_true", help="Print a JSON evidence report.")
    args = parser.parse_args(argv)
    if not args.fixture_mode:
        raise SystemExit("--fixture-mode is required; v0.4.4 MCP tool-profile smoke is fixture-only.")
    report = collect_evidence(run_pytest=True)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
