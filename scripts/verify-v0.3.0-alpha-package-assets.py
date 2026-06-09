from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.3.0"
RELEASE = "v0.3.0-alpha"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"v0.3.0-alpha package asset verification failed: {message}")


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
    return match.group(1)


def assert_required_assets() -> None:
    required_files = [
        "skills/skill-router/SKILL.md",
        "skills/router-claude-code/SKILL.md",
        "skills/router-hermes/SKILL.md",
        "skills/router-openclaw/SKILL.md",
        "scripts/install-codex.sh",
        "scripts/install-codex.ps1",
        "scripts/install-claude-code.sh",
        "scripts/install-claude-code.ps1",
        "scripts/install-hermes.sh",
        "scripts/install-hermes.ps1",
        "scripts/install-openclaw.sh",
        "scripts/install-openclaw.ps1",
        "scripts/migrate-codex.sh",
        "scripts/migrate-codex.ps1",
        "scripts/rollback-hermes.sh",
        "scripts/rollback-hermes.ps1",
        "schemas/enterprise-policy-assignment.schema.json",
        "docs/install-upgrade-uninstall.md",
        "docs/packaging.md",
    ]
    missing = [item for item in required_files if not (ROOT / item).is_file()]
    require(not missing, "missing required repo assets: " + ", ".join(missing))


def assert_installer_flags() -> None:
    installers = [
        ROOT / "scripts" / "install-codex.sh",
        ROOT / "scripts" / "install-claude-code.sh",
        ROOT / "scripts" / "install-hermes.sh",
        ROOT / "scripts" / "install-openclaw.sh",
    ]
    for path in installers:
        text = read(path)
        require("--skip-pip-install" in text, f"{path.relative_to(ROOT)} missing --skip-pip-install")
        require("--hub-token-env" in text, f"{path.relative_to(ROOT)} missing --hub-token-env")
        require("--hub-token" in text, f"{path.relative_to(ROOT)} missing --hub-token private config support")
        require("rm -rf" not in text, f"{path.relative_to(ROOT)} must not use rm -rf")
    codex_text = read(ROOT / "scripts" / "install-codex.sh")
    require("--no-agents-patch" in codex_text, "Codex installer must expose --no-agents-patch")
    claude_text = read(ROOT / "scripts" / "install-claude-code.sh")
    require("--no-claude-patch" in claude_text, "Claude Code installer must expose --no-claude-patch")


def assert_docs() -> None:
    docs = "\n".join(
        read(path)
        for path in [
            ROOT / "README.md",
            ROOT / "SECURITY.md",
            ROOT / "docs" / "known-limitations.md",
            ROOT / "docs" / "support-matrix.md",
            ROOT / "docs" / "install-upgrade-uninstall.md",
            ROOT / "docs" / "packaging.md",
        ]
    )
    lowered = docs.lower()
    require(RELEASE in docs, "docs must identify v0.3.0-alpha")
    require("pypi is not the supported v0.3.0-alpha distribution path" in lowered, "PyPI alpha decision is not explicit")
    require("github clone" in lowered, "GitHub clone install path is not documented")
    require("do not delete arbitrary" in lowered or "must not delete pre-existing local library files" in lowered, "local library deletion guardrail is missing")
    unsafe = [
        "pypi is the supported v0.3.0-alpha distribution path",
        "delete the local library during sync",
        "rm -rf ~/.unlimited-skills",
    ]
    found = [phrase for phrase in unsafe if phrase in lowered]
    require(not found, "docs contain unsafe packaging/install claims: " + ", ".join(found))


def main() -> int:
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")
    assert_required_assets()
    assert_installer_flags()
    assert_docs()
    print("v0.3.0-alpha package asset verification passed")
    print("distribution path: GitHub clone")
    print("pypi support: not supported for this alpha")
    print("required repo assets: present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
