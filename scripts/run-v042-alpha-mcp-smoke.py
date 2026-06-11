from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load_script(name: str, function_name: str):
    script_path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(name.replace("-", "_").removesuffix(".py"), script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, function_name)


def run(command: list[str], repo: Path, *, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print("+ " + " ".join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=repo,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the v0.4.2-alpha MCP smoke and boundary harness.")
    parser.add_argument("--fixture-mode", action="store_true", help="Required; no hosted calls are made.")
    parser.add_argument("--json", action="store_true", help="Print a JSON evidence report.")
    args = parser.parse_args(argv)
    if not args.fixture_mode:
        raise SystemExit("--fixture-mode is required; v0.4.2 MCP smoke is fixture-only.")
    repo = Path(__file__).resolve().parents[1]
    py = sys.executable
    if not args.json:
        print("Running v0.4.2-alpha MCP fixture smoke", flush=True)
    run_smoke = _load_script("run-mcp-smoke.py", "run_smoke")
    smoke = run_smoke(repo)
    boundary_result = run([py, "scripts/verify-mcp-boundaries.py", "--json"], repo, quiet=True)
    run(
        [
            py,
            "-m",
            "pytest",
            "tests/test_mcp_server.py",
            "tests/test_mcp_gateway.py",
            "tests/integration/test_mcp_gateway_fixture.py",
            "-q",
        ],
        repo,
        quiet=args.json,
    )
    boundary = json.loads(boundary_result.stdout)
    report = {
        "status": "passed",
        "release": "v0.4.2-alpha",
        "mode": "fixture",
        "production_hosted_calls": False,
        "mcp_resources_or_prompts": False,
        "oauth_upstreams": False,
        "skills_server_transcript": smoke["skills_server"],
        "gateway_transcript": smoke["gateway"],
        "boundaries": smoke["boundaries"],
        "boundary_verifier": boundary,
        "pytest": {
            "tests/test_mcp_server.py": "passed",
            "tests/test_mcp_gateway.py": "passed",
            "tests/integration/test_mcp_gateway_fixture.py": "passed",
        },
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        print("v0.4.2-alpha MCP fixture smoke passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
