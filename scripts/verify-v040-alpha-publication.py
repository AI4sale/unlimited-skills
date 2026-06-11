from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.0-alpha"
VERSION = "0.4.0"
MANIFEST = ROOT / "docs" / "releases" / "v0.4.0-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.4.0-alpha.md",
    ROOT / "docs" / "releases" / "v0.4.0-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.4.0-alpha-upgrade-notes.md",
    ROOT / "docs" / "releases" / "v0.4.0-alpha-known-issues.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "known-limitations.md",
    ROOT / "docs" / "policy-aware-recommendations.md",
    ROOT / "docs" / "eval-release-gates.md",
    ROOT / "docs" / "maintainer-queue-status.md",
    ROOT / "docs" / "governance-dashboard.md",
]
PRIVATE_MATERIAL_PATTERNS = {
    "pem_private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "openssh_private_key": r"-----BEGIN OPENSSH PRIVATE KEY-----",
    "github_pat": r"gh[pousr]_[A-Za-z0-9_]{20,}",
    "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
    "raw_uls_token": r"uls_(?:hub|token|license)_[A-Za-z0-9_\-]{16,}",
    "device_private_key_assignment": r"device_private_key\s*[:=]\s*[A-Za-z0-9_\-]{16,}",
    "checkout_url_field": r'"checkout_url"\s*:',
    "payment_link_field": r'"payment_link"\s*:',
    "catalog_body_field": r'"skill_bod(?:y|ies)"\s*:',
    "prompt_body_field": r'"(?:prompt|prompts|task_text|customer_data)"\s*:\s*"[^"]+"',
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} publication verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def package_version() -> str:
    return str(tomllib.loads(read(ROOT / "pyproject.toml"))["project"]["version"])


def init_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', read(ROOT / "unlimited_skills" / "__init__.py"))
    require(match is not None, "__version__ is missing")
    return str(match.group(1))


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


def resolve_ref(ref: str) -> str:
    return run_git(["rev-parse", ref]).stdout.strip()


def tag_exists(tag: str) -> bool:
    return run_git(["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"], check=False).returncode == 0


def assert_clean_worktree() -> None:
    status = run_git(["status", "--short"]).stdout.strip()
    require(not status, "working tree must be clean before publication verification")


def load_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing release manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(isinstance(payload, dict), "release manifest must be a JSON object")
    return payload


def assert_manifest(payload: dict[str, Any]) -> None:
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_version") == VERSION, "manifest package version mismatch")
    require(payload.get("distribution") == "github-clone-alpha", "GitHub clone must remain distribution path")
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("publication_branch") == "release/v0.4.0-alpha-final-publication", "manifest publication branch mismatch")
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(git.get("tag_status") == "pending_release_owner_approval", "manifest must require human tag approval")
    require("release owner" in str(git.get("tag_target_sha_policy", "")).lower(), "manifest must document release-owner tag policy")

    prs = payload.get("required_prs", {}) if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    private_numbers = [item.get("number") for item in prs.get("private_registry", []) if isinstance(item, dict)]
    for number in (69, 74, 75):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    for number in (42, 43, 44):
        require(number in private_numbers, f"manifest missing private registry PR #{number}")

    boundary = payload.get("safety_boundary", {}) if isinstance(payload.get("safety_boundary"), dict) else {}
    for key in (
        "alpha_only",
        "mit_local_core_registration_free",
        "signed_hosted_manifests_required",
    ):
        require(boundary.get(key) is True, f"safety boundary must set {key}")
    for key in (
        "production_rollout",
        "automatic_telemetry",
        "prompt_upload",
        "skill_body_upload",
        "automatic_hosted_query_forwarding",
        "automatic_rewriting",
        "automatic_install_update_remove",
        "auto_publish",
        "live_billing",
        "pypi",
        "full_catalog_distribution",
        "private_registry_content_committed",
    ):
        require(boundary.get(key) is False, f"safety boundary must disable {key}")

    commands = payload.get("required_test_commands", [])
    for command in (
        ".venv\\Scripts\\python.exe -m pytest tests -q",
        ".venv\\Scripts\\python.exe scripts\\run-v0.2x-smoke-tests.py",
        ".venv\\Scripts\\python.exe scripts\\run-v040-alpha-release-smoke.py",
        ".venv\\Scripts\\python.exe scripts\\verify-v040-alpha-publication.py --expected-sha <current-sha>",
        ".venv\\Scripts\\python.exe -m compileall -q unlimited_skills scripts tests",
        "git diff --check",
    ):
        require(command in commands, f"manifest missing test command: {command}")

    evidence = payload.get("publication_evidence", {}) if isinstance(payload.get("publication_evidence"), dict) else {}
    require(evidence.get("codex_may_push_tag") is False, "Codex must not be allowed to push the final tag")
    require(evidence.get("tag_command_owner") == "release-owner", "release owner must own the tag command")


def assert_docs() -> None:
    for path in RELEASE_DOCS:
        require(path.is_file(), f"missing release doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in PUBLIC_DOCS if path.exists()).lower()
    for required in (
        "v0.4.0-alpha",
        "skillops foundation",
        "policy-aware recommendation preview",
        "eval release",
        "maintainer queue",
        "governance dashboard",
        "support bundle",
        "github clone",
        "release owner",
        "pending release-owner approval",
        "no production rollout",
        "no live billing",
        "no pypi",
        "no full catalog distribution",
        "no automatic install",
        "no automatic rewriting",
        "no auto-publish",
        "mit local core",
    ):
        require(required in text, f"docs missing required wording: {required}")
    forbidden_claims = (
        "production rollout is enabled",
        "live billing is enabled",
        "full catalog distribution is enabled",
        "automatic skill rewriting is enabled",
        "codex pushes the release tag",
        "pypi is the supported v0.4.0-alpha distribution path",
    )
    for claim in forbidden_claims:
        require(claim not in text, f"docs contain unsafe release claim: {claim}")


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify v0.4.0-alpha final publication before tagging.")
    parser.add_argument("--expected-sha", help="Final tag target SHA to compare with the current checkout")
    parser.add_argument(
        "--allow-existing-tag",
        action="store_true",
        help="Post-publication mode: allow the release tag when it already points to --expected-tag-sha.",
    )
    parser.add_argument("--expected-tag-sha", help="Expected commit for the existing release tag in post-publication mode")
    parser.add_argument(
        "--allow-newer-package",
        action="store_true",
        help="Allow the checkout package version to be newer than the v0.4.0 release package.",
    )
    args = parser.parse_args(argv)

    assert_clean_worktree()
    current_package_version = package_version()
    current_init_version = init_version()
    if args.allow_newer_package:
        require(
            current_package_version == VERSION or current_package_version.startswith("0.4."),
            f"pyproject version must be {VERSION} or a newer v0.4.x release",
        )
        require(
            current_init_version == VERSION or current_init_version.startswith("0.4."),
            f"__version__ must be {VERSION} or a newer v0.4.x release",
        )
    else:
        require(current_package_version == VERSION, f"pyproject version must be {VERSION}")
        require(current_init_version == VERSION, f"__version__ must be {VERSION}")
    existing_tag = tag_exists(RELEASE)
    if args.allow_existing_tag:
        require(args.expected_tag_sha is not None, "--expected-tag-sha is required with --allow-existing-tag")
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_tag_sha) is not None, "--expected-tag-sha must be 40 lowercase hex")
        require(existing_tag, f"tag {RELEASE} must exist in post-publication mode")
        tag_target = resolve_ref(f"{RELEASE}^{{commit}}")
        require(tag_target == args.expected_tag_sha, f"tag {RELEASE} points to {tag_target}, expected {args.expected_tag_sha}")
    else:
        require(not existing_tag, f"tag {RELEASE} already exists locally; Codex must not create the final tag")
    assert_manifest(load_manifest())
    assert_docs()
    assert_no_private_material()
    current_head = git_head()
    if args.expected_sha:
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(current_head == args.expected_sha, f"current checkout {current_head} does not match expected tag target {args.expected_sha}")
    print(f"{RELEASE} final publication verification passed")
    print(f"manifest: {MANIFEST.relative_to(ROOT)}")
    print(f"current checkout sha: {current_head}")
    if args.allow_existing_tag:
        print(f"existing tag target verified: {args.expected_tag_sha}")
    print("distribution path: GitHub clone")
    print("tag status: " + ("already published by release owner" if args.allow_existing_tag else "pending release-owner approval"))
    print("production hosted calls: blocked by fixture-mode release commands")
    print("private key/token/payment-field scan: passed for public release docs")
    print("human tag command:")
    print(f"git tag -a {RELEASE} {current_head} -m \"{RELEASE}\"")
    print(f"git push origin {RELEASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
