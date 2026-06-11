from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.5-alpha"


def _load_helpers():
    path = ROOT / "tests" / "test_mcp_audit_inspector.py"
    spec = importlib.util.spec_from_file_location("v045_audit_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load audit inspector helpers: {path}")
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


def _audit_path(root: Path) -> Path:
    return root / ".learning" / "mcp-audit.jsonl"


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cli_json(root: Path) -> dict[str, Any]:
    from unlimited_skills.cli import main

    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["--root", str(root), "mcp", "audit-report", "--json"])
    if code != 0:
        raise AssertionError(f"audit-report --json exited {code}: {err.getvalue()}")
    return json.loads(out.getvalue())


def _missing_log_exit(root: Path) -> dict[str, Any]:
    from unlimited_skills.cli import main

    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["--root", str(root), "mcp", "audit-report"])
    message = err.getvalue()
    return {
        "code": code,
        "clear_message": "Audit log not found" in message and "Run the gateway first" in message,
        "no_traceback": "Traceback" not in message,
    }


def collect_evidence(*, run_pytest: bool = False) -> dict[str, Any]:
    from unlimited_skills.mcp import audit_inspector as inspector
    from unlimited_skills.mcp.audit import AuditLog

    helpers = _load_helpers()
    pytest_results: dict[str, str] = {}
    if run_pytest:
        run([sys.executable, "-m", "pytest", "tests/test_mcp_audit_inspector.py", "-q"], quiet=True)
        pytest_results["tests/test_mcp_audit_inspector.py"] = "passed"

    schema = json.loads((ROOT / "schemas" / "mcp-audit-report.schema.json").read_text(encoding="utf-8"))
    secret = helpers.SECRET_BEARER
    local_path = helpers.SECRET_PATH

    with tempfile.TemporaryDirectory(prefix="uls-v045-audit-inspector-") as temp:
        root = Path(temp)
        path = _audit_path(root)
        log = helpers.build_basic_log(path)
        for index in range(4):
            log.record(
                "tools_call",
                f"up{index}",
                1.0,
                False,
                arguments={"tool": f"up{index}.t", "arguments": {"note": f"payload-{index}"}},
                error="UpstreamError: Upstream timed out on 'tools/call'.",
            )
        log.record(
            "tools_call",
            "github",
            3.0,
            True,
            arguments={"tool": "github.create_issue", "arguments": {"token": "uls_secret_x", "title": secret}},
        )

        before_digest = _file_digest(path)
        before_mtime = path.stat().st_mtime_ns
        report = inspector.build_report(path, recent=3)
        rendered = inspector.render_text(report, section="all")
        cli_report = _cli_json(root)
        after_digest = _file_digest(path)
        after_mtime = path.stat().st_mtime_ns

        validation_errors = helpers.validate(cli_report, schema)
        recent = report["refusals"]["recent"]
        recent_timestamps = [entry["ts"] for entry in recent]

        profile_path = root / ".learning" / "mcp-audit-profile.jsonl"
        helpers.build_basic_log(profile_path)
        helpers.write_profile_rows(profile_path)
        profile_report = inspector.build_report(profile_path)

        injected = root / ".learning" / "mcp-audit-injected.jsonl"
        AuditLog(injected).record("tools_call", "github", 1.0, True)
        helpers.write_raw_row(
            injected,
            ts=2000.0,
            tool="tools_call",
            upstream="github",
            duration_ms=1.0,
            ok=True,
            args={"arguments": {"note": secret}},
        )
        helpers.write_raw_row(
            injected,
            ts=2001.0,
            tool="tools_call",
            upstream="github",
            duration_ms=1.0,
            ok=False,
            error=local_path,
        )
        injected_report = inspector.build_report(injected)
        injected_text = inspector.render_text(injected_report, section="redaction")

        rotated = root / ".learning" / "mcp-audit-rotated.jsonl"
        helpers.write_raw_row(rotated.with_name(rotated.name + ".2"), ts=1.0, tool="tools_call", upstream="old", duration_ms=1.0, ok=True)
        helpers.write_raw_row(rotated.with_name(rotated.name + ".1"), ts=2.0, tool="tools_call", upstream="mid", duration_ms=1.0, ok=True)
        helpers.write_raw_row(rotated, ts=3.0, tool="tools_call", upstream="new", duration_ms=1.0, ok=True)
        rotated_report = inspector.build_report(rotated)

        missing = _missing_log_exit(root / "missing-root")

    dumped_report = json.dumps(report, sort_keys=True) + rendered
    dumped_injected = json.dumps(injected_report, sort_keys=True) + injected_text
    report_dict: dict[str, Any] = {
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
        "audit_log_writes": False,
        "pytest": pytest_results,
        "proofs": {
            "json_schema_valid": validation_errors == [],
            "summary_counts": {
                "rows_total": report["log"]["rows_total"],
                "total_calls": report["summary"]["total_calls"],
                "refusals": report["summary"]["refused_calls"],
                "malformed_lines": report["log"]["malformed_lines"],
            },
            "recent_refusals_safe": {
                "newest_first": recent_timestamps == sorted(recent_timestamps, reverse=True),
                "fields": sorted(recent[0].keys()) if recent else [],
                "upstreams": [entry["upstream"] for entry in recent],
                "payload_absent": "payload-3" not in dumped_report,
                "error_text_absent": "timed out on" not in json.dumps(recent, sort_keys=True).lower(),
            },
            "profiles": {
                "present": profile_report.get("profiles", {}).get("present") is True,
                "profile_loaded_count": len(profile_report.get("profiles", {}).get("profile_loaded_events", [])),
                "profile_refusals": profile_report.get("profiles", {}).get("profile_refusals"),
            },
            "redaction_clean_pass": {
                "status": report["redaction"]["status"],
                "suspects": report["redaction"]["suspects"],
                "secret_absent": secret not in dumped_report and "uls_secret_x" not in dumped_report,
            },
            "redaction_injected_fail_safe": {
                "status": injected_report["redaction"]["status"],
                "suspect_lines": [item["line"] for item in injected_report["redaction"]["suspects"]],
                "secret_values_absent": secret not in dumped_injected and "C:\\Users\\tedja" not in dumped_injected,
            },
            "rotated_logs": {
                "files_read": rotated_report["log"]["files_read"],
                "oldest_first": rotated_report["log"]["files_read"] == [
                    "mcp-audit-rotated.jsonl.2",
                    "mcp-audit-rotated.jsonl.1",
                    "mcp-audit-rotated.jsonl",
                ],
            },
            "missing_log": missing,
            "read_only": {
                "digest_unchanged": before_digest == after_digest,
                "mtime_unchanged": before_mtime == after_mtime,
            },
        },
    }
    return report_dict


def assert_evidence(report: dict[str, Any]) -> None:
    assert report["status"] == "passed"
    assert report["release"] == RELEASE
    for key in (
        "production_hosted_calls",
        "hosted_gateway",
        "oauth",
        "remote_upstreams",
        "mcp_resources",
        "mcp_prompts",
        "arbitrary_shell_execution",
        "automatic_telemetry",
        "audit_log_writes",
    ):
        assert report[key] is False
    proofs = report["proofs"]
    assert proofs["json_schema_valid"] is True
    assert proofs["recent_refusals_safe"]["newest_first"] is True
    assert proofs["recent_refusals_safe"]["fields"] == ["code", "name", "tool", "ts", "upstream"]
    assert proofs["recent_refusals_safe"]["payload_absent"] is True
    assert proofs["recent_refusals_safe"]["error_text_absent"] is True
    assert proofs["profiles"]["present"] is True
    assert proofs["profiles"]["profile_loaded_count"] == 1
    assert proofs["redaction_clean_pass"]["status"] == "PASS"
    assert proofs["redaction_clean_pass"]["suspects"] == []
    assert proofs["redaction_clean_pass"]["secret_absent"] is True
    assert proofs["redaction_injected_fail_safe"]["status"] == "FAIL"
    assert proofs["redaction_injected_fail_safe"]["suspect_lines"] == [2, 3]
    assert proofs["redaction_injected_fail_safe"]["secret_values_absent"] is True
    assert proofs["rotated_logs"]["oldest_first"] is True
    assert proofs["missing_log"] == {"code": 1, "clear_message": True, "no_traceback": True}
    assert proofs["read_only"] == {"digest_unchanged": True, "mtime_unchanged": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run v0.4.5-alpha MCP audit inspector integration smoke.")
    parser.add_argument("--fixture-mode", action="store_true", help="Required: run without production hosted calls.")
    parser.add_argument("--run-pytest", action="store_true", help="Also run the audit inspector unit tests.")
    parser.add_argument("--json", action="store_true", help="Print JSON evidence.")
    args = parser.parse_args(argv)
    if not args.fixture_mode:
        raise SystemExit("--fixture-mode is required; production hosted calls are not part of this smoke.")
    report = collect_evidence(run_pytest=args.run_pytest)
    assert_evidence(report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} MCP audit inspector smoke passed")
        print("JSON schema validation: passed")
        print("recent refusals omit argument/error payloads: passed")
        print("redaction self-check and safe suspect reporting: passed")
        print("rotated log discovery: passed")
        print("read-only inspection: passed")
        print("missing log exit: passed")
        print("production hosted calls: blocked by fixture-mode release commands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
