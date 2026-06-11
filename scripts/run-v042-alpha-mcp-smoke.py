from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(command: list[str], repo: Path) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=repo, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the v0.4.2-alpha MCP smoke and boundary harness.")
    parser.add_argument("--fixture-mode", action="store_true", help="Required; no hosted calls are made.")
    args = parser.parse_args(argv)
    if not args.fixture_mode:
        raise SystemExit("--fixture-mode is required; v0.4.2 MCP smoke is fixture-only.")
    repo = Path(__file__).resolve().parents[1]
    py = sys.executable
    print("Running v0.4.2-alpha MCP fixture smoke", flush=True)
    run([py, "scripts/run-mcp-smoke.py", "--fixture-mode", "--json"], repo)
    run([py, "scripts/verify-mcp-boundaries.py", "--json"], repo)
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
    )
    print("v0.4.2-alpha MCP fixture smoke passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
