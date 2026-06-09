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
    print("Running v0.3.3-alpha org/team governance smoke")
    output = run([sys.executable, "scripts/run-private-team-pack-cross-repo-e2e.py", "--fixture-mode", "--temp-home", "--json"])
    payload = json.loads(output[output.find("{") :])
    if payload.get("status") != "passed":
        raise SystemExit("cross-repo E2E did not pass")
    if payload.get("production_hosted_calls") is not False:
        raise SystemExit("v0.3.3 smoke must not call production hosted services")
    if payload.get("cli_access_check_denied") is not True:
        raise SystemExit("v0.3.3 smoke did not verify public CLI access-check denial")
    if payload.get("cli_org_status_cache") is not True:
        raise SystemExit("v0.3.3 smoke did not verify public CLI org status cache")
    governance = payload.get("registry_org_governance") if isinstance(payload.get("registry_org_governance"), dict) else {}
    if governance.get("entitlement_plan") != "business" or governance.get("private_pack_owned") is not True:
        raise SystemExit("v0.3.3 smoke did not verify private registry org/team governance")
    print("v0.3.3-alpha org/team governance smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
