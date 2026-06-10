from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.3.6-alpha"
MANIFEST = ROOT / "docs" / "releases" / "v0.3.6-alpha.release-manifest.json"
PUBLICATION_FILES = [
    ROOT / "docs" / "releases" / "v0.3.6-alpha-upgrade-notes.md",
    ROOT / "docs" / "releases" / "v0.3.6-alpha-known-issues.md",
    ROOT / "scripts" / "run-v0.3.6-alpha-release-smoke.py",
    ROOT / "scripts" / "verify-v0.3.6-alpha-publication.py",
]
PRIVATE_MATERIAL_PATTERNS = {
    "pem_private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "openssh_private_key": r"-----BEGIN OPENSSH PRIVATE KEY-----",
    "github_pat": r"gh[pousr]_[A-Za-z0-9_]{20,}",
    "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
    "raw_uls_token": r"uls_(?:hub|token|license)_[A-Za-z0-9_\-]{16,}",
    "device_private_key_assignment": r"device_private_key\s*[:=]\s*[A-Za-z0-9_\-]{16,}",
    "catalog_body_field": r'"skill_bod(?:y|ies)"\s*:',
    "prompt_field": r'"prompts?"\s*:',
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


def run(command: list[str]) -> str:
    completed = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        fail("command failed: " + " ".join(command) + "\nstdout:\n" + completed.stdout + "\nstderr:\n" + completed.stderr)
    return completed.stdout.strip()


def git_ok(args: list[str]) -> bool:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return completed.returncode == 0


def load_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing release manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(isinstance(payload, dict), "release manifest must be a JSON object")
    return payload


def assert_manifest(expected_sha: str | None) -> str:
    payload = load_manifest()
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_version") == "0.3.6", "manifest package version mismatch")
    git_info = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    sha = str(git_info.get("sha") or "")
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "manifest git.sha must be 40 lowercase hex")
    require(git_info.get("tag") == RELEASE, "manifest tag mismatch")
    require(git_info.get("tag_status") == "pending_release_owner_approval", "manifest must require human tag approval")
    require(git_info.get("publication_branch") == "release/v0.3.6-alpha-final-publication", "manifest publication branch mismatch")
    require(str(git_info.get("tag_owner_note") or "").startswith("Run scripts/verify-v0.3.6-alpha-publication.py"), "manifest tag owner note must reference publication verifier")
    if expected_sha:
        require(re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(git_ok(["merge-base", "--is-ancestor", sha, expected_sha]), f"manifest release candidate {sha} is not contained in expected tag target {expected_sha}")

    prs = payload.get("required_prs", {}) if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    private_numbers = [item.get("number") for item in prs.get("private_registry", []) if isinstance(item, dict)]
    for number in (56, 57, 58):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    require(34 in private_numbers, "manifest missing private registry PR #34")

    security = payload.get("security_boundary", {}) if isinstance(payload.get("security_boundary"), dict) else {}
    require(security.get("production_hosted_calls_in_tests") is False, "production hosted calls must be disabled in tests")
    require(security.get("private_skill_bodies_committed") is False, "private skill bodies must not be committed")
    require(security.get("raw_tokens_committed") is False, "raw tokens must not be committed")
    require(security.get("support_bundle_redacted") is True, "support bundle must be redacted")

    commands = payload.get("required_test_commands", [])
    for command in (
        "python scripts/run-v0.3.6-alpha-release-smoke.py",
        "python scripts/verify-v0.3.6-alpha-publication.py --expected-sha <tag-target-sha>",
    ):
        require(command in commands, f"manifest missing publication test command: {command}")
    return sha


def assert_docs() -> None:
    for path in PUBLICATION_FILES:
        require(path.is_file(), f"missing publication file: {path.relative_to(ROOT)}")
    public_docs = [
        ROOT / "README.md",
        ROOT / "SECURITY.md",
        ROOT / "CHANGELOG.md",
        ROOT / "docs" / "catalog-browser.md",
        ROOT / "docs" / "community-skills.md",
        ROOT / "docs" / "known-limitations.md",
        ROOT / "docs" / "releases" / "v0.3.6-alpha.md",
        ROOT / "docs" / "releases" / "v0.3.6-alpha-checklist.md",
        ROOT / "docs" / "releases" / "v0.3.6-alpha-upgrade-notes.md",
        ROOT / "docs" / "releases" / "v0.3.6-alpha-known-issues.md",
    ]
    text = "\n".join(read(path) for path in public_docs if path.exists()).lower()
    for required in (
        "v0.3.6-alpha",
        "github clone",
        "pyPI".lower(),
        "signed metadata",
        "metadata-only",
        "dry-run",
        "no production hosted calls",
        "mit local",
        "unregistered",
        "no marketplace storefront",
        "no billing",
        "release owner",
    ):
        require(required in text, f"docs missing required wording: {required}")
    for forbidden in ("signed archives are verified", "full catalog distribution is enabled", "live payment provider is enabled"):
        require(forbidden not in text, f"docs contain unsafe release claim: {forbidden}")


def assert_no_private_material() -> None:
    files = [
        ROOT / "README.md",
        ROOT / "SECURITY.md",
        ROOT / "CHANGELOG.md",
        ROOT / "docs" / "known-limitations.md",
        ROOT / "docs" / "catalog-browser.md",
        ROOT / "docs" / "community-skills.md",
        *PUBLICATION_FILES,
        MANIFEST,
    ]
    offenders: list[str] = []
    for path in files:
        if not path.exists() or path.is_dir():
            continue
        text = read(path)
        for name, pattern in PRIVATE_MATERIAL_PATTERNS.items():
            if path.name == "verify-v0.3.6-alpha-publication.py" and name in {
                "pem_private_key",
                "openssh_private_key",
                "catalog_body_field",
                "prompt_field",
                "checkout_url_field",
                "payment_link_field",
                "card_number_field",
                "bank_account_field",
            }:
                continue
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    require(not offenders, "possible private material in public publication files: " + ", ".join(offenders))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify v0.3.6-alpha final publication before tagging.")
    parser.add_argument("--expected-sha", help="Final tag target SHA to compare with docs/releases/v0.3.6-alpha.release-manifest.json")
    args = parser.parse_args()

    run([sys.executable, "scripts/verify-v0.3.6-alpha-catalog-browser.py"] + (["--expected-sha", args.expected_sha] if args.expected_sha else []))
    manifest_sha = assert_manifest(args.expected_sha)
    assert_docs()
    assert_no_private_material()
    current_head = run(["git", "rev-parse", "HEAD"])
    if args.expected_sha:
        require(current_head == args.expected_sha, f"current checkout {current_head} does not match expected tag target {args.expected_sha}")
    print(f"{RELEASE} publication verification passed")
    print(f"manifest: {MANIFEST.relative_to(ROOT)}")
    print(f"manifest release candidate sha: {manifest_sha}")
    print(f"current checkout sha: {current_head}")
    print("distribution path: GitHub clone")
    print("catalog browser milestone: final publication gate")
    print("production hosted calls: blocked by fixture-mode release commands")
    print("private key/token/body/search-query scan: passed for public publication files")
    if args.expected_sha:
        print(f"expected tag target sha: {args.expected_sha}")
    else:
        print("tag target sha check: skipped; pass --expected-sha before pushing the release tag")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
