from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.2.2-alpha"
PACKAGE_VERSION = "0.2.2"
MANIFEST = ROOT / "docs" / "releases" / "v0.2.2-alpha.release-manifest.json"
DOC_PATHS = [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "known-limitations.md",
    ROOT / "docs" / "release-process.md",
    ROOT / "docs" / "release-smoke-tests.md",
    ROOT / "docs" / "public-core-boundary.md",
    ROOT / "docs" / "release-channels.md",
    ROOT / "docs" / "releases" / "v0.2.2-alpha.md",
    ROOT / "docs" / "releases" / "v0.2.2-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.2.2-alpha-upgrade-notes.md",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"release verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_package_version() -> str:
    data = tomllib.loads(read(ROOT / "pyproject.toml"))
    return str(data["project"]["version"])


def load_init_version() -> str:
    text = read(ROOT / "unlimited_skills" / "__init__.py")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    require(match is not None, "unlimited_skills.__version__ is missing")
    return match.group(1)


def bundled_key_scopes() -> list[str]:
    text = read(ROOT / "unlimited_skills" / "signatures.py")
    match = re.search(r'"scopes":\s*\[([^\]]+)\]', text, re.MULTILINE)
    require(match is not None, "bundled trusted manifest key scopes are missing")
    return re.findall(r'"([^"]+)"', match.group(1))


def all_docs_text() -> str:
    return "\n".join(read(path) for path in DOC_PATHS if path.exists())


def assert_no_private_material(paths: list[Path]) -> None:
    patterns = {
        "pem_private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        "openssh_private_key": r"-----BEGIN OPENSSH PRIVATE KEY-----",
        "github_pat": r"gh[pousr]_[A-Za-z0-9_]{20,}",
        "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
        "raw_uls_token": r"uls_(?:hub|token|license)_[A-Za-z0-9_\-]{12,}",
        "device_private_key_assignment": r"device_private_key\s*[:=]\s*[A-Za-z0-9_\-]{12,}",
    }
    offenders: list[str] = []
    for path in paths:
        if not path.exists() or path.is_dir():
            continue
        text = read(path)
        for name, pattern in patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    require(not offenders, "possible private material in release artifacts: " + ", ".join(offenders))


def assert_docs() -> None:
    text = all_docs_text()
    lowered = text.lower()
    require(RELEASE in text, "release docs do not identify v0.2.2-alpha")
    require("full catalog distribution remains disabled" in lowered or "full catalog distribution is disabled" in lowered, "docs do not state full catalog is disabled")
    require("allowlist-only" in lowered, "docs do not state Local Skill Hub is allowlist-only")
    require("hosted remote manifests must include valid signed manifest envelopes" in lowered, "docs do not state hosted manifests require signatures")
    require("release-channels" in lowered, "docs do not document release-channel signed manifest scope")
    require("archive bytes are sha256-verified" in lowered or "archive bytes still require sha256 verification" in lowered or "archive bytes are accepted only after sha256 verification" in lowered, "docs do not state archive-byte SHA256 boundary")
    require("unlimited-skills serve` remains" in text or "`serve` is the free local daemon and remains unregistered" in text, "docs do not preserve unregistered serve boundary")
    require("`unlimited-skills hub serve` remains registration-gated" in text or "`hub serve` is a separate registration-required product command" in text, "docs do not preserve registration-gated hub serve boundary")
    require("enterprise skill lock local policy mvp" in lowered or "enterprise skill lock is an opt-in local policy mvp" in lowered, "docs do not document Enterprise Skill Lock as local policy MVP")
    require("managed hosted policy sync" in lowered, "docs do not document Enterprise Skill Lock managed hosted sync limitation")

    forbidden = [
        "full catalog distribution is enabled",
        "full catalog distribution allowed",
        "unsigned hosted manifests are accepted",
        "unsigned hosted manifests accepted",
        "archive bytes are cryptographically signed",
        "signed archives are verified",
        "archive-byte signatures are implemented in v0.2.2-alpha",
        "enterprise skill lock is planned, not implemented",
    ]
    found = [phrase for phrase in forbidden if phrase in lowered]
    require(not found, "docs contain unsafe release claims: " + ", ".join(found))


def assert_manifest(package_version: str) -> dict:
    require(MANIFEST.is_file(), f"missing release manifest: {MANIFEST.relative_to(ROOT)}")
    try:
        payload = json.loads(read(MANIFEST))
    except json.JSONDecodeError as exc:
        fail(f"release manifest is invalid JSON: {exc}")
    require(isinstance(payload, dict), "release manifest must be a JSON object")
    require(payload.get("release") == RELEASE, "release manifest release mismatch")
    require(payload.get("package_version") == package_version, "release manifest package_version mismatch")
    require(payload.get("git", {}).get("tag") == RELEASE, "release manifest tag mismatch")
    sha = payload.get("git", {}).get("sha")
    require(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha), "release manifest git.sha must be a 40-hex release candidate SHA")
    placeholder = "pending" + "_final_gate_merge_commit"
    require(sha != placeholder, "release manifest still contains placeholder git.sha")
    private_prs = payload.get("required_prs", {}).get("private_registry", [])
    public_prs = payload.get("required_prs", {}).get("public", [])
    require([item.get("number") for item in private_prs] == [2, 3, 4, 5, 6], "release manifest private PR list mismatch")
    require([item.get("number") for item in public_prs] == list(range(13, 28)), "release manifest public PR list mismatch")
    require(payload.get("required_prs", {}).get("finalization_branch") == "release/v0.2.2-alpha-final-gate", "release manifest finalization branch mismatch")
    require(payload.get("required_prs", {}).get("publication_branch") == "release/v0.2.2-alpha-publication", "release manifest publication branch mismatch")
    require(payload.get("distribution_policy", {}).get("full_catalog_distribution") is False, "manifest must keep full catalog disabled")
    require(payload.get("distribution_policy", {}).get("hub_distribution_mode") == "allowlist_only", "manifest must keep hub allowlist-only")
    security = payload.get("security_boundary", {})
    require(security.get("hosted_remote_manifests_require_valid_signatures") is True, "manifest must require signed hosted manifests")
    require(security.get("archive_bytes_verified_by_sha256") is True, "manifest must require archive SHA256")
    require(security.get("archive_bytes_cryptographically_signed") is False, "manifest must not claim archive-byte signatures")
    require(security.get("production_hosted_calls_in_tests") is False, "manifest must block production hosted calls in tests")
    manifest_scopes = set(security.get("manifest_scopes", []))
    require("release-channels" in manifest_scopes, "manifest missing release-channels scope")
    commands = payload.get("required_test_commands", [])
    require(
        "python scripts/run-v0.2.2-alpha-cross-repo-smoke.py --fixture-mode --temp-home" in commands,
        "manifest missing v0.2.2 cross-repo smoke command",
    )
    require("python scripts/verify-v0.2.2-alpha-publication.py" in commands, "manifest missing publication verifier command")
    scope = payload.get("feature_scope", [])
    require("release channel naming fixed to stable, beta, and canary" in scope, "manifest missing channel naming decision")
    require("production service onboarding diagnostics" in scope, "manifest missing production service diagnostics scope")
    require("Enterprise Skill Lock local policy MVP" in scope, "manifest missing Enterprise Skill Lock scope")
    require("private registry deployment and operations package" in scope, "manifest missing private registry deployment ops scope")
    key_records = payload.get("public_trusted_manifest_keys", [])
    key_ids = [item.get("key_id") for item in key_records]
    require("registry-alpha-2026-06" in key_ids, "manifest missing bundled trusted key id")
    official = next(item for item in key_records if item.get("key_id") == "registry-alpha-2026-06")
    require("release-channels" in set(official.get("scopes", [])), "manifest official key missing release-channels scope")
    return payload


def main() -> int:
    package_version = load_package_version()
    init_version = load_init_version()
    require(package_version == PACKAGE_VERSION, f"pyproject version must be {PACKAGE_VERSION}, got {package_version}")
    require(init_version == package_version, f"__version__ {init_version} != pyproject {package_version}")
    scopes = set(bundled_key_scopes())
    require("release-channels" in scopes, "bundled official trusted manifest key must allow release-channels scope")
    assert_manifest(package_version)
    assert_docs()
    release_artifacts = DOC_PATHS + [MANIFEST]
    assert_no_private_material(release_artifacts)
    print("v0.2.2-alpha release verification passed")
    print(f"manifest: {MANIFEST.relative_to(ROOT)}")
    print("production hosted calls: not required by release verification")
    print("private key/token scan: passed for release artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
