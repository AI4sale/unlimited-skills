from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.3.5-alpha"
VERSION = "0.3.5"
MANIFEST = ROOT / "docs" / "releases" / "v0.3.5-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.3.5-alpha.md",
    ROOT / "docs" / "releases" / "v0.3.5-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.3.5-alpha-upgrade-notes.md",
    ROOT / "docs" / "releases" / "v0.3.5-alpha-known-issues.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "community-skills.md",
    ROOT / "docs" / "community-submission-review.md",
    ROOT / "docs" / "known-limitations.md",
    ROOT / "docs" / "support-diagnostic-bundle.md",
    ROOT / "docs" / "public-core-boundary.md",
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
    "card_number_field": r'"card_number"\s*:',
    "bank_account_field": r'"bank_account"\s*:',
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
    git_info = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    sha = str(git_info.get("sha") or "")
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "manifest git.sha must be 40 lowercase hex")
    require(git_info.get("tag") == RELEASE, "manifest tag mismatch")
    require(git_info.get("tag_status") == "pending_release_owner_approval", "manifest must require human tag approval")
    require(git_info.get("publication_branch") == "release/v0.3.5-alpha-final-publication", "manifest publication branch mismatch")
    if expected_sha is not None:
        require(re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(git_ok(["merge-base", "--is-ancestor", sha, expected_sha]), f"manifest candidate {sha} is not contained in expected tag target {expected_sha}")

    prs = payload.get("required_prs", {}) if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    private_numbers = [item.get("number") for item in prs.get("private_registry", []) if isinstance(item, dict)]
    for number in (53, 54, 55):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    require(33 in private_numbers, "manifest missing private registry PR #33")

    security = payload.get("security_boundary", {}) if isinstance(payload.get("security_boundary"), dict) else {}
    require(security.get("skill_execution") is False, "release must not execute skills")
    require(security.get("full_catalog_distribution") is False, "full catalog distribution must remain disabled")
    require(security.get("community_hosted_operations_registration_gated") is True, "hosted community operations must require registration")
    require(security.get("local_mit_core_registration_gated") is False, "MIT local core must remain unregistered")
    require(security.get("stable_promotion_by_default") is False, "stable promotion must not be automatic")
    require(security.get("production_hosted_calls_in_tests") is False, "fixture tests must not call production hosted services")
    require(security.get("signed_hosted_manifests_required") is True, "signed hosted manifests must remain required")
    require(security.get("skill_bodies_in_public_artifacts") is False, "private skill bodies must not be committed")
    require(security.get("payment_or_storefront_features") is False, "payment/storefront features must remain out of scope")
    require(security.get("marketplace_storefront") is False, "marketplace storefront must remain out of scope")
    require(security.get("billing_revenue_share") is False, "billing/revenue share must remain out of scope")

    commands = payload.get("required_test_commands", [])
    for command in (
        "python scripts/run-community-catalog-cross-repo-e2e.py --fixture-mode --temp-home --json",
        "python scripts/run-v0.3.5-alpha-community-catalog-smoke.py --fixture-mode --temp-home",
        "python scripts/run-v0.3.5-alpha-release-smoke.py",
        "python scripts/verify-v0.3.5-alpha-community-catalog.py --expected-sha <tag-target-sha>",
        "python scripts/verify-v0.3.5-alpha-publication.py --expected-sha <tag-target-sha>",
        "python scripts/run-v0.2x-smoke-tests.py",
        "python -m pytest tests -q",
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
        "v0.3.5-alpha",
        "github clone",
        "pypi remains deferred",
        "community submit",
        "dry-run",
        "approved",
        "published",
        "signed",
        "registration",
        "no production hosted calls",
        "full catalog distribution remains disabled",
        "no marketplace storefront",
        "no billing",
        "release owner",
    ):
        require(required in text, f"docs missing required wording: {required}")


def assert_no_private_material() -> None:
    offenders: list[str] = []
    for path in PUBLIC_DOCS:
        if not path.exists() or path.is_dir():
            continue
        text = read(path)
        for name, pattern in PRIVATE_MATERIAL_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    require(not offenders, "possible private material or live payment field in public release docs: " + ", ".join(offenders))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify v0.3.5-alpha final publication gate before tagging.")
    parser.add_argument("--expected-sha", help="Final tag target SHA to compare with docs/releases/v0.3.5-alpha.release-manifest.json")
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
    print(f"manifest: {MANIFEST.relative_to(ROOT)}")
    print(f"manifest release candidate sha: {manifest_sha}")
    print(f"current checkout sha: {current_head}")
    print("distribution path: GitHub clone")
    print("pypi support: deferred")
    print("community hosted operations: registration required")
    print("community install safety: approved/published signed items only")
    print("production hosted calls: blocked by fixture-mode release commands")
    print("private key/token/payment-field scan: passed for public release docs")
    if args.expected_sha:
        print(f"expected tag target sha: {args.expected_sha}")
    else:
        print("tag target sha check: skipped; pass --expected-sha before pushing the release tag")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
