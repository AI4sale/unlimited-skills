from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.9-alpha"
VERSION = "0.4.9"
MANIFEST = ROOT / "docs" / "releases" / "v0.4.9-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.4.9-alpha.md",
    ROOT / "docs" / "releases" / "v0.4.9-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.4.9-alpha-upgrade-notes.md",
    ROOT / "docs" / "releases" / "v0.4.9-alpha-known-issues.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "SECURITY.md",
    ROOT / "docs" / "mcp-profile-rollout.md",
    ROOT / "docs" / "mcp-trust-store.md",
    ROOT / "docs" / "mcp-signed-profile-bundles.md",
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
ALLOWED_PRIVATE_MARKER_DOCS = {
    ROOT / "docs" / "mcp-trust-store.md",
    ROOT / "docs" / "mcp-signed-profile-bundles.md",
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


def load_integration_smoke():
    path = ROOT / "scripts" / "run-v049-alpha-profile-rollout-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v049_alpha_profile_rollout_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load integration smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    require(git.get("base_branch") == "main", "base branch mismatch")
    require(git.get("publication_branch") == "release/v0.4.9-alpha-final-publication", "publication branch mismatch")
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(git.get("tag_status") == "pending_codex_publication_after_verifier", "manifest tag status mismatch")
    require("after final publication verifier passes" in str(git.get("tag_target_sha_policy", "")).lower(), "tag policy must require final verifier")
    prs = payload.get("required_prs") if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    for number in (107, 108, 109, 110, 112):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    boundary = payload.get("safety_boundary") if isinstance(payload.get("safety_boundary"), dict) else {}
    for key in (
        "alpha_only",
        "fixture_mode",
        "profile_rollout_integration",
        "dry_run_only",
        "codex_pushes_tag",
    ):
        require(boundary.get(key) is True, f"safety boundary must set {key}")
    require(boundary.get("codex_must_not_push_tag") is False, "final publication gate should own Codex tag push")
    for key in (
        "production_rollout",
        "profile_activation",
        "trust_store_mutation",
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
    evidence = payload.get("integration_evidence") if isinstance(payload.get("integration_evidence"), dict) else {}
    for key in (
        "release_smoke_runner",
        "publication_verifier",
        "rollout_smoke_runner",
        "rollout_verifier",
        "integration_test",
    ):
        require(key in evidence, f"manifest missing evidence pointer: {key}")
    return payload


def assert_docs() -> None:
    for path in RELEASE_DOCS:
        require(path.is_file(), f"missing release doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in PUBLIC_DOCS if path.exists()).lower()
    for required in (
        "v0.4.9-alpha",
        "mcp profile rollout simulator",
        "final publication gate",
        "git tag -a v0.4.9-alpha",
        "after the final publication verifier passes",
        "rollout-plan",
        "policy doctor",
        "dry-run",
        "raw profile rollout plan",
        "signed bundle rollout plan",
        "trust-store-backed rollout plan",
        "no upstream spawn",
        "no network",
        "no mutation",
        "no profile activation",
        "no trust-store mutation",
        "no hosted trust fetch",
        "no registry sync",
        "no production signing keys",
        "no oauth",
        "no resources",
        "no prompts",
    ):
        require(required in text, f"docs missing required wording: {required}")


def assert_smoke(report: dict[str, Any]) -> None:
    require(report.get("status") == "passed", "integration smoke status mismatch")
    require(report.get("release") == RELEASE, "integration smoke release mismatch")
    for key in (
        "production_hosted_calls",
        "hosted_trust_fetch",
        "registry_sync",
        "profile_activation",
        "trust_store_mutation",
        "oauth",
        "remote_upstreams",
        "mcp_resources",
        "mcp_prompts",
        "production_signing_keys",
        "private_key_storage",
        "telemetry",
    ):
        require(report.get(key) is False, f"integration smoke must disable {key}")
    proofs = report.get("proofs") if isinstance(report.get("proofs"), dict) else {}
    for key in ("no_upstream_spawn", "no_network", "no_mutation"):
        require(proofs.get(key) is True, f"integration smoke proof missing: {key}")


def assert_no_private_material() -> None:
    offenders: list[str] = []
    for path in PUBLIC_DOCS:
        if not path.exists():
            continue
        text = read(path)
        for name, pattern in PRIVATE_MATERIAL_PATTERNS.items():
            if name in {"pem_private_key", "openssh_private_key"} and path in ALLOWED_PRIVATE_MARKER_DOCS:
                continue
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    require(not offenders, "possible private material in public release docs: " + ", ".join(offenders))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify v0.4.9-alpha publication before Codex tagging.")
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
    smoke = load_integration_smoke().collect_evidence()
    assert_smoke(smoke)
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
        "profile_rollout_integration": True,
        "dry_run_only": True,
        "production_hosted_calls": False,
        "hosted_trust_fetch": False,
        "registry_sync": False,
        "profile_activation": False,
        "trust_store_mutation": False,
        "production_signing_keys": False,
        "private_key_storage": False,
        "oauth_resources_prompts": False,
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
        print("MCP profile rollout simulator integration: passed")
        print("hosted trust fetch: false")
        print("registry sync: false")
        print("profile activation: false")
        print("trust-store mutation: false")
        print("private key/token/proof/prompt/skill-body/local-path scan: passed")
        print("tag command:")
        print(report["tag_command"])
        print(f"git push origin {RELEASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
