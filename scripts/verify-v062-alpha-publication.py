"""Verify the v0.6.2-alpha non-English routing hotfix publication gate."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.6.2-alpha"
VERSION = "0.6.2"
MANIFEST = ROOT / "docs" / "releases" / "v0.6.2-alpha.release-manifest.json"
REQUIRED_DOCS = [
    ROOT / "docs" / "releases" / "v0.6.2-alpha.md",
    ROOT / "docs" / "releases" / "v0.6.2-alpha-pypi-publishing.md",
    ROOT / "docs" / "releases" / "v0.6.x-release-operator-runbook.md",
    ROOT / "docs" / "releases" / "v0.6-contract-freeze-spec.md",
    ROOT / "docs" / "context-reduction-model.md",
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    MANIFEST,
]


def load_v060_verifier():
    path = ROOT / "scripts" / "verify-v060-alpha-publication.py"
    spec = importlib.util.spec_from_file_location("verify_v060_alpha_publication", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load publication verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RELEASE = RELEASE
    module.VERSION = VERSION
    module.MANIFEST = MANIFEST
    module.REQUIRED_DOCS = REQUIRED_DOCS
    module.load_package_smoke = load_package_smoke
    module.assert_manifest = assert_manifest
    module.assert_docs = assert_docs
    module.release_blocker = release_blocker
    return module


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"{RELEASE} verification failed: {message}")


def load_package_smoke():
    path = ROOT / "scripts" / "run-v062-alpha-package-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v062_alpha_package_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_version") == VERSION, "manifest package version mismatch")
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(git.get("tag_status") == "blocked_until_pypi_upload_and_post_publish_smoke", "manifest must keep the release tag blocked until PyPI smoke passes")
    required_prs = payload.get("required_prs") if isinstance(payload.get("required_prs"), dict) else {}
    public_prs = required_prs.get("public") if isinstance(required_prs.get("public"), list) else []
    public_numbers = {item.get("number") for item in public_prs if isinstance(item, dict)}
    require({167, 168}.issubset(public_numbers), "manifest must include #167 and #168 in public required PRs")
    excluded = payload.get("excluded_prs") if isinstance(payload.get("excluded_prs"), list) else []
    require(119 in excluded, "#119 must be explicitly excluded from v0.6.2")
    requirements = payload.get("adoption_toolchain_requirements") if isinstance(payload.get("adoption_toolchain_requirements"), dict) else {}
    for key in (
        "contract_freeze",
        "local_roi_receipt",
        "package_smoke",
        "non_english_retrieval_rescue",
        "router_metrics",
        "multilingual_install_guidance",
    ):
        require(requirements.get(key) is True, f"manifest adoption requirement must be true: {key}")
    return payload


def assert_docs() -> None:
    for path in REQUIRED_DOCS:
        require(path.is_file(), f"missing required doc: {path.relative_to(ROOT)}")
    public_text = "\n".join(read(path) for path in REQUIRED_DOCS if path.exists()).lower()
    for required in (
        "v0.6.2-alpha",
        "unlimited-skills==0.6.2",
        "non-english users got zero",
        "multilingual",
        "vector",
        "daemon",
        "router-metrics.json",
        "no telemetry",
        "no hosted",
        "no team",
        "no enterprise",
        "#119",
    ):
        require(required in public_text, f"public docs missing required wording: {required}")


def release_blocker(reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "code": reason,
        "owner": "PyPI account / GitHub Trusted Publisher setup",
        "action": "Publish unlimited-skills 0.6.2 through the manual Trusted Publishing workflow, then rerun the post-publish smoke.",
        "fallback": "Keep v0.6.2-alpha tag and GitHub prerelease blocked; do not mark the package release as published.",
        "details": details or {},
    }


def main(argv: list[str] | None = None) -> int:
    return load_v060_verifier().main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
