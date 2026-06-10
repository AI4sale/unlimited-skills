from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> str:
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
    return completed.stdout


def main() -> int:
    print("Running v0.3.4-alpha plans/billing integration smoke")
    output = run([sys.executable, "scripts/run-billing-lifecycle-cross-repo-e2e.py", "--fixture-mode", "--temp-home", "--json"])
    payload = json.loads(output[output.find("{") :])
    if payload.get("status") != "passed":
        raise SystemExit("billing lifecycle cross-repo E2E did not pass")
    if payload.get("production_hosted_calls") is not False:
        raise SystemExit("v0.3.4 smoke must not call production hosted services")
    if payload.get("billing_active_cli") != "active":
        raise SystemExit("v0.3.4 smoke did not verify active billing lifecycle status")
    if payload.get("billing_past_due_cli") != "past_due":
        raise SystemExit("v0.3.4 smoke did not verify past_due billing lifecycle status")
    if payload.get("billing_suspended_cli") != "suspended":
        raise SystemExit("v0.3.4 smoke did not verify suspended billing lifecycle status")
    if payload.get("entitlement_reconciled_to_business") is not True:
        raise SystemExit("v0.3.4 smoke did not verify business entitlement reconciliation")
    print("v0.3.4-alpha plans/billing integration smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
