from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.3.1-alpha"
VERSION = "0.3.1"
PUBLISHED_BASELINE = "v0.3.0-alpha"
PUBLISHED_BASELINE_URL = "https://github.com/AI4sale/unlimited-skills/releases/tag/v0.3.0-alpha"
MANIFEST = ROOT / "docs" / "releases" / "v0.3.1-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.3.1-alpha.md",
    ROOT / "docs" / "releases" / "v0.3.1-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.3.1-alpha.release-health.md",
    ROOT / "docs" / "releases" / "v0.3.1-alpha.known-issues.md",
    ROOT / "docs" / "releases" / "v0.3.1-alpha-upgrade-notes.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "known-limitations.md",
    ROOT / "docs" / "install.md",
    ROOT / "docs" / "upgrade.md",
    ROOT / "docs" / "release-process.md",
    ROOT / "docs" / "public-core-boundary.md",
    ROOT / "docs" / "first-run-setup.md",
    ROOT / "docs" / "support-bundle.md",
]
PRIVATE_MATERIAL_PATTERNS = {
    "pem_private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "openssh_private_key": r"-----BEGIN OPENSSH PRIVATE KEY-----",
    "github_pat": r"gh[pousr]_[A-Za-z0-9_]{20,}",
    "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
    "raw_uls_token": r"uls_(?:hub|token|license)_[A-Za-z0-9_\-]{16,}",
    "device_private_key_assignment": r"device_private_key\s*[:=]\s*[A-Za-z0-9_\-]{16,}",
    "device_proof_assignment": r"device_proof\s*[:=]\s*[A-Za-z0-9_\-]{16,}",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"v0.3.1-alpha publication verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def run_git(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def git_ok(args: list[str]) -> bool:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return completed.returncode == 0


def package_version() -> str:
    data = tomllib.loads(read(ROOT / "pyproject.toml"))
    return str(data["project"]["version"])


def init_version() -> str:
    text = read(ROOT / "unlimited_skills" / "__init__.py")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    require(match is not None, "__version__ is missing")
    return str(match.group(1))


def load_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing release manifest: {MANIFEST.relative_to(ROOT)}")
    try:
        payload = json.loads(read(MANIFEST))
    except json.JSONDecodeError as exc:
        fail(f"release manifest is invalid JSON: {exc}")
    require(isinstance(payload, dict), "release manifest must be a JSON object")
    return payload


def assert_baseline_release_detected() -> str:
    local = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/tags/{PUBLISHED_BASELINE}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if local.returncode == 0:
        return local.stdout.strip()
    remote = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{PUBLISHED_BASELINE}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    require(remote.returncode == 0 and PUBLISHED_BASELINE in remote.stdout, f"{PUBLISHED_BASELINE} tag not detected locally or on origin")
    return "origin/" + PUBLISHED_BASELINE


def assert_manifest(payload: dict[str, Any], expected_sha: str | None) -> str:
    require(payload.get("schema_version") == 1, "manifest schema_version must be 1")
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_name") == "unlimited-skills", "manifest package name mismatch")
    require(payload.get("package_version") == VERSION, "manifest package version mismatch")
    baseline = payload.get("published_baseline") if isinstance(payload.get("published_baseline"), dict) else {}
    require(baseline.get("release") == PUBLISHED_BASELINE, "published baseline release mismatch")
    require(baseline.get("url") == PUBLISHED_BASELINE_URL, "published baseline URL mismatch")

    git_info = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    sha = str(git_info.get("sha") or "")
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "manifest git.sha must be 40 lowercase hex")
    sha_kind = str(git_info.get("sha_kind") or "final_tag_target")
    require(git_info.get("tag") == RELEASE, "manifest tag mismatch")
    require(git_info.get("tag_status") == "pending_release_owner_approval", "manifest must require human tag approval")
    require(git_info.get("publication_branch") == "release/v0.3.1-alpha-publication", "manifest publication branch mismatch")
    if expected_sha is not None:
        require(re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        if sha_kind == "release_candidate_stack_head":
            require(
                git_ok(["merge-base", "--is-ancestor", sha, expected_sha]),
                f"manifest release candidate {sha} is not contained in expected tag target {expected_sha}",
            )
        else:
            require(sha == expected_sha, f"manifest git.sha {sha} does not match expected tag target {expected_sha}")

    prs = payload.get("required_prs", {}) if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    private_numbers = [item.get("number") for item in prs.get("private_registry", []) if isinstance(item, dict)]
    for number in (34, 35, 36):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    for number in (9, 10):
        require(number in private_numbers, f"manifest missing private registry PR #{number}")

    reconciliation = payload.get("private_registry_reconciliation") if isinstance(payload.get("private_registry_reconciliation"), dict) else {}
    expected_counts = {
        "canonical_audit_total": 315,
        "allowlist_total": 105,
        "requires_local_install_plan_total": 165,
        "excluded_total": 45,
        "blocked_total": 26,
        "local_only_total": 13,
        "needs_human_review_total": 6,
    }
    for key, expected in expected_counts.items():
        require(reconciliation.get(key) == expected, f"private registry reconciliation {key} mismatch")
    require(reconciliation.get("status") == "in_review", "private registry reconciliation status must remain in_review")
    require(
        reconciliation.get("source_audit_sha256") == "6dcb8f04251fed917ebf3b683fe48966095808c0f868daffeddcf6b5bd7b5311",
        "private registry source audit sha mismatch",
    )

    distribution = payload.get("distribution", {}) if isinstance(payload.get("distribution"), dict) else {}
    require(distribution.get("official_alpha_path") == "GitHub clone", "GitHub clone must be official alpha path")
    require(distribution.get("pypi_supported") is False, "PyPI must be deferred for this alpha")

    boundary = payload.get("registration_boundary", {}) if isinstance(payload.get("registration_boundary"), dict) else {}
    require(boundary.get("local_mit_core_unregistered") is True, "local MIT core must remain unregistered")
    require(boundary.get("setup_wizard_local_only_unregistered") is True, "setup wizard local-only mode must remain unregistered")
    require(boundary.get("support_bundle_unregistered") is True, "support bundle must remain unregistered")
    require(boundary.get("enterprise_policy_mandatory_for_community") is False, "Enterprise policy must not be mandatory for Community users")

    security = payload.get("security_boundary", {}) if isinstance(payload.get("security_boundary"), dict) else {}
    require(security.get("full_catalog_distribution") is False, "full catalog distribution must remain disabled")
    require(security.get("local_skill_hub_distribution_mode") == "allowlist_only", "Local Skill Hub must remain allowlist-only")
    require(security.get("hosted_remote_manifests_require_valid_signatures") is True, "hosted manifests must require signatures")
    require("enterprise-policy" in security.get("manifest_scopes", []), "enterprise-policy signature scope missing")
    require(security.get("archive_bytes_verified_by_sha256") is True, "archive SHA256 verification must remain true")
    require(security.get("archive_bytes_cryptographically_signed") is False, "must not claim archive-byte signatures")
    require(security.get("support_bundle_redacts_private_material") is True, "support bundle redaction boundary missing")
    require(security.get("private_registry_skill_bodies_committed") is False, "private registry skill bodies must not be committed")
    require(security.get("private_signing_keys_committed") is False, "private signing keys must not be committed")
    require(security.get("raw_tokens_committed") is False, "raw tokens must not be committed")

    commands = payload.get("required_test_commands", [])
    for command in (
        "python -m pytest tests -q",
        "python scripts/run-v0.2x-smoke-tests.py",
        "python scripts/run-v0.3.0-alpha-release-smoke.py",
        "python scripts/run-v0.3.0-alpha-packaging-smoke.py",
        "python scripts/run-v0.3.1-alpha-post-release-smoke.py",
        "python scripts/verify-v0.3.0-alpha-publication.py",
        "python scripts/verify-v0.3.1-alpha-stabilization.py",
        "python scripts/verify-v0.3.1-alpha-publication.py",
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
        RELEASE.lower(),
        PUBLISHED_BASELINE.lower(),
        PUBLISHED_BASELINE_URL.lower(),
        "github clone",
        "pypi is not the supported",
        "full catalog distribution remains disabled",
        "allowlist-only",
        "mit local",
        "registration-gated",
        "support diagnostic bundle",
        "first-run setup wizard",
        "private registry reconciliation",
        "canonical 315-skill audit",
        "hosted remote manifests must include valid signed manifest envelopes",
        "archive bytes are sha256-verified",
    ):
        require(required in text, f"docs missing required wording: {required}")
    forbidden = [
        "pypi is the supported",
        "full catalog distribution is enabled",
        "unsigned hosted manifests are accepted",
        "local mit core requires registration",
        "mit local commands require registration",
        "archive-byte signatures are implemented in v0.3.1-alpha",
        "archive-byte signatures are implemented.",
    ]
    found = [phrase for phrase in forbidden if phrase in text]
    require(not found, "docs contain unsafe release claims: " + ", ".join(found))


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
    parser = argparse.ArgumentParser(description="Verify v0.3.1-alpha publication gate before tagging.")
    parser.add_argument("--expected-sha", help="Final tag target SHA to compare with docs/releases/v0.3.1-alpha.release-manifest.json")
    args = parser.parse_args()

    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")
    baseline = assert_baseline_release_detected()
    manifest_sha = assert_manifest(load_manifest(), args.expected_sha)
    assert_docs()
    assert_no_private_material()
    current_head = run_git(["rev-parse", "HEAD"])
    if args.expected_sha:
        require(
            current_head == args.expected_sha,
            f"current checkout {current_head} does not match expected tag target {args.expected_sha}",
        )
    print("v0.3.1-alpha publication verification passed")
    print(f"manifest: {MANIFEST.relative_to(ROOT)}")
    print(f"manifest release candidate sha: {manifest_sha}")
    print(f"current checkout sha: {current_head}")
    print(f"published baseline: {PUBLISHED_BASELINE} ({baseline})")
    print("distribution path: GitHub clone")
    print("pypi support: deferred")
    print("MIT local core: unregistered")
    print("hosted features: registration-gated")
    print("full catalog distribution: disabled")
    print("private registry reconciliation: in review, canonical 315-skill audit recorded")
    print("private key/token/proof scan: passed for public publication docs")
    if args.expected_sha:
        print(f"expected tag target sha: {args.expected_sha}")
    else:
        print("tag target sha check: skipped; pass --expected-sha before pushing the release tag")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
