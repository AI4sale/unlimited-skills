"""Verify the v0.6.3-alpha release execution package is internally consistent."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.6.3-alpha"
VERSION = "0.6.3"
MANIFEST = ROOT / "docs" / "releases" / "v0.6.3-alpha.release-manifest.json"
REQUIRED_DOCS = [
    ROOT / "docs" / "releases" / "v0.6.3-alpha.md",
    ROOT / "docs" / "releases" / "v0.6.3-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.6.3-alpha-upgrade-notes.md",
    ROOT / "docs" / "releases" / "v0.6.3-alpha-known-issues.md",
    ROOT / "docs" / "releases" / "v0.6.3-alpha-pypi-publishing.md",
    ROOT / "docs" / "releases" / "v0.6.3-personal-verification.md",
    ROOT / "docs" / "reports" / "v0.6.3-release-decision-package.md",
    ROOT / "README-pypi.md",
    ROOT / "CHANGELOG.md",
    MANIFEST,
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"{RELEASE} release execution verification failed: {message}")


def run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
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
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(
        git.get("tag_status") == "blocked_until_pypi_upload_clean_install_and_post_publish_verifier",
        "manifest must keep tag blocked until PyPI upload, clean install, and post-publish verifier pass",
    )
    release_execution = payload.get("release_execution") if isinstance(payload.get("release_execution"), dict) else {}
    require(release_execution.get("executed_in_this_pr") is False, "manifest must state publish/tag is not executed in this PR")
    require(release_execution.get("package_ready") is True, "manifest must state package_ready=true")
    require(
        release_execution.get("stale_owner_gap_marker") == "closed_reconciled_by_release_execution_package_if_all_gates_pass",
        "manifest must reconcile the stale owner-gap marker explicitly",
    )
    required = set(payload.get("release_package_files") or [])
    for raw in (
        "docs/releases/v0.6.3-alpha-pypi-publishing.md",
        "scripts/run-v063-alpha-package-smoke.py",
        "scripts/verify-v063-alpha-release-execution.py",
    ):
        require(raw in required or raw in (payload.get("verifier_scripts") or []), f"manifest missing {raw}")
    require(119 in (payload.get("excluded_prs") or []), "#119 must remain excluded")
    return payload


def assert_docs() -> None:
    for path in REQUIRED_DOCS:
        require(path.is_file(), f"missing required doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in REQUIRED_DOCS).lower()
    for required in (
        "v0.6.3-alpha",
        "unlimited-skills==0.6.3",
        "python scripts/run-v063-alpha-package-smoke.py --json",
        "python scripts/verify-v063-alpha-release-execution.py --json",
        "free",
        "registered",
        "team",
        "business",
        "enterprise",
        "no v0.6.4 release claim",
        "no hosted dashboard",
        "no automatic skill improvement",
        "release_owner_go_with_limits_acceptance",
        "#119",
    ):
        require(required in text, f"release docs missing required wording: {required}")
    for forbidden in (
        "docs-only tier claim",
        "hosted telemetry",
        "live sync",
        "sso/scim",
        "signature-enforced",
    ):
        require(forbidden in text, f"release docs must name forbidden claim boundary: {forbidden}")


def assert_workflow() -> None:
    text = read(ROOT / ".github" / "workflows" / "publish-pypi.yml")
    require('test "${{ github.event.inputs.version }}" = "0.6.3"' in text, "publish workflow version guard must be 0.6.3")
    require(
        'test "${{ github.event.inputs.confirm_pypi_publish }}" = "publish unlimited-skills 0.6.3 to PyPI"' in text,
        "publish workflow confirmation guard must be exact for 0.6.3",
    )
    require("python scripts/run-v063-alpha-package-smoke.py --json" in text, "publish workflow must run v0.6.3 package smoke")
    require("python scripts/verify-v063-alpha-release-execution.py" in text, "publish workflow must run v0.6.3 release verifier")
    require("pypa/gh-action-pypi-publish@release/v1" in text, "publish workflow must use Trusted Publishing action")
    require("PYPI_TOKEN" not in text and "TWINE_PASSWORD" not in text, "publish workflow must not use token/password publishing")


def run_frozen_contracts() -> dict[str, Any]:
    proc = run_cmd([sys.executable, "scripts/verify-v06-frozen-contracts.py", "--json"])
    require(proc.returncode == 0, "frozen-contract verifier failed: " + proc.stdout[-1000:] + proc.stderr[-1000:])
    payload = json.loads(proc.stdout)
    require(payload.get("ok") is True, "frozen-contract verifier returned ok=false")
    require(payload.get("expected_version") == VERSION, "frozen-contract verifier expected version mismatch")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", default="", help="Optional exact HEAD SHA selected for release execution.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow local dirty tree while verifying a PR under construction.")
    parser.add_argument("--skip-frozen-contracts", action="store_true", help="Skip the frozen-contract subprocess for lightweight tests.")
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
    frozen_contracts = None if args.skip_frozen_contracts else run_frozen_contracts()

    payload = {
        "schema_version": 1,
        "release": RELEASE,
        "version": VERSION,
        "status": "passed",
        "manifest_status": manifest["status"],
        "release_execution": manifest["release_execution"],
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
