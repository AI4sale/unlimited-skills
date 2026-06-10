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
    print("Running v0.3.6-alpha final release smoke")
    run([sys.executable, "scripts/run-v0.3.6-alpha-catalog-browser-release-smoke.py"])
    run([sys.executable, "scripts/verify-v0.3.6-alpha-publication.py"])
    print("v0.3.6-alpha final release smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
