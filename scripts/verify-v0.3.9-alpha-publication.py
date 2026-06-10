from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.3.9-alpha"
VERSION = "0.3.9"
MANIFEST = ROOT / "docs" / "releases" / "v0.3.9-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.3.9-alpha.md",
    ROOT / "docs" / "releases" / "v0.3.9-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.3.9-alpha-upgrade-notes.md",
    ROOT / "docs" / "releases" / "v0.3.9-alpha-known-issues.md",
    ROOT / "docs" / "releases" / "v0.4-readiness-audit.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "skill-improvement-workflow.md",
    ROOT / "docs" / "skill-improvement-status.md",
    ROOT / "docs" / "catalog-quality.md",
    ROOT / "docs" / "privacy-and-telemetry.md",
    ROOT / "docs" / "support-diagnostic-bundle.md",
    ROOT / "docs" / "known-limitations.md",
]
PRIVATE_MATERIAL_PATTERNS = {
    "pem_private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "openssh_private_key": r"-----BEGIN OPENSSH PRIVATE KEY-----",
    "github_pat": r"gh[pousr]_[A-Za-z0-9_]{20,}",
    "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
    "raw_uls_token": r"uls_(?:hub|token|license)_[A-Za-z0-9_\-]{16,}",
    "device_private_key_assignment": r"device_private_key\s*[:=]\s*[A-Za-z0-9_\-]{16,}",
    "checkout_url_field": r'"checkout_url"\s*:',
    "payment_link_field": r'"payment_link"\s*:',
    "catalog_body_field": r'"skill_bod(?:y|ies)"\s*:',
    "prompt_body_field": r'"(?:prompt|prompts|task_text|customer_data)"\s*:\s*"[^"]+"',
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} publication verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def package_version() -> str:
    return str(tomllib.loads(read(ROOT / "pyproject.toml"))["project"]["version"])


def init_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', read(ROOT / "unlimited_skills" / "__init__.py"))
    require(match is not None, "__version__ is missing")
    return str(match.group(1))


def run_git(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def git_ok(args: list[str]) -> bool:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return completed.returncode == 0


def load_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing release manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(isinstance(payload, dict), "release manifest must be a JSON object")
    return payload


def assert_manifest(payload: dict[str, Any], expected_sha: str | None) -> str:
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_version") == VERSION, "manifest package version mismatch")
    require(payload.get("distribution") == "github-clone-alpha", "GitHub clone must remain distribution path")
    git_info = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    sha = str(git_info.get("sha") or "")
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "manifest git.sha must be 40 lowercase hex")
    require(git_info.get("tag") == RELEASE, "manifest tag mismatch")
    require(git_info.get("tag_status") == "pending_release_owner_approval", "manifest must require human tag approval")
    require(git_info.get("publication_branch") == "release/v0.3.9-alpha-final-publication", "manifest publication branch mismatch")
    if expected_sha is not None:
        require(re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(git_ok(["merge-base", "--is-ancestor", sha, expected_sha]), f"manifest release candidate {sha} is not contained in expected tag target {expected_sha}")
    public_numbers = [item.get("number") for item in payload.get("required_prs", {}).get("public", []) if isinstance(item, dict)]
    private_numbers = [item.get("number") for item in payload.get("required_prs", {}).get("private_registry", []) if isinstance(item, dict)]
    for number in (65, 66, 67):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    require(37 in private_numbers, "manifest missing private registry PR #37")
    boundary = payload.get("skill_improvement_boundary", {}) if isinstance(payload.get("skill_improvement_boundary"), dict) else {}
    for key in ("maintainer_controlled", "fixture_mode", "external_local_registry_mode"):
        require(boundary.get(key) is True, f"skill improvement boundary must set {key}")
    for key in (
        "automatic_telemetry",
        "prompts_included",
        "task_text_included",
        "skill_bodies_included",
        "search_queries_included",
        "local_paths_included",
        "repo_paths_included",
        "untrusted_script_execution",
        "automatic_skill_rewriting",
        "auto_publish",
        "production_hosted_calls_in_tests",
    ):
        require(boundary.get(key) is False, f"skill improvement boundary must disable {key}")
    commands = payload.get("required_test_commands", [])
    for command in (
        ".venv\\Scripts\\python.exe -m pytest tests -q",
        ".venv\\Scripts\\python.exe scripts/run-v0.2x-smoke-tests.py",
        ".venv\\Scripts\\python.exe scripts/run-skill-improvement-cross-repo-e2e.py --fixture-mode --temp-home --json",
        ".venv\\Scripts\\python.exe scripts/run-v0.3.9-alpha-skill-improvement-smoke.py --fixture-mode --temp-home",
        ".venv\\Scripts\\python.exe scripts/run-v0.3.9-alpha-release-smoke.py",
        ".venv\\Scripts\\python.exe scripts/verify-v0.3.9-alpha-skill-improvement.py --expected-sha <tag-target-sha>",
        ".venv\\Scripts\\python.exe scripts/verify-v0.3.9-alpha-publication.py --expected-sha <tag-target-sha>",
        ".venv\\Scripts\\python.exe -m compileall -q unlimited_skills scripts tests",
        "git diff --check",
    ):
        require(command in commands, f"manifest missing test command: {command}")
    return sha


def assert_docs() -> None:
    for path in RELEASE_DOCS:
        require(path.is_file(), f"missing release doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in PUBLIC_DOCS if path.exists()).lower()
    for required in (
        "v0.3.9-alpha",
        "skill improvement",
        "maintainer-controlled",
        "preview-only",
        "fixed pending eval",
        "no automatic skill rewriting",
        "no auto-publish",
        "no prompt upload",
        "no user telemetry",
        "no production hosted calls",
        "support bundle",
        "github clone",
        "pypi",
        "mit local core",
        "v0.4 remains no-go",
    ):
        require(required in text, f"docs missing required wording: {required}")
    forbidden_claims = (
        "automatic skill improvement telemetry",
        "recommendations automatically update",
        "recommendations automatically install",
        "recommendations automatically remove",
        "pypi is the supported v0.3.9-alpha distribution path",
        "mit local core requires registration",
        "v0.4 is ready for implementation",
    )
    for claim in forbidden_claims:
        require(claim not in text, f"docs contain unsafe release claim: {claim}")


def assert_no_private_material() -> None:
    offenders: list[str] = []
    for path in PUBLIC_DOCS:
        if not path.exists() or path.is_dir():
            continue
        text = read(path)
        for name, pattern in PRIVATE_MATERIAL_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    require(not offenders, "possible private material in public release docs: " + ", ".join(offenders))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify v0.3.9-alpha final publication before tagging.")
    parser.add_argument("--expected-sha", help="Final tag target SHA to compare with docs/releases/v0.3.9-alpha.release-manifest.json")
    args = parser.parse_args()
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")
    manifest_sha = assert_manifest(load_manifest(), args.expected_sha)
    assert_docs()
    assert_no_private_material()
    current_head = run_git(["rev-parse", "HEAD"])
    if args.expected_sha:
        require(current_head == args.expected_sha, f"current checkout {current_head} does not match expected tag target {args.expected_sha}")
    print(f"{RELEASE} final publication verification passed")
    print(f"manifest release candidate sha: {manifest_sha}")
    print(f"current checkout sha: {current_head}")
    print("production hosted calls: blocked by fixture-mode release commands")
    print("tag status: pending release-owner approval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
