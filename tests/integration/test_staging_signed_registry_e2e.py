from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_staging_signed_registry_e2e_fixture_mode() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run-staging-registry-e2e.py",
            "--fixture-mode",
            "--temp-home",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    assert "staging signed registry E2E passed" in completed.stdout
    assert "production hosted calls: none" in completed.stdout
