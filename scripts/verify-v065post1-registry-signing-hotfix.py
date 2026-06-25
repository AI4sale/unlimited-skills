"""Verify the v0.6.5.post1 registry manifest signing hotfix release surface."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VERSION = "0.6.5.post1"
KEY_ID = "registry-prod-2026-06-25"
PUBLIC_KEY = "qoKlymz97CLckL4zIdjI2BjYxYPvvaLYBKcV153BNE4"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"v0.6.5.post1 registry signing hotfix verification failed: {message}")


def run_cmd(args: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def package_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', read(ROOT / "pyproject.toml"), re.MULTILINE)
    require(match is not None, "pyproject version is missing")
    return match.group(1)


def init_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', read(ROOT / "unlimited_skills" / "__init__.py"))
    require(match is not None, "__version__ is missing")
    return match.group(1)


def run_json(args: list[str], label: str, *, timeout: int = 900) -> dict[str, Any]:
    proc = run_cmd(args, timeout=timeout)
    require(proc.returncode == 0, f"{label} failed: " + proc.stdout[-1200:] + proc.stderr[-1200:])
    payload = json.loads(proc.stdout)
    require(isinstance(payload, dict), f"{label} must emit a JSON object")
    return payload


def assert_versions() -> None:
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")


def assert_bundled_trust() -> dict[str, Any]:
    from unlimited_skills.registration import base64_urlsafe_decode
    from unlimited_skills.signatures import trusted_manifest_key_records

    records = trusted_manifest_key_records(include_public=True)
    key_ids = [str(record.get("key_id") or "") for record in records]
    require(len(key_ids) == len(set(key_ids)), "bundled trusted manifest key ids must be unique")
    record = next((item for item in records if item.get("key_id") == KEY_ID), None)
    require(record is not None, f"missing bundled trust key {KEY_ID}")
    require(record.get("public_key") == PUBLIC_KEY, f"public key mismatch for {KEY_ID}")
    require(record.get("algorithm") == "ed25519", f"algorithm mismatch for {KEY_ID}")
    require(record.get("status") == "active", f"status mismatch for {KEY_ID}")
    require(len(base64_urlsafe_decode(str(record.get("public_key") or ""))) == 32, "public key must decode to 32 bytes")
    scopes = set(record.get("scopes") or [])
    require("community-catalog" in scopes, f"{KEY_ID} must allow community-catalog scope")
    require("catalog-updates" in scopes, f"{KEY_ID} must allow catalog-updates fallback scope")
    require(record.get("registry_origins") == ["https://unlimited.ai4.sale"], f"{KEY_ID} must be scoped to production registry origin")
    return {"key_id": KEY_ID, "scope_count": len(scopes), "registry_origins": record.get("registry_origins")}


def assert_workflow() -> None:
    text = read(ROOT / ".github" / "workflows" / "publish-pypi.yml")
    require('test "${{ github.event.inputs.version }}" = "0.6.5.post1"' in text, "publish workflow version guard must be 0.6.5.post1")
    require(
        'test "${{ github.event.inputs.confirm_pypi_publish }}" = "publish unlimited-skills 0.6.5.post1 to PyPI"' in text,
        "publish workflow confirmation guard must be exact for 0.6.5.post1",
    )
    require("python scripts/run-v065-alpha-package-smoke.py --expected-version 0.6.5.post1 --json" in text, "publish workflow must run package smoke for 0.6.5.post1")
    require("python scripts/verify-v065post1-registry-signing-hotfix.py" in text, "publish workflow must run this hotfix verifier")
    require("pypa/gh-action-pypi-publish@release/v1" in text, "publish workflow must use Trusted Publishing")
    require("PYPI_TOKEN" not in text and "TWINE_PASSWORD" not in text, "publish workflow must not use token/password publishing")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", default="")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--skip-package-smoke", action="store_true")
    parser.add_argument("--skip-frozen-contracts", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.expected_sha:
        head = run_cmd(["git", "rev-parse", "HEAD"]).stdout.strip()
        require(head == args.expected_sha, f"HEAD {head} does not match expected SHA {args.expected_sha}")
    if not args.allow_dirty:
        dirty = run_cmd(["git", "status", "--short"]).stdout.strip()
        require(not dirty, "working tree must be clean unless --allow-dirty is passed")

    assert_versions()
    trust = assert_bundled_trust()
    assert_workflow()

    package_smoke = None
    if not args.skip_package_smoke:
        package_smoke = run_json([sys.executable, "scripts/run-v065-alpha-package-smoke.py", "--expected-version", VERSION, "--json"], "package smoke", timeout=1200)
        require(package_smoke.get("ok") is True, "package smoke must pass")

    frozen_contracts = None
    if not args.skip_frozen_contracts:
        frozen_contracts = run_json([sys.executable, "scripts/verify-v06-frozen-contracts.py", "--expected-version", VERSION, "--json"], "frozen contracts")
        require(frozen_contracts.get("ok") is True, "frozen contracts must pass")

    payload = {
        "schema_version": 1,
        "release": "v0.6.5.post1-alpha",
        "version": VERSION,
        "status": "passed",
        "hotfix": "registry_manifest_signing_key_rotation",
        "bundled_trust": trust,
        "package_smoke": {"ok": True if package_smoke is None else package_smoke.get("ok")},
        "frozen_contracts": {"ok": True if frozen_contracts is None else frozen_contracts.get("ok")},
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("v0.6.5.post1 registry signing hotfix verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
