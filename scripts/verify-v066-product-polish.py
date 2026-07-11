#!/usr/bin/env python
"""Verify inherited v0.6.6 precision plus the current v0.6.7 release surface."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.6.7"
FOCUSED_TESTS = (
    "tests/test_suggest.py",
    "tests/test_suggest_language_routing.py",
    "tests/test_plugin_hooks.py",
    "tests/test_quickstart.py",
    "tests/test_doctor.py",
    "tests/test_pypi_trusted_publishing_workflow.py",
    "tests/test_v066_release.py",
    "tests/test_business_context.py",
    "tests/test_claude_code_install.py",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(args: list[str], *, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
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


def checked(args: list[str], label: str, *, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    proc = run(args, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed\n{proc.stdout[-1800:]}\n{proc.stderr[-1800:]}")
    return proc


def declared_version(path: Path, pattern: str) -> str:
    match = re.search(pattern, read(path), re.MULTILINE)
    require(match is not None, f"version missing in {path.relative_to(ROOT)}")
    return match.group(1)


def verify_static_surface() -> dict[str, Any]:
    versions = {
        "pyproject": declared_version(ROOT / "pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
        "runtime": declared_version(ROOT / "unlimited_skills" / "__init__.py", r'__version__\s*=\s*"([^"]+)"'),
        "claude_plugin": declared_version(ROOT / "plugin" / ".claude-plugin" / "plugin.json", r'"version"\s*:\s*"([^"]+)"'),
    }
    require(set(versions.values()) == {VERSION}, f"release versions must all be {VERSION}: {versions}")

    precision_plan = read(ROOT / "docs" / "releases" / "v0.6.6-plan.md")
    for marker in (
        "raw retrieval, recall-safe hints, and card/body eligibility are separate surfaces",
        "Body-only overlap never qualifies",
        "the hook keeps one compatible local daemon running by default",
        "tag/release creation follows verified public-wheel smoke",
        "No deletion, replacement, or migration of `library/local`",
    ):
        require(marker in precision_plan, f"precision plan missing invariant: {marker}")
    release_plan = read(ROOT / "docs" / "releases" / "v0.6.7-plan.md")
    for marker in (
        "never names or imports a private knowledge system",
        "provider-controlled text is escaped and adversarially tested",
        "the Stop hook never submits prose",
        "defaults permit only `public` and `internal-sanitized`",
        "No deletion, replacement, or migration of `library/local`",
    ):
        require(marker in release_plan, f"v0.6.7 plan missing invariant: {marker}")

    hook = read(ROOT / "plugin" / "hooks" / "user_prompt_submit.py")
    session_hook = read(ROOT / "plugin" / "hooks" / "session_start.py")
    for marker in (
        "_ensure_warm_daemon",
        "_daemon_identity_matches",
        "_claim_daemon_launch",
        "UNLIMITED_SKILLS_NO_AUTOSERVE",
        "subprocess.Popen",
        "subprocess.DETACHED_PROCESS",
    ):
        require(marker in hook, f"hook missing autoserve invariant: {marker}")
    require("shell=True" not in hook, "daemon autoserve must never invoke a shell")
    require("127.0.0.1" in hook and "localhost" in hook and "::1" in hook, "autoserve must remain loopback-only")
    require("_ensure_warm_daemon(command)" in session_hook, "SessionStart must proactively ensure the daemon")
    endpoint = read(ROOT / "unlimited_skills" / "daemon_endpoint.py")
    require("HASHED_PORT_BASE" in endpoint and "sha256" in endpoint, "multi-root daemon endpoint derivation missing")

    workflow = read(ROOT / ".github" / "workflows" / "publish-pypi.yml")
    require(f'test "${{{{ github.event.inputs.version }}}}" = "{VERSION}"' in workflow, "workflow version guard mismatch")
    require(
        f'test "${{{{ github.event.inputs.confirm_pypi_publish }}}}" = "publish unlimited-skills {VERSION} to PyPI"'
        in workflow,
        "workflow confirmation guard mismatch",
    )
    require(f"python scripts/verify-pypi-publication.py --version {VERSION}" in workflow, "workflow must verify the public PyPI wheel")
    require("verify-v066-daemon-rollover.py --wheel dist/*.whl" in workflow, "workflow must prove live legacy-daemon rollover")
    require(
        "verify-v067-business-context-wheel.py --wheel dist/*.whl" in workflow,
        "workflow must prove business-context retrieval from the exact wheel",
    )
    release_command = f'gh release create "v{VERSION}"'
    require(release_command in workflow, "workflow must create the release after PyPI verification")
    require(workflow.index("verify-pypi-publication.py") < workflow.index(release_command), "GitHub release must follow PyPI verification")
    require("--prerelease" not in workflow, "PEP 440 final package must not create a prerelease tag")
    require("PYPI_TOKEN" not in workflow and "TWINE_PASSWORD" not in workflow, "workflow must remain OIDC-only")
    return {"versions": versions, "plan": "present", "workflow": "pypi_first"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", default="")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-frozen-contracts", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.expected_sha:
        head = checked(["git", "rev-parse", "HEAD"], "read HEAD").stdout.strip()
        require(head == args.expected_sha, f"HEAD {head} does not match expected SHA {args.expected_sha}")
    if not args.allow_dirty:
        require(not checked(["git", "status", "--short"], "read worktree").stdout.strip(), "working tree must be clean")

    static = verify_static_surface()
    tests = {"skipped": True}
    if not args.skip_tests:
        proc = checked([sys.executable, "-m", "pytest", "-q", *FOCUSED_TESTS], "focused regression suite")
        tests = {"skipped": False, "tail": proc.stdout.strip().splitlines()[-1]}

    frozen: dict[str, Any] = {"skipped": True}
    if not args.skip_frozen_contracts:
        proc = checked(
            [sys.executable, "scripts/verify-v06-frozen-contracts.py", "--expected-version", VERSION, "--json"],
            "frozen contracts",
        )
        frozen_payload = json.loads(proc.stdout)
        require(frozen_payload.get("ok") is True, "frozen contract verifier did not report ok")
        frozen = {"skipped": False, "ok": True, "rows": len(frozen_payload.get("rows") or [])}

    result = {
        "schema_version": 1,
        "release": f"v{VERSION}",
        "version": VERSION,
        "status": "passed",
        "static": static,
        "tests": tests,
        "frozen_contracts": frozen,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"v{VERSION} inherited precision and release verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
