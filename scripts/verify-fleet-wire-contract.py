from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> dict:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def main() -> int:
    checks = [
        run([sys.executable, "scripts/generate-fleet-contract-fixtures.py"]),
        run([sys.executable, "scripts/generate-fleet-contract-manifest.py"]),
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_fleet_contract.py",
                "tests/test_fleet_reconciler.py",
                "-q",
            ]
        ),
    ]
    result = {
        "check": "fleet-wire-contract-v1",
        "ok": all(item["returncode"] == 0 for item in checks),
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
