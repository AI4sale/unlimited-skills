from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def current_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.strip()


def main() -> int:
    sha = current_sha()
    print("Running v0.4.3-alpha MCP upstream enforcement publication smoke", flush=True)
    run([sys.executable, "scripts/run-v0.2x-smoke-tests.py"])
    run([sys.executable, "scripts/run-v042-alpha-release-smoke.py"])
    run([sys.executable, "scripts/run-v043-alpha-mcp-enforcement-smoke.py", "--fixture-mode", "--json"])
    run([sys.executable, "scripts/verify-v043-alpha-mcp-enforcement.py", "--expected-sha", sha])
    run([sys.executable, "scripts/verify-v043-alpha-publication.py", "--expected-sha", sha])
    print("v0.4.3-alpha MCP upstream enforcement publication smoke passed", flush=True)
    print(f"tag target sha: {sha}", flush=True)
    print("tag status: pending Codex publication after verifier", flush=True)
    print("production hosted calls: blocked by fixture-mode release commands", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
