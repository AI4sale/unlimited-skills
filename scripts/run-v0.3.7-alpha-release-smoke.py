from __future__ import annotations

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
    print("Running v0.3.7-alpha final publication smoke")
    run([sys.executable, "scripts/run-v0.3.7-alpha-catalog-feedback-smoke.py"])
    run([sys.executable, "scripts/verify-v0.3.7-alpha-catalog-feedback.py"])
    run([sys.executable, "scripts/verify-v0.3.7-alpha-publication.py"])
    print("v0.3.7-alpha final publication smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
