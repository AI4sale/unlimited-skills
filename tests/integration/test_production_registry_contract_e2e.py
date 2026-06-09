from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_production_registry_contract_e2e_fixture() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run-production-registry-contract-e2e.py"), "--fixture-mode", "--temp-home"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "production registry contract E2E passed" in completed.stdout
    assert "device proof missing/invalid/replay rejection: ok" in completed.stdout
