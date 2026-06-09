from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.3.0-alpha"
VERSION = "0.3.0"
MANIFEST = ROOT / "docs" / "releases" / "v0.3.0-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.3.0-alpha.md",
    ROOT / "docs" / "releases" / "v0.3.0-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.3.0-alpha-upgrade-notes.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "known-limitations.md",
    ROOT / "docs" / "packaging.md",
    ROOT / "docs" / "install.md",
    ROOT / "docs" / "upgrade.md",
    ROOT / "docs" / "install-upgrade-uninstall.md",
    ROOT / "docs" / "public-core-boundary.md",
    ROOT / "docs" / "managed-enterprise-policy-sync.md",
    ROOT / "docs" / "managed-enterprise-policy-sync-e2e.md",
]
PRIVATE_MATERIAL_PATTERNS = {
    "pem_private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "openssh_private_key": r"-----BEGIN OPENSSH PRIVATE KEY-----",
    "github_pat": r"gh[pousr]_[A-Za-z0-9_]{20,}",
    "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
    "raw_uls_token": r"uls_(?:hub|token|license)_[A-Za-z0-9_\-]{16,}",
    "device_private_key_assignment": r"device_private_key\s*[:=]\s*[A-Za-z0-9_\-]{16,}",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"v0.3.0-alpha publication verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def package_version() -> str:
    data = tomllib.loads(read(ROOT / "pyproject.toml"))
    return str(data["project"]["version"])


def init_version() -> str:
    text = read(ROOT / "unlimited_skills" / "__init__.py")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    require(match is not None, "__version__ is missing")
    return str(match.group(1))


def run_git(args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def load_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing release manifest: {MANIFEST.relative_to(ROOT)}")
    try:
        payload = json.loads(read(MANIFEST))
    except json.JSONDecodeError as exc:
        fail(f"release manifest is invalid JSON: {exc}")
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
    require(git_info.get("publication_branch") == "release/v0.3.0-alpha-publication", "manifest publication branch mismatch")
    if expected_sha is not None:
        require(re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(sha == expected_sha, f"manifest git.sha {sha} does not match expected tag target {expected_sha}")

    prs = payload.get("required_prs", {}) if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    private_numbers = [item.get("number") for item in prs.get("private_registry", []) if isinstance(item, dict)]
    for number in (28, 29, 30, 31, 32):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    for number in (7, 8):
        require(number in private_numbers, f"manifest missing private registry PR #{number}")

    distribution = payload.get("distribution", {}) if isinstance(payload.get("distribution"), dict) else {}
    require(distribution.get("official_alpha_path") == "GitHub clone", "GitHub clone must be official alpha path")
    require(distribution.get("pypi_supported") is False, "PyPI must be deferred for this alpha")

    boundary = payload.get("registration_boundary", {}) if isinstance(payload.get("registration_boundary"), dict) else {}
    require(boundary.get("local_mit_core_unregistered") is True, "local MIT core must remain unregistered")
    require(boundary.get("enterprise_policy_mandatory_for_community") is False, "Enterprise policy must not be mandatory for Community users")

    security = payload.get("security_boundary", {}) if isinstance(payload.get("security_boundary"), dict) else {}
    require(security.get("full_catalog_distribution") is False, "full catalog distribution must remain disabled")
    require(security.get("local_skill_hub_distribution_mode") == "allowlist_only", "Local Skill Hub must remain allowlist-only")
    require(security.get("hosted_remote_manifests_require_valid_signatures") is True, "hosted manifests must require signatures")
    require("enterprise-policy" in security.get("manifest_scopes", []), "enterprise-policy signature scope missing")
    require(security.get("archive_bytes_verified_by_sha256") is True, "archive SHA256 verification must remain true")
    require(security.get("archive_bytes_cryptographically_signed") is False, "must not claim archive-byte signatures")
    require(security.get("private_registry_skill_bodies_committed") is False, "private registry skill bodies must not be committed")
    require(security.get("private_signing_keys_committed") is False, "private signing keys must not be committed")
    require(security.get("raw_tokens_committed") is False, "raw tokens must not be committed")

    commands = payload.get("required_test_commands", [])
    for command in (
        "python -m pytest tests -q",
        "python scripts/run-v0.2x-smoke-tests.py",
        "python scripts/run-production-registry-contract-e2e.py --fixture-mode --temp-home",
        "python scripts/run-managed-policy-sync-e2e.py --fixture-mode --temp-home",
        "python scripts/verify-v0.3.0-alpha-package-assets.py",
        "python scripts/run-v0.3.0-alpha-packaging-smoke.py",
        "python scripts/run-v0.3.0-alpha-release-smoke.py",
        "python scripts/verify-v0.3.0-alpha-publication.py",
        "python -m compileall -q unlimited_skills scripts tests",
        "git diff --check",
    ):
        require(command in commands, f"manifest missing test command: {command}")
    return sha


def assert_docs() -> None:
    for path in RELEASE_DOCS:
        require(path.is_file(), f"missing release doc: {path.relative_to(ROOT)}")
    require((ROOT / "docs" / "install.md").is_file(), "docs/install.md is missing")
    require((ROOT / "docs" / "upgrade.md").is_file(), "docs/upgrade.md is missing")
    text = "\n".join(read(path) for path in PUBLIC_DOCS if path.exists()).lower()
    for required in (
        "v0.3.0-alpha",
        "github clone",
        "pypi is not the supported v0.3.0-alpha distribution path",
        "full catalog distribution remains disabled",
        "allowlist-only",
        "hosted remote manifests must include valid signed manifest envelopes",
        "archive bytes are sha256-verified",
        "managed enterprise skill lock policy sync",
        "unmanaged local policies",
    ):
        require(required in text, f"docs missing required wording: {required}")
    forbidden = [
        "pypi is the supported v0.3.0-alpha distribution path",
        "full catalog distribution is enabled",
        "unsigned hosted manifests are accepted",
        "archive-byte signatures are implemented in v0.3.0-alpha",
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
    parser = argparse.ArgumentParser(description="Verify v0.3.0-alpha publication gate before tagging.")
    parser.add_argument("--expected-sha", help="Final tag target SHA to compare with docs/releases/v0.3.0-alpha.release-manifest.json")
    args = parser.parse_args()

    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")
    manifest_sha = assert_manifest(load_manifest(), args.expected_sha)
    assert_docs()
    assert_no_private_material()
    current_head = run_git(["rev-parse", "HEAD"])
    print("v0.3.0-alpha publication verification passed")
    print(f"manifest: {MANIFEST.relative_to(ROOT)}")
    print(f"manifest release candidate sha: {manifest_sha}")
    print(f"current checkout sha: {current_head}")
    print("distribution path: GitHub clone")
    print("pypi support: deferred")
    print("production hosted calls: blocked by fixture-mode release commands")
    print("private key/token scan: passed for public release docs")
    if args.expected_sha:
        print(f"expected tag target sha: {args.expected_sha}")
    else:
        print("tag target sha check: skipped; pass --expected-sha before pushing the release tag")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
