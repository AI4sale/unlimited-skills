"""Verify the v0.5.0-alpha public packaging gate."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.5.0-alpha"
VERSION = "0.5.0"
MANIFEST = ROOT / "docs" / "releases" / "v0.5.0-alpha.release-manifest.json"
REQUIRED_DOCS = [
    ROOT / "docs" / "releases" / "v0.5.0-alpha.md",
    ROOT / "docs" / "releases" / "v0.5.0-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.5.0-alpha-known-issues.md",
    ROOT / "docs" / "releases" / "v0.5.0-alpha-readme-risks.md",
    ROOT / "docs" / "feedback.md",
    ROOT / "docs" / "adoption" / "marketplace-listing-copy.md",
    MANIFEST,
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} verification failed: {message}")


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


def git_head() -> str:
    return run_git(["rev-parse", "HEAD"]).stdout.strip()


def tag_exists(tag: str) -> bool:
    return run_git(["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"], check=False).returncode == 0


def assert_clean_worktree() -> None:
    status = run_git(["status", "--short"]).stdout.strip()
    require(not status, "working tree must be clean for publication verification")


def package_version() -> str:
    return str(tomllib.loads(read(ROOT / "pyproject.toml"))["project"]["version"])


def project_urls() -> dict[str, str]:
    return dict(tomllib.loads(read(ROOT / "pyproject.toml"))["project"].get("urls", {}))


def init_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', read(ROOT / "unlimited_skills" / "__init__.py"))
    require(match is not None, "__version__ is missing")
    return str(match.group(1))


def plugin_versions() -> tuple[str, str]:
    plugin = json.loads(read(ROOT / "plugin" / ".claude-plugin" / "plugin.json"))
    marketplace = json.loads(read(ROOT / ".claude-plugin" / "marketplace.json"))
    return str(plugin["version"]), str(marketplace["plugins"][0]["version"])


def load_package_smoke():
    path = ROOT / "scripts" / "run-v050-alpha-package-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v050_alpha_package_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_package_smoke() -> dict[str, Any]:
    module = load_package_smoke()
    import tempfile

    with tempfile.TemporaryDirectory(prefix="uls-v050-verifier-") as tmp_dir:
        tmp = Path(tmp_dir)
        dist_dir = tmp / "dist"
        dist_dir.mkdir()
        wheel, sdist = module.build_dist(dist_dir)
        report = {
            "schema_version": 1,
            "version": VERSION,
            "dist": module.inspect_dist(wheel, sdist),
            "clean_install": module.clean_install_smoke(wheel, tmp / "install"),
        }
        report["errors"] = module.verify(report)
        report["ok"] = not report["errors"]
        return report


def assert_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_version") == VERSION, "manifest package version mismatch")
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("publication_branch") == "release/v0.5.0-public-alpha", "publication branch mismatch")
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    requirements = payload.get("package_requirements") if isinstance(payload.get("package_requirements"), dict) else {}
    for key in (
        "wheel_includes_bundled_packs",
        "clean_install_quickstart",
        "clean_install_suggest",
        "clean_install_mcp_savings",
        "twine_check",
        "project_urls",
    ):
        require(requirements.get(key) is True, f"manifest package requirement must be true: {key}")
    require(requirements.get("deprecated_license_classifier") is False, "manifest must keep deprecated license classifier false")
    return payload


def assert_docs(package_availability: str) -> None:
    for path in REQUIRED_DOCS:
        require(path.is_file(), f"missing required doc: {path.relative_to(ROOT)}")
    readme = read(ROOT / "README.md")
    public_text = "\n".join(read(path) for path in REQUIRED_DOCS + [ROOT / "README.md", ROOT / "CHANGELOG.md"] if path.exists())
    for required in (
        "v0.5.0-alpha",
        "nothing for sale",
        "no telemetry",
        "bundled ECC + Superpowers",
        "scripts/run-v050-alpha-package-smoke.py",
    ):
        require(required.lower() in public_text.lower(), f"public docs missing required wording: {required}")
    has_flip_marker = "A3-PYPI-FLIP" in readme
    if package_availability == "not-published":
        require(has_flip_marker, "A3-PYPI-FLIP marker must remain until package availability is real")
        require('pip install "git+https://github.com/AI4sale/unlimited-skills.git"' in readme, "Git install command must remain before PyPI availability")
    else:
        require(not has_flip_marker, "A3-PYPI-FLIP marker must be removed after publication")
        pypi_install = "pip install " + "unlimited-skills"
        require(pypi_install in readme, "PyPI install command must be present after publication")


def assert_metadata() -> None:
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")
    require(plugin_versions() == (VERSION, VERSION), "Claude plugin and marketplace versions must match package version")
    urls = project_urls()
    for key in ("Homepage", "Repository", "Issues", "Changelog", "Documentation"):
        require(key in urls, f"missing project URL: {key}")
    classifiers = tomllib.loads(read(ROOT / "pyproject.toml"))["project"].get("classifiers", [])
    require("License :: OSI Approved :: MIT License" not in classifiers, "deprecated MIT license classifier must be absent")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", help="Expected release commit SHA")
    parser.add_argument(
        "--package-availability",
        choices=("not-published", "published"),
        default="not-published",
        help="Use published only after the package exists on the intended index and install commands are flipped.",
    )
    parser.add_argument("--allow-existing-tag", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true", help="Development-only mode for testing this verifier before committing.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.allow_dirty:
        assert_clean_worktree()
    assert_metadata()
    manifest = assert_manifest()
    assert_docs(args.package_availability)
    if args.expected_sha:
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(git_head() == args.expected_sha, f"current checkout {git_head()} does not match expected SHA {args.expected_sha}")
    if not args.allow_existing_tag:
        require(not tag_exists(RELEASE), f"tag {RELEASE} already exists locally")
    package_smoke = run_package_smoke()
    require(package_smoke.get("ok") is True, "package smoke failed: " + ", ".join(package_smoke.get("errors") or []))
    report = {
        "schema_version": 1,
        "status": "passed",
        "release": RELEASE,
        "version": VERSION,
        "package_availability": args.package_availability,
        "current_checkout_sha": git_head(),
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "required_prs": manifest.get("required_prs", {}),
        "package_smoke": {
            "wheel_skill_count": package_smoke["dist"]["wheel_skill_count"],
            "quickstart_skill_count": package_smoke["clean_install"]["quickstart_library"]["skill_count"],
            "version_output": package_smoke["clean_install"]["version_output"],
            "suggest_candidates": package_smoke["clean_install"]["suggest_candidates"],
            "twine_check": True,
        },
        "tag_command": f"git tag -a {RELEASE} {git_head()} -m \"{RELEASE}\"",
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} verification passed")
        print(json.dumps(report["package_smoke"], ensure_ascii=False, indent=2, sort_keys=True))
        print("tag command:")
        print(report["tag_command"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
