from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(
            "command failed: "
            + " ".join(command)
            + "\nstdout:\n"
            + completed.stdout
            + "\nstderr:\n"
            + completed.stderr
        )
    print(completed.stdout, end="")


def main() -> int:
    print("Running v0.3.0-alpha release smoke")
    run([sys.executable, "scripts/run-managed-policy-sync-e2e.py", "--fixture-mode", "--temp-home"])
    print("v0.3.0-alpha release smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
