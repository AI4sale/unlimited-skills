from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.2.1-alpha"
MANIFEST = ROOT / "docs" / "releases" / "v0.2.1-alpha.release-manifest.json"
DOC_PATHS = [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "known-limitations.md",
    ROOT / "docs" / "release-process.md",
    ROOT / "docs" / "release-smoke-tests.md",
    ROOT / "docs" / "public-core-boundary.md",
    ROOT / "docs" / "releases" / "v0.2.1-alpha.md",
    ROOT / "docs" / "releases" / "v0.2.1-alpha-checklist.md",
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
    require(RELEASE in text, "release docs do not identify v0.2.1-alpha")
    require("full catalog distribution remains disabled" in lowered or "full catalog distribution is disabled" in lowered, "docs do not state full catalog is disabled")
    require("allowlist-only" in lowered, "docs do not state Local Skill Hub is allowlist-only")
    require("hosted remote manifests must include valid signed manifest envelopes" in lowered, "docs do not state hosted manifests require signatures")
    require("archive bytes are sha256-verified" in lowered or "archive bytes still require sha256 verification" in lowered or "archive bytes are accepted only after sha256 verification" in lowered, "docs do not state archive-byte SHA256 boundary")
    require("unlimited-skills serve` remains" in text or "`serve` is the free local daemon and remains unregistered" in text, "docs do not preserve unregistered serve boundary")
    require("`unlimited-skills hub serve` remains registration-gated" in text or "`hub serve` is a separate registration-required product command" in text, "docs do not preserve registration-gated hub serve boundary")

    forbidden = [
        "full catalog distribution is enabled",
        "full catalog distribution allowed",
        "unsigned hosted manifests are accepted",
        "unsigned hosted manifests accepted",
        "archive bytes are cryptographically signed",
        "signed archives are verified",
        "archive-byte signatures are implemented in v0.2.1-alpha",
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
    public_prs = payload.get("required_prs", {}).get("public", [])
    require([item.get("number") for item in public_prs] == [13, 14, 15, 16, 17, 18, 19], "release manifest public PR list mismatch")
    require(payload.get("distribution_policy", {}).get("full_catalog_distribution") is False, "manifest must keep full catalog disabled")
    require(payload.get("distribution_policy", {}).get("hub_distribution_mode") == "allowlist_only", "manifest must keep hub allowlist-only")
    security = payload.get("security_boundary", {})
    require(security.get("hosted_remote_manifests_require_valid_signatures") is True, "manifest must require signed hosted manifests")
    require(security.get("archive_bytes_verified_by_sha256") is True, "manifest must require archive SHA256")
    require(security.get("archive_bytes_cryptographically_signed") is False, "manifest must not claim archive-byte signatures")
    require(security.get("production_hosted_calls_in_tests") is False, "manifest must block production hosted calls in tests")
    key_ids = [item.get("key_id") for item in payload.get("public_trusted_manifest_keys", [])]
    require("registry-alpha-2026-06" in key_ids, "manifest missing bundled trusted key id")
    return payload


def main() -> int:
    package_version = load_package_version()
    init_version = load_init_version()
    require(package_version == "0.2.1", f"pyproject version must be 0.2.1, got {package_version}")
    require(init_version == package_version, f"__version__ {init_version} != pyproject {package_version}")
    assert_manifest(package_version)
    assert_docs()
    release_artifacts = DOC_PATHS + [MANIFEST]
    assert_no_private_material(release_artifacts)
    print("v0.2.1-alpha release verification passed")
    print(f"manifest: {MANIFEST.relative_to(ROOT)}")
    print("production hosted calls: not required by release verification")
    print("private key/token scan: passed for release artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
