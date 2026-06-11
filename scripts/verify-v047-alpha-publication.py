from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.7-alpha"
VERSION = "0.4.7"
MANIFEST = ROOT / "docs" / "releases" / "v0.4.7-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.4.7-alpha.md",
    ROOT / "docs" / "releases" / "v0.4.7-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.4.7-alpha-upgrade-notes.md",
    ROOT / "docs" / "releases" / "v0.4.7-alpha-known-issues.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "mcp-signed-profile-bundles.md",
    ROOT / "docs" / "mcp-gateway.md",
    ROOT / "docs" / "mcp-permissioned-tool-profiles.md",
    ROOT / "docs" / "unlimited-tools.md",
]
PRIVATE_MATERIAL_PATTERNS = {
    "pem_private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "openssh_private_key": r"-----BEGIN OPENSSH PRIVATE KEY-----",
    "github_pat": r"gh[pousr]_[A-Za-z0-9_]{20,}",
    "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
    "raw_uls_token": r"uls_(?:hub|token|license)_[A-Za-z0-9_\-]{16,}",
    "prompt_body_field": r'"(?:prompt|prompts|task_text|customer_data)"\s*:\s*"[^"]+"',
    "local_windows_user_path": r"[A-Za-z]:\\Users\\tedja\\",
    "local_repo_path": r"D:\\git\\",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} publication verification failed: {message}")


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


def resolve_ref(ref: str) -> str:
    return run_git(["rev-parse", ref]).stdout.strip()


def tag_exists(tag: str) -> bool:
    return run_git(["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"], check=False).returncode == 0


def assert_clean_worktree() -> None:
    status = run_git(["status", "--short"]).stdout.strip()
    require(not status, "working tree must be clean before publication verification")


def assert_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing release manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_version") == VERSION, "manifest package version mismatch")
    require(payload.get("distribution") == "github-clone-alpha", "GitHub clone must remain distribution path")
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("publication_branch") == "release/v0.4.7-alpha-final-publication", "publication branch mismatch")
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(git.get("tag_status") == "pending_codex_publication_after_verifier", "manifest tag status mismatch")
    prs = payload.get("required_prs") if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    for number in (102, 103, 105):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    private_numbers = [item.get("number") for item in prs.get("private_registry", []) if isinstance(item, dict)]
    require(50 in private_numbers, "manifest missing private registry PR #50")
    boundary = payload.get("safety_boundary") if isinstance(payload.get("safety_boundary"), dict) else {}
    for key in (
        "alpha_only",
        "fixture_mode",
        "signed_profile_bundle_integration",
        "raw_local_profiles_still_allowed_by_default",
        "registered_business_signed_required_future_gated",
        "codex_pushes_tag",
    ):
        require(boundary.get(key) is True, f"safety boundary must set {key}")
    for key in (
        "production_rollout",
        "production_hosted_calls",
        "hosted_trust_fetch",
        "registry_sync",
        "oauth_upstreams",
        "remote_upstreams",
        "mcp_resources",
        "mcp_prompts",
        "production_signing_keys",
        "private_key_storage",
        "auto_publish",
        "live_billing",
        "pypi",
        "full_catalog_distribution",
    ):
        require(boundary.get(key) is False, f"safety boundary must disable {key}")
    return payload


def assert_docs() -> None:
    for path in RELEASE_DOCS:
        require(path.is_file(), f"missing release doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in PUBLIC_DOCS if path.exists()).lower()
    for required in (
        "v0.4.7-alpha",
        "signed mcp profile bundle",
        "may break before v0.6",
        "local mit core may still allow unsigned profiles",
        "registered/business signed-required behavior is future-gated",
        "no hosted trust fetch",
        "no registry sync",
        "no production signing keys",
        "no private key storage",
        "no oauth",
        "no resources",
        "no prompts",
        "git tag -a v0.4.7-alpha",
    ):
        require(required in text, f"docs missing required wording: {required}")


def assert_no_private_material() -> None:
    offenders: list[str] = []
    for path in PUBLIC_DOCS:
        if not path.exists():
            continue
        text = read(path)
        for name, pattern in PRIVATE_MATERIAL_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    require(not offenders, "possible private material in public release docs: " + ", ".join(offenders))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify v0.4.7-alpha publication before Codex tagging.")
    parser.add_argument("--expected-sha", help="Final tag target SHA to compare with the current checkout")
    parser.add_argument("--allow-existing-tag", action="store_true", help="Post-publication mode: allow an existing release tag.")
    parser.add_argument("--expected-tag-sha", help="Expected commit for the existing release tag in post-publication mode")
    parser.add_argument("--json", action="store_true", help="Print JSON evidence")
    args = parser.parse_args(argv)

    assert_clean_worktree()
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")
    require(plugin_versions() == (VERSION, VERSION), "Claude plugin and marketplace versions must match package version")
    existing_tag = tag_exists(RELEASE)
    if args.allow_existing_tag:
        require(args.expected_tag_sha is not None, "--expected-tag-sha is required with --allow-existing-tag")
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_tag_sha) is not None, "--expected-tag-sha must be 40 lowercase hex")
        require(existing_tag, f"tag {RELEASE} must exist in post-publication mode")
        tag_target = resolve_ref(f"{RELEASE}^{{commit}}")
        require(tag_target == args.expected_tag_sha, f"tag {RELEASE} points to {tag_target}, expected {args.expected_tag_sha}")
    else:
        require(not existing_tag, f"tag {RELEASE} already exists locally; use --allow-existing-tag for post-publication verification")
    manifest = assert_manifest()
    assert_docs()
    assert_no_private_material()
    current_head = git_head()
    if args.expected_sha:
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(current_head == args.expected_sha, f"current checkout {current_head} does not match expected tag target {args.expected_sha}")
    report = {
        "status": "passed",
        "release": RELEASE,
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "current_checkout_sha": current_head,
        "required_prs": manifest.get("required_prs", {}),
        "signed_profile_bundle_integration": True,
        "hosted_trust_fetch": False,
        "registry_sync": False,
        "production_signing_keys": False,
        "private_key_storage": False,
        "oauth_resources_prompts": False,
        "production_hosted_calls": False,
        "private_material_scan": "passed",
        "tag_command": f"git tag -a {RELEASE} {current_head} -m \"{RELEASE}\"",
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} publication verification passed")
        print(f"manifest: {MANIFEST.relative_to(ROOT)}")
        print(f"current checkout sha: {current_head}")
        if args.allow_existing_tag:
            print(f"existing tag target verified: {args.expected_tag_sha}")
        print("distribution path: GitHub clone")
        print("signed profile bundle integration: passed")
        print("hosted trust fetch: false")
        print("registry sync: false")
        print("production signing keys: false")
        print("private key/token/proof/prompt/skill-body/local-path scan: passed")
        print("tag command:")
        print(report["tag_command"])
        print(f"git push origin {RELEASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
