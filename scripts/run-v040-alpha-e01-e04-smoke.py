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


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    e2e_args = args if args else ["--fixture-mode", "--temp-home"]
    print("Running v0.4.0-alpha E01-E04 integration smoke")
    run([sys.executable, "scripts/run-v040-alpha-e01-e04-cross-repo-e2e.py", *e2e_args, "--json"])
    run([sys.executable, "scripts/verify-v040-alpha-e01-e04.py"])
    print("v0.4.0-alpha E01-E04 integration smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
