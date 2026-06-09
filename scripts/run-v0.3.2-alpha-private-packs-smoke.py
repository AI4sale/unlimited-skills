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
    print("Running v0.3.2-alpha private packs smoke")
    output = run([sys.executable, "scripts/run-private-team-pack-cross-repo-e2e.py", "--fixture-mode", "--temp-home", "--json"])
    payload = json.loads(output[output.find("{") :])
    if payload.get("status") != "passed":
        raise SystemExit("private team pack E2E did not pass")
    if payload.get("production_hosted_calls") is not False:
        raise SystemExit("private team pack smoke must not call production hosted services")
    if payload.get("wrong_agent_denied") is not True or payload.get("revoked_denied") is not True:
        raise SystemExit("private team pack smoke did not verify denial paths")
    if payload.get("local_skill_preserved") is not True:
        raise SystemExit("private team pack smoke did not verify local skill preservation")
    print("v0.3.2-alpha private packs smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
