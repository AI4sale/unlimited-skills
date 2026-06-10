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
    # Accept release-runner compatibility flags. The smoke is fixture-only by design.
    allowed_args = {"--fixture-mode", "--temp-home"}
    unknown_args = [arg for arg in sys.argv[1:] if arg not in allowed_args]
    if unknown_args:
        raise SystemExit("unsupported arguments: " + ", ".join(unknown_args))
    print("Running v0.3.5-alpha community catalog integration smoke")
    run([sys.executable, "scripts/run-community-catalog-cross-repo-e2e.py", "--fixture-mode", "--temp-home", "--json"])
    run([sys.executable, "-m", "pytest", "tests/test_community.py", "-q"])
    print("v0.3.5-alpha community catalog integration smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
