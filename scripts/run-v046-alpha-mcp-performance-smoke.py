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
RELEASE = "v0.4.6-alpha"
SMOKE_SIZE = 40
SMOKE_REPEATS = 2


def _load_perf_tests():
    path = ROOT / "tests" / "test_mcp_performance_benchmarks.py"
    spec = importlib.util.spec_from_file_location("v046_perf_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load performance test helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(command: list[str], *, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print("+ " + " ".join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        result.check_returncode()
    if not quiet and result.stdout:
        sys.stdout.write(result.stdout)
    return result


def _iter_strings(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, str):
        yield value


def _assert_report(report: dict[str, Any], json_text: str, md_text: str) -> dict[str, Any]:
    helpers = _load_perf_tests()
    schema = json.loads((ROOT / "schemas" / "mcp-perf-report.schema.json").read_text(encoding="utf-8"))
    validation_errors = helpers.validate(report, schema, schema)
    size = report["sizes"][0]
    warm = size["warm"]
    context = size["context_bytes"]
    required_sections = (
        "cold_start",
        "warm",
        "search",
        "indexing",
        "audit_overhead",
        "context_bytes",
        "memory",
    )
    secret_or_path_leaks: list[str] = []
    for text in _iter_strings(report):
        if helpers.looks_secret(text) or helpers._PATH_PATTERN.search(text):
            secret_or_path_leaks.append(text[:80])
    for line in md_text.splitlines():
        if helpers.looks_secret(line) or helpers._PATH_PATTERN.search(line):
            secret_or_path_leaks.append(line[:80])

    proofs = {
        "schema_valid": validation_errors == [],
        "sections_present": all(section in size for section in required_sections),
        "raw_samples_present": bool(size["cold_start"]["total"]["samples"])
        and bool(warm["first_schema"]["samples"])
        and bool(size["search"]["indexed_no_spawn"]["samples"]),
        "spawn_slower_than_reuse": warm["first_schema"]["median"] > warm["reuse_schema"]["median"]
        and warm["spawn_vs_reuse_ratio"] > 1.0,
        "context_bytes_consistent": context["full_all_schemas_dump"] > context["gateway_tools_list"]
        and context["full_all_schemas_dump"] > context["tools_search_response"]
        and context["full_all_schemas_dump"] > context["tools_schema_response"],
        "memory_best_effort": isinstance(size["memory"].get("available"), bool),
        "report_files_written": '"schema_version": 1' in json_text and "MCP performance" in md_text,
        "no_secret_or_local_path_leaks": not secret_or_path_leaks
        and "uls-mcp-perf" not in json_text
        and "uls-mcp-perf" not in md_text,
    }
    return {
        "status": "passed" if all(proofs.values()) else "failed",
        "proofs": proofs,
        "validation_errors": validation_errors,
        "tools_total": size["tools_total"],
        "repeats": report["repeats"],
        "spawn_vs_reuse_ratio": warm["spawn_vs_reuse_ratio"],
        "context_bytes": context,
    }


def collect_evidence(*, run_pytest: bool = False) -> dict[str, Any]:
    pytest_results: dict[str, str] = {}
    if run_pytest:
        run([sys.executable, "-m", "pytest", "tests/test_mcp_performance_benchmarks.py", "-q"], quiet=True)
        pytest_results["tests/test_mcp_performance_benchmarks.py"] = "passed"

    with tempfile.TemporaryDirectory(prefix="uls-v046-perf-smoke-") as temp:
        out_dir = Path(temp) / "perf"
        completed = run(
            [
                sys.executable,
                "scripts/run-mcp-performance-benchmarks.py",
                "--fixture-mode",
                "--json",
                "--sizes",
                str(SMOKE_SIZE),
                "--repeats",
                str(SMOKE_REPEATS),
                "--warmup",
                "1",
                "--out",
                str(out_dir),
            ],
            quiet=True,
        )
        report = json.loads(completed.stdout)
        json_text = (out_dir / "mcp-perf-report.json").read_text(encoding="utf-8")
        md_text = (out_dir / "mcp-perf-report.md").read_text(encoding="utf-8")

    benchmark = _assert_report(report, json_text, md_text)
    evidence: dict[str, Any] = {
        "status": benchmark["status"],
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
        "runtime_default_changes": False,
        "warm_start_implementation": False,
        "pytest": pytest_results,
        "benchmark": benchmark,
    }
    if evidence["status"] != "passed":
        raise AssertionError(json.dumps(evidence, indent=2, sort_keys=True))
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run v0.4.6-alpha MCP performance benchmark integration smoke.")
    parser.add_argument("--fixture-mode", action="store_true", help="Required; confirms no hosted or production dependencies")
    parser.add_argument("--json", action="store_true", help="Print JSON evidence")
    parser.add_argument("--run-pytest", action="store_true", help="Also run benchmark tests")
    args = parser.parse_args(argv)
    if not args.fixture_mode:
        parser.error("--fixture-mode is required")
    report = collect_evidence(run_pytest=args.run_pytest)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} MCP performance benchmark integration smoke passed")
        print(f"tools_total: {report['benchmark']['tools_total']}")
        print(f"spawn_vs_reuse_ratio: {report['benchmark']['spawn_vs_reuse_ratio']}")
        print("production hosted calls: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
