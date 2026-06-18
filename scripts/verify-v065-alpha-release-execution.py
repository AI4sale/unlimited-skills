"""Verify the v0.6.5-alpha retrieval/learning reliability release package."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.6.5-alpha"
VERSION = "0.6.5"
MANIFEST = ROOT / "docs" / "releases" / "v0.6.5-alpha.release-manifest.json"
REQUIRED_DOCS = [
    ROOT / "docs" / "releases" / "v0.6.5-alpha.md",
    ROOT / "docs" / "releases" / "v0.6.5-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.6.5-alpha-upgrade-notes.md",
    ROOT / "docs" / "releases" / "v0.6.5-alpha-known-issues.md",
    ROOT / "docs" / "releases" / "v0.6.5-alpha-pypi-publishing.md",
    ROOT / "docs" / "releases" / "v0.6.5-personal-verification.md",
    ROOT / "docs" / "reports" / "v0.6.5-release-decision-package.md",
    ROOT / "README-pypi.md",
    ROOT / "CHANGELOG.md",
    MANIFEST,
]

FORBIDDEN_CLAIMS = [
    "new paid tier",
    "hosted dashboard",
    "marketplace",
    "enterprise governance",
    "billing",
    "exact revenue",
    "exact money claim",
    "search is perfect",
    "all skills always top-1",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"{RELEASE} release execution verification failed: {message}")


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


def assert_metadata() -> None:
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")


def assert_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_version") == VERSION, "manifest package version mismatch")
    require(payload.get("status") == "release_execution_ready", "manifest status must be release_execution_ready")
    require(payload.get("distribution") == "retrieval-learning-reliability", "manifest distribution mismatch")

    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(git.get("tag_status") == "blocked_until_pypi_upload_clean_install_and_post_publish_verifier", "manifest tag must be blocked until PyPI clean install and post-publish verifier")

    execution = payload.get("release_execution") if isinstance(payload.get("release_execution"), dict) else {}
    require(execution.get("package_ready") is True, "manifest must state package_ready=true")
    require(execution.get("executed_in_this_pr") is False, "manifest must state publish/tag is not executed in this PR")

    required_files = set(payload.get("release_package_files") or [])
    scripts = set(payload.get("verifier_scripts") or [])
    tests = set(payload.get("tests") or [])
    for raw in (
        "docs/releases/v0.6.5-alpha.md",
        "docs/releases/v0.6.5-alpha.release-manifest.json",
        "docs/releases/v0.6.5-alpha-checklist.md",
        "docs/releases/v0.6.5-alpha-upgrade-notes.md",
        "docs/releases/v0.6.5-alpha-known-issues.md",
        "docs/releases/v0.6.5-alpha-pypi-publishing.md",
        "docs/releases/v0.6.5-personal-verification.md",
        "docs/reports/v0.6.5-release-decision-package.md",
    ):
        require(raw in required_files, f"manifest missing release package file {raw}")
    for raw in (
        "scripts/verify-v065-retrieval-learning-release-smoke.py",
        "scripts/verify-v065-alpha-release-execution.py",
        "scripts/run-v065-alpha-package-smoke.py",
    ):
        require(raw in scripts, f"manifest missing verifier script {raw}")
    require("tests/test_v065_release_package.py" in tests, "manifest missing v065 release package test")
    require(195 in (payload.get("held_prs") or []), "#195 must remain HOLD")
    require(119 in (payload.get("excluded_prs") or []), "#119 must remain excluded")
    return payload


def assert_docs() -> None:
    for path in REQUIRED_DOCS:
        require(path.is_file(), f"missing required doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in REQUIRED_DOCS)
    lower = text.lower()

    for required in (
        "v0.6.5-alpha",
        "unlimited-skills==0.6.5",
        "technical-debt / reliability release",
        "zero-candidate delivery fixed",
        "recall-first candidate delivery",
        "shared candidate family",
        "learning loop repaired",
        "100-step / 10-phase",
        "combined release smoke",
        "python scripts/verify-v065-retrieval-learning-release-smoke.py --json",
        "python scripts/verify-v065-alpha-release-execution.py --json",
        "python scripts/run-v065-alpha-package-smoke.py --json",
        "python scripts/verify-v06-frozen-contracts.py --expected-version 0.6.5 --json",
        "no pypi publish",
        "no tag",
        "no github release",
        "no marketplace",
        "no hosted rollout",
        "no paid-tier work",
        "#195",
        "#119",
    ):
        require(required in lower, f"release docs missing required wording: {required}")

    for forbidden in FORBIDDEN_CLAIMS:
        negated = (
            f"no {forbidden}" in lower
            or f"- {forbidden}" in lower
            or f"no claim that {forbidden}" in lower
            or f"does not claim {forbidden}" in lower
        )
        require(forbidden not in lower or negated, f"release docs contain unsafe claim: {forbidden}")


def assert_workflow() -> None:
    text = read(ROOT / ".github" / "workflows" / "publish-pypi.yml")
    require('test "${{ github.event.inputs.version }}" = "0.6.5"' in text, "publish workflow version guard must be 0.6.5")
    require('test "${{ github.event.inputs.confirm_pypi_publish }}" = "publish unlimited-skills 0.6.5 to PyPI"' in text, "publish workflow confirmation guard must be exact for 0.6.5")
    require("python scripts/run-v065-alpha-package-smoke.py --json" in text, "publish workflow must run v0.6.5 package smoke")
    require("python scripts/verify-v065-alpha-release-execution.py" in text, "publish workflow must run v0.6.5 release verifier")
    require("pypa/gh-action-pypi-publish@release/v1" in text, "publish workflow must use Trusted Publishing action")
    require("PYPI_TOKEN" not in text and "TWINE_PASSWORD" not in text, "publish workflow must not use token/password publishing")


def run_json(args: list[str], label: str, *, timeout: int = 900) -> dict[str, Any]:
    proc = run_cmd(args, timeout=timeout)
    require(proc.returncode == 0, f"{label} failed: " + proc.stdout[-1200:] + proc.stderr[-1200:])
    payload = json.loads(proc.stdout)
    require(isinstance(payload, dict), f"{label} must emit a JSON object")
    require(payload.get("ok") is True or payload.get("status") == "passed", f"{label} returned non-pass JSON")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", default="", help="Optional exact HEAD SHA selected for release execution.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow local dirty tree while verifying a PR under construction.")
    parser.add_argument("--skip-release-smoke", action="store_true")
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
    manifest = assert_manifest()
    assert_docs()
    assert_workflow()
    release_smoke = None
    if not args.skip_release_smoke:
        release_smoke = run_json([sys.executable, "scripts/verify-v065-retrieval-learning-release-smoke.py", "--json"], "combined release smoke", timeout=1200)
    frozen_contracts = None
    if not args.skip_frozen_contracts:
        frozen_contracts = run_json([sys.executable, "scripts/verify-v06-frozen-contracts.py", "--expected-version", VERSION, "--json"], "frozen contracts")

    payload = {
        "schema_version": 1,
        "release": RELEASE,
        "version": VERSION,
        "status": "passed",
        "manifest_status": manifest["status"],
        "release_execution": manifest["release_execution"],
        "release_smoke": {
            "ok": True if release_smoke is None else release_smoke.get("ok"),
            "installed_library_mutated": False if release_smoke is None else release_smoke.get("installed_library", {}).get("mutated"),
        },
        "frozen_contracts": {
            "ok": True if frozen_contracts is None else frozen_contracts.get("ok"),
            "status_counts": {} if frozen_contracts is None else frozen_contracts.get("status_counts"),
        },
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} release execution verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
