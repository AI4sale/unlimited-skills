from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V040_TAG_SHA = "4a3ee7d08be1167bbe37eba9cd7c73870d844ea1"


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
    print("Running v0.4.0-alpha final publication smoke", flush=True)
    run([sys.executable, "scripts/run-v0.2x-smoke-tests.py"])
    with tempfile.TemporaryDirectory(prefix="uls-v040-release-smoke-") as temp:
        temp_root = Path(temp)
        run(
            [
                sys.executable,
                "scripts/run-v040-alpha-e01-e04-cross-repo-e2e.py",
                "--fixture-mode",
                "--temp-home",
                "--json",
                "--out-json",
                str(temp_root / "e01-e04-report.json"),
                "--out-md",
                str(temp_root / "e01-e04-report.md"),
            ]
        )
    run([sys.executable, "scripts/verify-v040-alpha-e01-e04.py", "--expected-sha", sha])
    run(
        [
            sys.executable,
            "scripts/verify-v040-alpha-publication.py",
            "--expected-sha",
            sha,
            "--allow-existing-tag",
            "--expected-tag-sha",
            V040_TAG_SHA,
            "--allow-newer-package",
        ]
    )
    print("v0.4.0-alpha final publication smoke passed", flush=True)
    print(f"tag target sha: {sha}", flush=True)
    print(f"existing v0.4.0-alpha tag target: {V040_TAG_SHA}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
