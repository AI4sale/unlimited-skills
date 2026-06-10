from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.3.7-alpha"
VERSION = "0.3.7"
MANIFEST = ROOT / "docs" / "releases" / "v0.3.7-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.3.7-alpha.md",
    ROOT / "docs" / "releases" / "v0.3.7-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.3.7-alpha-upgrade-notes.md",
    ROOT / "docs" / "releases" / "v0.3.7-alpha-known-issues.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "catalog-feedback.md",
    ROOT / "docs" / "catalog-browser.md",
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
    require(git_info.get("publication_branch") == "release/v0.3.7-alpha-final-publication", "manifest publication branch mismatch")
    if expected_sha is not None:
        require(re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(git_ok(["merge-base", "--is-ancestor", sha, expected_sha]), f"manifest release candidate {sha} is not contained in expected tag target {expected_sha}")
    public_numbers = [item.get("number") for item in payload.get("required_prs", {}).get("public", []) if isinstance(item, dict)]
    private_numbers = [item.get("number") for item in payload.get("required_prs", {}).get("private_registry", []) if isinstance(item, dict)]
    for number in (59, 60, 61):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    require(35 in private_numbers, "manifest missing private registry PR #35")
    feedback = payload.get("feedback_boundary", {}) if isinstance(payload.get("feedback_boundary"), dict) else {}
    for key in ("explicit_feedback_only", "registration_required", "confirmation_required"):
        require(feedback.get(key) is True, f"feedback boundary must set {key}")
    for key in ("automatic_telemetry", "skill_bodies_included", "prompts_included", "local_paths_included", "tokens_included", "private_keys_included"):
        require(feedback.get(key) is False, f"feedback boundary must disable {key}")
    security = payload.get("security_boundary", {}) if isinstance(payload.get("security_boundary"), dict) else {}
    require(security.get("production_hosted_calls_in_tests") is False, "release tests must not call production hosted services")
    require(security.get("support_bundle_redacted") is True, "support bundle must remain redacted")
    commands = payload.get("required_test_commands", [])
    for command in (
        "python -m pytest tests -q",
        "python scripts/run-catalog-feedback-cross-repo-e2e.py --fixture-mode --temp-home --json",
        "python scripts/run-v0.2x-smoke-tests.py",
        "python scripts/run-v0.3.7-alpha-catalog-feedback-smoke.py",
        "python scripts/run-v0.3.7-alpha-release-smoke.py",
        "python scripts/verify-v0.3.7-alpha-publication.py --expected-sha <tag-target-sha>",
        "python -m compileall -q unlimited_skills scripts tests",
        "git diff --check",
    ):
        require(command in commands, f"manifest missing test command: {command}")
    return sha


def assert_docs() -> None:
    for path in RELEASE_DOCS:
        require(path.is_file(), f"missing release doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in PUBLIC_DOCS if path.exists()).lower()
    for required in (
        "v0.3.7-alpha",
        "catalog feedback",
        "explicit",
        "dry-run",
        "no automatic telemetry",
        "no production hosted calls",
        "support bundle",
        "release owner",
        "github clone",
        "pypi",
        "mit local core",
    ):
        require(required in text, f"docs missing required wording: {required}")
    forbidden_claims = (
        "automatic catalog feedback telemetry",
        "feedback sends prompts",
        "feedback sends skill bodies",
        "pypi is the supported v0.3.7-alpha distribution path",
        "mit local core requires registration",
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
    parser = argparse.ArgumentParser(description="Verify v0.3.7-alpha final publication before tagging.")
    parser.add_argument("--expected-sha", help="Final tag target SHA to compare with docs/releases/v0.3.7-alpha.release-manifest.json")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
