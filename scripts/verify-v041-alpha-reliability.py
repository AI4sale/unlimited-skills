from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.1-alpha"
VERSION = "0.4.1"
MANIFEST = ROOT / "docs" / "releases" / "v0.4.1-alpha.release-manifest.json"
REQUIRED_FILES = [
    ROOT / "unlimited_skills" / "commands" / "skillops.py",
    ROOT / "unlimited_skills" / "installers" / "common.py",
    ROOT / "tests" / "test_install_rollback.py",
    ROOT / "tests" / "test_vector_sidecar.py",
    ROOT / "tests" / "test_skillops_usage_snapshot.py",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} reliability verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def package_version() -> str:
    return str(tomllib.loads(read(ROOT / "pyproject.toml"))["project"]["version"])


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def init_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', read(ROOT / "unlimited_skills" / "__init__.py"))
    require(match is not None, "__version__ is missing")
    return str(match.group(1))


def plugin_versions() -> tuple[str, str]:
    plugin = json.loads(read(ROOT / "plugin" / ".claude-plugin" / "plugin.json"))
    marketplace = json.loads(read(ROOT / ".claude-plugin" / "marketplace.json"))
    return str(plugin["version"]), str(marketplace["plugins"][0]["version"])


def git_head() -> str:
    return run_git(["rev-parse", "HEAD"]).stdout.strip()


def assert_release_files() -> None:
    for path in REQUIRED_FILES:
        require(path.exists(), f"missing required reliability file: {path.relative_to(ROOT)}")
    common = read(ROOT / "unlimited_skills" / "installers" / "common.py")
    require("class InstallTransaction" in common, "InstallTransaction is missing")
    require("def rollback_install" in common, "rollback_install is missing")
    skillops = read(ROOT / "unlimited_skills" / "commands" / "skillops.py")
    require("cmd_skillops_usage_snapshot" in skillops, "usage-snapshot command is not in commands/skillops.py")
    cli = read(ROOT / "unlimited_skills" / "cli.py")
    require("from .commands import skillops" in cli, "cli.py does not import skillops command module")
    require("usage-snapshot" in cli, "cli.py does not wire usage-snapshot")
    vector_tests = read(ROOT / "tests" / "test_vector_sidecar.py")
    require("VectorModelMismatch" in vector_tests, "vector model mismatch tests are missing")
    rollback_tests = read(ROOT / "tests" / "test_install_rollback.py")
    require("rollback" in rollback_tests.lower(), "rollback tests are missing")


def assert_manifest() -> None:
    require(MANIFEST.is_file(), f"missing release manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_version") == VERSION, "manifest package version mismatch")
    require(payload.get("distribution") == "github-clone-alpha", "GitHub clone must remain distribution path")
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("publication_branch") == "release/v0.4.1-alpha-reliability-publication", "publication branch mismatch")
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(git.get("tag_status") == "pending_release_owner_approval", "manifest must require release-owner tag approval")
    prs = payload.get("required_prs", {}) if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    for number in (82, 83):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    boundary = payload.get("safety_boundary", {}) if isinstance(payload.get("safety_boundary"), dict) else {}
    for key in (
        "production_rollout",
        "production_hosted_calls",
        "automatic_telemetry",
        "automatic_rewriting",
        "auto_publish",
        "live_billing",
        "pypi",
        "full_catalog_distribution",
        "codex_pushes_tag",
    ):
        require(boundary.get(key) is False, f"safety boundary must disable {key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the v0.4.1-alpha reliability publication package.")
    parser.add_argument("--expected-sha", help="Expected current checkout SHA")
    parser.add_argument(
        "--allow-newer-package",
        action="store_true",
        help="Post-publication compatibility mode: allow package/plugin metadata newer than v0.4.1.",
    )
    args = parser.parse_args(argv)

    current_package_version = package_version()
    current_init_version = init_version()
    current_plugin_versions = plugin_versions()
    if args.allow_newer_package:
        require(
            version_tuple(current_package_version) >= version_tuple(VERSION),
            f"pyproject version must be {VERSION} or newer",
        )
        require(
            version_tuple(current_init_version) >= version_tuple(VERSION),
            f"__version__ must be {VERSION} or newer",
        )
        require(
            current_plugin_versions[0] == current_plugin_versions[1] == current_package_version,
            "Claude plugin and marketplace versions must match package version",
        )
    else:
        require(current_package_version == VERSION, f"pyproject version must be {VERSION}")
        require(current_init_version == VERSION, f"__version__ must be {VERSION}")
        require(current_plugin_versions == (VERSION, VERSION), "Claude plugin and marketplace versions must match package version")
    assert_release_files()
    assert_manifest()
    head = git_head()
    if args.expected_sha:
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(head == args.expected_sha, f"current checkout {head} does not match expected {args.expected_sha}")
    print(f"{RELEASE} reliability verification passed")
    print(f"current checkout sha: {head}")
    print("rollback proof: InstallTransaction and rollback tests present")
    print("vector mismatch proof: VectorModelMismatch tests present")
    print("CLI facade/commands compatibility proof: skillops usage-snapshot wired through commands/skillops.py")
    print("production hosted calls: not required by reliability verifier")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
