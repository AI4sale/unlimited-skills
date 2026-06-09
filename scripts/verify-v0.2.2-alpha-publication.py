from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.2.2-alpha"
MANIFEST = ROOT / "docs" / "releases" / "v0.2.2-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.2.2-alpha.md",
    ROOT / "docs" / "releases" / "v0.2.2-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.2.2-alpha-upgrade-notes.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "release-process.md",
    ROOT / "docs" / "release-smoke-tests.md",
    ROOT / "docs" / "known-limitations.md",
    ROOT / "docs" / "public-core-boundary.md",
]
PRIVATE_MATERIAL_PATTERNS = {
    "pem_private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "openssh_private_key": r"-----BEGIN OPENSSH PRIVATE KEY-----",
    "github_pat": r"gh[pousr]_[A-Za-z0-9_]{20,}",
    "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
    "raw_uls_token": r"uls_(?:hub|token|license)_[A-Za-z0-9_\-]{12,}",
    "device_private_key_assignment": r"device_private_key\s*[:=]\s*[A-Za-z0-9_\-]{12,}",
}
UNSUPPORTED_CHANNEL_NAME = "d" + "ev"
ALLOWED_CHANNELS_PATTERN_PREFIX = r"allowed_channels[^\n]+"
UNSUPPORTED_CHANNEL_PATTERNS = [
    re.compile(r"stable\s*[,/]\s*beta\s*[,/]\s*" + UNSUPPORTED_CHANNEL_NAME, re.IGNORECASE),
    re.compile(ALLOWED_CHANNELS_PATTERN_PREFIX + UNSUPPORTED_CHANNEL_NAME, re.IGNORECASE),
    re.compile(r"choices=\[[^\]]*['\"]" + UNSUPPORTED_CHANNEL_NAME + r"['\"]", re.IGNORECASE),
    re.compile(r"release\s+pin\s+" + UNSUPPORTED_CHANNEL_NAME, re.IGNORECASE),
    re.compile(r"--channel\s+" + UNSUPPORTED_CHANNEL_NAME, re.IGNORECASE),
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"publication verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


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


def walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(walk_strings(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(walk_strings(item))
        return result
    return []


def assert_manifest(payload: dict[str, Any], expected_sha: str | None) -> str:
    require(payload.get("release") == RELEASE, "release manifest release mismatch")
    require(payload.get("package_name") == "unlimited-skills", "release manifest package name mismatch")
    require(payload.get("package_version") == "0.2.2", "release manifest package version mismatch")

    git_info = payload.get("git", {})
    require(isinstance(git_info, dict), "release manifest git block missing")
    sha = git_info.get("sha")
    require(isinstance(sha, str), "release manifest git.sha missing")
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "release manifest git.sha must be 40 lowercase hex")
    require(sha != "pending" + "_final_gate_merge_commit", "release manifest still contains placeholder git.sha")
    require(git_info.get("tag") == RELEASE, "release manifest tag mismatch")
    require(git_info.get("publication_branch") == "release/v0.2.2-alpha-publication", "publication branch missing from manifest")
    require(git_info.get("tag_status") == "pending_release_owner_approval", "tag status must require release-owner approval before tag push")

    if expected_sha is not None:
        require(re.fullmatch(r"[0-9a-f]{40}", expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(sha == expected_sha, f"manifest git.sha {sha} does not match expected tag target {expected_sha}")

    required_prs = payload.get("required_prs", {})
    require([item.get("number") for item in required_prs.get("private_registry", [])] == [2, 3, 4, 5, 6], "private registry PR traceability mismatch")
    require([item.get("number") for item in required_prs.get("public", [])] == list(range(13, 28)), "public PR traceability mismatch")
    require(required_prs.get("finalization_branch") == "release/v0.2.2-alpha-final-gate", "finalization branch mismatch")
    require(required_prs.get("publication_branch") == "release/v0.2.2-alpha-publication", "publication branch mismatch")

    distribution = payload.get("distribution_policy", {})
    require(distribution.get("full_catalog_distribution") is False, "full catalog distribution must remain disabled")
    require(distribution.get("hub_distribution_mode") == "allowlist_only", "hub distribution must remain allowlist-only")
    require(distribution.get("hosted_query_forwarding") is False, "hosted query forwarding must remain disabled")
    require(distribution.get("hub_executes_skills") is False, "hub must not execute skills")

    boundary = payload.get("registration_boundary", {})
    require("serve" in boundary.get("unregistered_public_core_commands", []), "serve must remain unregistered")
    require("hub serve" in boundary.get("registration_gated_commands", []), "hub serve must remain registration-gated")

    security = payload.get("security_boundary", {})
    require(security.get("hosted_remote_manifests_require_valid_signatures") is True, "hosted manifests must require signatures")
    require(security.get("archive_bytes_verified_by_sha256") is True, "archive SHA256 verification must be required")
    require(security.get("archive_bytes_cryptographically_signed") is False, "manifest must not claim archive-byte signatures")
    require(security.get("zip_safe_extraction_required") is True, "safe extraction must be required")
    require(security.get("private_signing_keys_shipped") is False, "private signing keys must not ship")
    require(security.get("production_hosted_calls_in_tests") is False, "tests must not call production hosted services by default")

    supported_channels = {"stable", "beta", "canary"}
    for item in payload.get("public_trusted_manifest_keys", []):
        require("release-channels" in set(item.get("scopes", [])), "trusted key missing release-channels scope")
    for text in walk_strings(payload):
        require(text != "dev", "manifest contains unsupported dev channel string")
    scope = set(payload.get("feature_scope", []))
    for required in (
        "release channel naming fixed to stable, beta, and canary",
        "production service onboarding diagnostics",
        "Enterprise Skill Lock local policy MVP",
        "private registry deployment and operations package",
    ):
        require(required in scope, f"manifest missing feature scope: {required}")

    commands = payload.get("required_test_commands", [])
    for command in (
        "python -m pytest tests -q",
        "python scripts/run-v0.2x-smoke-tests.py",
        "python scripts/run-staging-registry-e2e.py --fixture-mode --temp-home",
        "python scripts/run-production-registry-contract-e2e.py --fixture-mode --temp-home",
        "python scripts/run-v0.2.2-alpha-cross-repo-smoke.py --fixture-mode --temp-home",
        "python scripts/verify-v0.2.2-alpha-release.py",
        "python scripts/verify-v0.2.2-alpha-publication.py",
        "python -m compileall -q unlimited_skills scripts tests",
        "git diff --check",
    ):
        require(command in commands, f"manifest missing required test command: {command}")
    require(supported_channels == {"stable", "beta", "canary"}, "internal supported channel set drifted")
    return sha


def assert_docs() -> None:
    release_text = "\n".join(read(path) for path in RELEASE_DOCS if path.exists())
    require("pending" + "_final_gate_merge_commit" not in release_text, "release docs still contain placeholder SHA marker")

    text = "\n".join(read(path) for path in PUBLIC_DOCS if path.exists())
    lowered = text.lower()
    for required in (
        "mit community core remains local-first",
        "`unlimited-skills serve` remains unregistered",
        "`unlimited-skills hub serve` remains registration-gated",
        "local skill hub remains allowlist-only",
        "full catalog distribution is disabled",
        "hosted remote manifests must include valid signed manifest envelopes",
        "archive bytes are sha256-verified",
        "enterprise skill lock local policy mvp",
    ):
        require(required in lowered, f"release docs missing required boundary wording: {required}")
    require("private registry skill bodies" in lowered, "release docs must state private registry skill bodies are not shipped")
    require("managed hosted policy sync" in lowered, "release docs must state managed Enterprise Skill Lock sync limitation")

    forbidden = [
        "full catalog distribution is enabled",
        "full catalog distribution allowed",
        "unsigned hosted manifests are accepted",
        "archive-byte signatures are implemented in v0.2.2-alpha",
        "enterprise skill lock is planned, not implemented",
    ]
    found = [phrase for phrase in forbidden if phrase in lowered]
    require(not found, "release docs contain unsafe or stale claims: " + ", ".join(found))


def assert_no_unsupported_channels() -> None:
    offenders: list[str] = []
    candidates = [
        *PUBLIC_DOCS,
        ROOT / "scripts" / "verify-v0.2.2-alpha-release.py",
    ]
    for path in candidates:
        if not path.exists() or path.is_dir():
            continue
        text = read(path)
        for pattern in UNSUPPORTED_CHANNEL_PATTERNS:
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))
                break
    require(not offenders, "unsupported dev release-channel references found: " + ", ".join(sorted(set(offenders))))


def assert_no_private_material() -> None:
    offenders: list[str] = []
    for path in PUBLIC_DOCS:
        if not path.exists() or path.is_dir():
            continue
        text = read(path)
        for name, pattern in PRIVATE_MATERIAL_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    require(not offenders, "possible private material in release docs: " + ", ".join(offenders))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the v0.2.2-alpha publication gate before tagging.")
    parser.add_argument("--expected-sha", help="Final tag target SHA to compare against docs/releases/v0.2.2-alpha.release-manifest.json")
    args = parser.parse_args()

    payload = load_manifest()
    manifest_sha = assert_manifest(payload, args.expected_sha)
    assert_docs()
    assert_no_unsupported_channels()
    assert_no_private_material()

    current_head = run_git(["rev-parse", "HEAD"])
    print("v0.2.2-alpha publication verification passed")
    print(f"manifest: {MANIFEST.relative_to(ROOT)}")
    print(f"manifest release candidate sha: {manifest_sha}")
    print(f"current checkout sha: {current_head}")
    print("production hosted calls: blocked by fixture-mode release commands")
    print("private key/token scan: passed for public release docs")
    if args.expected_sha:
        print(f"expected tag target sha: {args.expected_sha}")
    else:
        print("tag target sha check: skipped; pass --expected-sha before pushing the release tag")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
