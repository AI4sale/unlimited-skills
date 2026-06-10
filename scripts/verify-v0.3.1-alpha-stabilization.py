from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.3.1-alpha"
VERSION = "0.3.1"
PUBLISHED_BASELINE = "v0.3.0-alpha"
PUBLISHED_BASELINE_URL = "https://github.com/AI4sale/unlimited-skills/releases/tag/v0.3.0-alpha"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.3.1-alpha.md",
    ROOT / "docs" / "releases" / "v0.3.1-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.3.1-alpha.release-health.md",
    ROOT / "docs" / "releases" / "v0.3.1-alpha.known-issues.md",
    ROOT / "docs" / "releases" / "v0.3.1-alpha-upgrade-notes.md",
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
    raise SystemExit(f"v0.3.1-alpha stabilization verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def package_version() -> str:
    data = tomllib.loads(read(ROOT / "pyproject.toml"))
    return str(data["project"]["version"])


def init_version() -> str:
    text = read(ROOT / "unlimited_skills" / "__init__.py")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    require(match is not None, "__version__ is missing")
    return str(match.group(1))


def assert_baseline_release_detected() -> str:
    local = run_git(["rev-parse", "--verify", f"refs/tags/{PUBLISHED_BASELINE}^{{commit}}"])
    if local.returncode == 0:
        return local.stdout.strip()
    remote = run_git(["ls-remote", "--tags", "origin", f"refs/tags/{PUBLISHED_BASELINE}"])
    require(remote.returncode == 0 and PUBLISHED_BASELINE in remote.stdout, f"{PUBLISHED_BASELINE} tag not detected locally or on origin")
    return "origin/" + PUBLISHED_BASELINE


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
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")
    baseline = assert_baseline_release_detected()
    assert_docs()
    assert_no_private_material()
    print("v0.3.1-alpha stabilization verification passed")
    print(f"release: {RELEASE}")
    print(f"published baseline: {PUBLISHED_BASELINE} ({baseline})")
    print("distribution path: GitHub clone")
    print("pypi support: deferred")
    print("MIT local core: unregistered")
    print("hosted features: registration-gated")
    print("full catalog distribution: disabled")
    print("private key/token/proof scan: passed for public stabilization docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
