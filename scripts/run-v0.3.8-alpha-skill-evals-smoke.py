from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print("+ " + " ".join(command))
    completed = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run v0.3.8-alpha skill evaluations smoke.")
    parser.add_argument("--fixture-mode", action="store_true")
    parser.add_argument("--temp-home", action="store_true")
    args = parser.parse_args()
    command = [sys.executable, "scripts/run-skill-evals-cross-repo-e2e.py"]
    if args.fixture_mode:
        command.append("--fixture-mode")
    if args.temp_home:
        command.append("--temp-home")
    command.append("--json")
    print("Running v0.3.8-alpha skill evaluations smoke")
    run(command)
    print("v0.3.8-alpha skill evaluations smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
