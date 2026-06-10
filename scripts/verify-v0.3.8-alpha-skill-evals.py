from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.3.8-alpha"
VERSION = "0.3.8"
MANIFEST = ROOT / "docs" / "releases" / "v0.3.8-alpha.release-manifest.json"
DOCS = [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "catalog-quality.md",
    ROOT / "docs" / "skill-evaluations.md",
    ROOT / "docs" / "catalog-browser.md",
    ROOT / "docs" / "known-limitations.md",
    ROOT / "docs" / "releases" / "v0.3.8-alpha.md",
    ROOT / "docs" / "releases" / "v0.3.8-alpha-checklist.md",
    MANIFEST,
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def package_version() -> str:
    return str(tomllib.loads(read(ROOT / "pyproject.toml"))["project"]["version"])


def init_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', read(ROOT / "unlimited_skills" / "__init__.py"))
    require(match is not None, "__version__ is missing")
    return str(match.group(1))


def git_ok(args: list[str]) -> bool:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return completed.returncode == 0


def run_git(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), "missing v0.3.8 release manifest")
    payload = json.loads(read(MANIFEST))
    require(isinstance(payload, dict), "release manifest must be an object")
    return payload


def assert_manifest(payload: dict[str, Any], expected_sha: str | None) -> None:
    require(payload.get("release") == RELEASE, "release mismatch")
    require(payload.get("package_version") == VERSION, "package version mismatch")
    git_info = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    sha = str(git_info.get("sha") or "")
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "manifest git.sha must be 40 lowercase hex")
    require(git_info.get("tag_status") == "not_tagged_integration_gate", "v0.3.8 must not be tagged by this task")
    if expected_sha:
        require(re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(git_ok(["merge-base", "--is-ancestor", sha, expected_sha]), "manifest sha is not contained in expected sha")
    required = set(payload.get("required_test_commands", []))
    for command in (
        "python scripts/run-skill-evals-cross-repo-e2e.py --fixture-mode --temp-home --json",
        "python -m pytest tests/integration/test_skill_evals_cross_repo_e2e.py -q",
        "python scripts/run-v0.3.8-alpha-skill-evals-smoke.py --fixture-mode --temp-home",
        "python scripts/verify-v0.3.8-alpha-skill-evals.py --expected-sha <tag-target-sha>",
        "python -m compileall -q unlimited_skills scripts tests",
        "git diff --check",
    ):
        require(command in required, f"manifest missing test command: {command}")


def assert_docs() -> None:
    for path in DOCS:
        require(path.is_file(), f"missing doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in DOCS).lower()
    for phrase in (
        "skill evaluation",
        "catalog quality",
        "fixture",
        "no automatic telemetry",
        "no prompt",
        "no untrusted script execution",
        "no automatic skill rewriting",
        "no production hosted calls",
        "blocked item",
    ):
        require(phrase in text, f"docs missing required phrase: {phrase}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify v0.3.8-alpha skill eval integration gate.")
    parser.add_argument("--expected-sha")
    args = parser.parse_args()
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")
    assert_manifest(manifest(), args.expected_sha)
    assert_docs()
    current_head = run_git(["rev-parse", "HEAD"])
    if args.expected_sha:
        require(current_head == args.expected_sha, f"current checkout {current_head} does not match expected sha {args.expected_sha}")
    print(f"{RELEASE} skill eval integration verification passed")
    print(f"current checkout sha: {current_head}")
    print("production hosted calls: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
