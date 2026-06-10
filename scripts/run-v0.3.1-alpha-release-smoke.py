from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERRIDE_REASON = "Release owner explicitly accepts blocked production registry signing as a v0.3.1-alpha known issue."


def run(command: list[str], *, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )
    if expect_ok and completed.returncode != 0:
        print(completed.stdout)
        raise SystemExit(f"command failed with exit code {completed.returncode}: {' '.join(command)}")
    if not expect_ok and completed.returncode == 0:
        print(completed.stdout)
        raise SystemExit(f"command unexpectedly passed: {' '.join(command)}")
    return completed


def main() -> int:
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    blocked = run([sys.executable, "scripts/verify-v0.3.1-alpha-publication.py", "--expected-sha", head], expect_ok=False)
    if "production-signed registry artifacts are not verified" not in blocked.stdout:
        print(blocked.stdout)
        raise SystemExit("publication verifier did not fail on the production signing gate")
    run(
        [
            sys.executable,
            "scripts/verify-v0.3.1-alpha-publication.py",
            "--expected-sha",
            head,
            "--allow-registry-signing-blocked",
            "--release-owner-override-reason",
            OVERRIDE_REASON,
        ]
    )
    print("v0.3.1-alpha release smoke passed")
    print("production registry signing default gate: blocked")
    print("release-owner override path: passed")
    print("production hosted calls: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
