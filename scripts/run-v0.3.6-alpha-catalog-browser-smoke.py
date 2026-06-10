from __future__ import annotations

import json
import os
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


def json_payload(output: str) -> dict:
    start = output.find("{")
    if start < 0:
        raise SystemExit("command did not emit JSON payload")
    payload = json.loads(output[start:])
    if not isinstance(payload, dict):
        raise SystemExit("command emitted non-object JSON payload")
    return payload


def assert_catalog_payload(payload: dict, *, expected_mode: str) -> None:
    if payload.get("status") != "passed":
        raise SystemExit(f"catalog browser smoke did not pass in {expected_mode} mode")
    if payload.get("mode") != expected_mode:
        raise SystemExit(f"catalog browser smoke mode mismatch: expected {expected_mode}, got {payload.get('mode')}")
    for key in ("approved_only_visibility", "signed_metadata_verified", "metadata_only_preview", "dry_run_install_verified"):
        if payload.get(key) is not True:
            raise SystemExit(f"catalog browser smoke missing proof: {key}")
    if payload.get("production_hosted_calls") is not False:
        raise SystemExit("catalog browser smoke must not call production hosted services")


def main() -> int:
    print("Running v0.3.6-alpha catalog browser smoke")
    fixture = json_payload(run([sys.executable, "scripts/run-catalog-browser-cross-repo-e2e.py", "--fixture-mode", "--temp-home", "--json"]))
    assert_catalog_payload(fixture, expected_mode="public-fixture")

    registry_repo = Path(os.environ.get("UNLIMITED_SKILLS_REGISTRY_REPO", r"D:\git\unlimited-skills-registry"))
    local_registry_status = "skipped"
    if (registry_repo / "unlimited_registry" / "production_api.py").is_file():
        local_registry = json_payload(
            run(
                [
                    sys.executable,
                    "scripts/run-catalog-browser-cross-repo-e2e.py",
                    "--local-registry",
                    "--registry-repo",
                    str(registry_repo),
                    "--temp-home",
                    "--json",
                ]
            )
        )
        assert_catalog_payload(local_registry, expected_mode="local-registry")
        local_registry_status = "passed"
    print(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "fixture_mode": "passed",
                "local_registry_mode": local_registry_status,
                "registry_repo": str(registry_repo),
                "production_hosted_calls": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    print("v0.3.6-alpha catalog browser smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
