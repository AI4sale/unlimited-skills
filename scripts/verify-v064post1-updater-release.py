"""Verify the v0.6.4.post1 updater repair release package is publishable."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.6.4.post1"
VERSION = "0.6.4.post1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"{RELEASE} release verification failed: {message}")


def run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )


def package_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', read(ROOT / "pyproject.toml"), re.MULTILINE)
    require(match is not None, "pyproject version is missing")
    return match.group(1)


def init_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', read(ROOT / "unlimited_skills" / "__init__.py"))
    require(match is not None, "__version__ is missing")
    return match.group(1)


def assert_metadata() -> None:
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")


def assert_workflow() -> None:
    text = read(ROOT / ".github" / "workflows" / "publish-pypi.yml")
    require('test "${{ github.event.inputs.version }}" = "0.6.4.post1"' in text, "publish workflow version guard must be 0.6.4.post1")
    require(
        'test "${{ github.event.inputs.confirm_pypi_publish }}" = "publish unlimited-skills 0.6.4.post1 to PyPI"' in text,
        "publish workflow confirmation guard must be exact for 0.6.4.post1",
    )
    require(
        "python scripts/run-v064-alpha-package-smoke.py --expected-version 0.6.4.post1 --json" in text,
        "publish workflow must run package smoke for 0.6.4.post1",
    )
    require(
        "python scripts/run-v064post1-updater-smoke.py --json" in text,
        "publish workflow must run updater smoke",
    )
    require(
        "python scripts/verify-v064post1-updater-release.py" in text,
        "publish workflow must run this prepublish verifier",
    )
    require("pypa/gh-action-pypi-publish@release/v1" in text, "publish workflow must use Trusted Publishing")
    require("PYPI_TOKEN" not in text and "TWINE_PASSWORD" not in text, "publish workflow must not use token/password publishing")


def assert_yanked_064_notice() -> None:
    known_issues = read(ROOT / "docs" / "releases" / "v0.6.4-alpha-known-issues.md").lower()
    audit = read(ROOT / "docs" / "reports" / "v0.6.4-money-saved-truth-audit.md").lower()
    joined = known_issues + "\n" + audit
    require("context/token proxy" in joined, "known issue must still document the v0.6.4 proxy-savings truth gap")
    require("does not compute dollar savings" in joined, "known issue must still say v0.6.4 does not compute dollar savings")


def run_json(args: list[str], label: str) -> dict[str, Any]:
    proc = run_cmd(args)
    require(proc.returncode == 0, f"{label} failed: {proc.stdout[-1200:]}{proc.stderr[-1200:]}")
    payload = json.loads(proc.stdout)
    require(isinstance(payload, dict), f"{label} must emit a JSON object")
    require(payload.get("ok") is True, f"{label} returned ok=false")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", default="", help="Optional exact HEAD SHA selected for release execution.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow local dirty tree while verifying a PR under construction.")
    parser.add_argument("--skip-package-smoke", action="store_true")
    parser.add_argument("--skip-updater-smoke", action="store_true")
    parser.add_argument("--skip-frozen-contracts", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.expected_sha:
        head = run_cmd(["git", "rev-parse", "HEAD"]).stdout.strip()
        require(head == args.expected_sha, f"HEAD {head} does not match expected SHA {args.expected_sha}")
    if not args.allow_dirty:
        dirty = run_cmd(["git", "status", "--short"]).stdout.strip()
        require(not dirty, "working tree must be clean unless --allow-dirty is passed")

    assert_metadata()
    assert_workflow()
    assert_yanked_064_notice()
    package_smoke = (
        {"ok": True, "skipped": True}
        if args.skip_package_smoke
        else run_json([sys.executable, "scripts/run-v064-alpha-package-smoke.py", "--expected-version", VERSION, "--json"], "package smoke")
    )
    updater_smoke = (
        {"ok": True, "skipped": True}
        if args.skip_updater_smoke
        else run_json([sys.executable, "scripts/run-v064post1-updater-smoke.py", "--json"], "updater smoke")
    )
    frozen_contracts = (
        {"ok": True, "skipped": True}
        if args.skip_frozen_contracts
        else run_json([sys.executable, "scripts/verify-v06-frozen-contracts.py", "--expected-version", VERSION, "--json"], "frozen contracts")
    )
    payload = {
        "schema_version": 1,
        "release": RELEASE,
        "version": VERSION,
        "status": "passed",
        "package_smoke": {"ok": package_smoke.get("ok"), "skipped": package_smoke.get("skipped", False)},
        "updater_smoke": {"ok": updater_smoke.get("ok"), "skipped": updater_smoke.get("skipped", False)},
        "frozen_contracts": {"ok": frozen_contracts.get("ok"), "skipped": frozen_contracts.get("skipped", False)},
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} release verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
