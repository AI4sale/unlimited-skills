from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_managed_policy_sync_e2e_fixture_mode() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run-managed-policy-sync-e2e.py", "--fixture-mode", "--temp-home"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    assert "managed Enterprise policy sync E2E passed" in completed.stdout
    assert "production hosted calls: none" in completed.stdout
