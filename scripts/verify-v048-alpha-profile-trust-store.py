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
RELEASE = "v0.4.8-alpha"
VERSION = "0.4.8"
MANIFEST = ROOT / "docs" / "releases" / "v0.4.8-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.4.8-alpha.md",
    ROOT / "docs" / "releases" / "v0.4.8-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.4.8-alpha-known-issues.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "SECURITY.md",
    ROOT / "docs" / "mcp-trust-store.md",
    ROOT / "docs" / "mcp-signed-profile-bundles.md",
    ROOT / "docs" / "mcp-gateway.md",
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
    raise SystemExit(f"{RELEASE} profile trust-store verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def run_git(args: list[str]) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()


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


def load_smoke():
    path = ROOT / "scripts" / "run-v048-alpha-profile-trust-store-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v048_alpha_profile_trust_store_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing release manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("package_version") == VERSION, "manifest package version mismatch")
    require(payload.get("distribution") == "github-clone-alpha", "GitHub clone must remain distribution path")
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("base_branch") == "main", "base branch mismatch")
    require(
        git.get("publication_branch")
        in {
            "release/v0.4.8-alpha-profile-trust-store-integration",
            "release/v0.4.8-alpha-final-publication",
        },
        "publication branch mismatch",
    )
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(
        git.get("tag_status")
        in {"not_created_by_codex", "pending_codex_publication_after_verifier"},
        "unexpected tag status",
    )
    prs = payload.get("required_prs") if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    for number in (102, 103, 105, 106, 107):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    private_numbers = [item.get("number") for item in prs.get("private_registry", []) if isinstance(item, dict)]
    for number in (50, 51):
        require(number in private_numbers, f"manifest missing private registry PR #{number}")
    boundary = payload.get("safety_boundary") if isinstance(payload.get("safety_boundary"), dict) else {}
    for key in (
        "alpha_only",
        "fixture_mode",
        "profile_trust_store_integration",
        "local_offline_trust_store",
        "public_keys_only",
        "raw_local_profiles_still_allowed_by_default",
    ):
        require(boundary.get(key) is True, f"safety boundary must set {key}")
    require(
        boundary.get("codex_must_not_push_tag") is True or boundary.get("codex_pushes_tag") is True,
        "manifest must declare the Codex tag policy",
    )
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
        "v0.4.8-alpha",
        "managed mcp profile trust store",
        "local trust store",
        "offline",
        "public keys only",
        "trust status",
        "trust list",
        "trust import",
        "trust revoke",
        "trust doctor",
        "revoked key",
        "expired key",
        "wrong scope",
        "wrong audience",
        "corrupt trust store",
        "missing trust store",
        "audit provenance",
        "no hosted trust fetch",
        "no registry sync",
        "no production signing keys",
        "no private key storage",
        "no oauth",
        "no resources",
        "no prompts",
        "codex must not create or push",
    ):
        require(required in text, f"docs missing required wording: {required}")


def assert_smoke(report: dict[str, Any]) -> None:
    require(report.get("status") == "passed", "smoke status mismatch")
    require(report.get("release") == RELEASE, "smoke release mismatch")
    for key in (
        "production_hosted_calls",
        "hosted_trust_fetch",
        "registry_sync",
        "oauth",
        "remote_upstreams",
        "mcp_resources",
        "mcp_prompts",
        "production_signing_keys",
        "private_key_storage",
    ):
        require(report.get(key) is False, f"smoke must disable {key}")
    proofs = report.get("proofs") if isinstance(report.get("proofs"), dict) else {}
    for key in (
        "trust_status",
        "trust_list",
        "trust_import",
        "trust_revoke",
        "trust_doctor",
        "valid_trusted_key",
        "revoked_key_refusal",
        "missing_trust_store_refusal",
        "explicit_trusted_keys_override_refusal",
        "unreadable_crl_refusal",
        "active_after_crl_created",
        "private_key_import_refusal",
        "audit_provenance",
    ):
        proof = proofs.get(key)
        require(isinstance(proof, dict) and proof.get("status") == "passed", f"smoke proof missing: {key}")
    require(proofs["trust_doctor"]["corrupt_exit_code"] == 1, "corrupt trust store must fail doctor")
    for key in ("no_registry_sync", "no_hosted_trust_fetch", "no_production_signing_keys"):
        require(proofs.get(key) is True, f"smoke boolean proof missing: {key}")


def assert_no_private_material() -> None:
    offenders: list[str] = []
    allowed_private_marker_docs = {
        ROOT / "docs" / "mcp-trust-store.md",
        ROOT / "docs" / "mcp-signed-profile-bundles.md",
    }
    for path in PUBLIC_DOCS:
        if not path.exists():
            continue
        text = read(path)
        for name, pattern in PRIVATE_MATERIAL_PATTERNS.items():
            if name in {"pem_private_key", "openssh_private_key"} and path in allowed_private_marker_docs:
                continue
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    require(not offenders, "possible private material in public docs: " + ", ".join(offenders))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify v0.4.8-alpha MCP profile trust-store integration gate.")
    parser.add_argument("--expected-sha", help="Expected checkout SHA for the integration gate")
    parser.add_argument("--json", action="store_true", help="Print JSON evidence")
    args = parser.parse_args(argv)

    current_head = run_git(["rev-parse", "HEAD"])
    if args.expected_sha:
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(current_head == args.expected_sha, f"current checkout {current_head} does not match {args.expected_sha}")
    require(package_version() == VERSION, f"pyproject version must be {VERSION}")
    require(init_version() == VERSION, f"__version__ must be {VERSION}")
    require(plugin_versions() == (VERSION, VERSION), "Claude plugin and marketplace versions must match package version")
    manifest = assert_manifest()
    assert_docs()
    smoke = load_smoke().collect_evidence()
    assert_smoke(smoke)
    assert_no_private_material()
    report = {
        "status": "passed",
        "release": RELEASE,
        "current_checkout_sha": current_head,
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "required_prs": manifest.get("required_prs", {}),
        "smoke": smoke,
        "production_hosted_calls": False,
        "hosted_trust_fetch": False,
        "registry_sync": False,
        "codex_pushes_tag": False,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} MCP profile trust-store integration verification passed")
        print(f"manifest: {MANIFEST.relative_to(ROOT)}")
        print(f"current checkout sha: {current_head}")
        print("trust-store smoke: passed")
        print("hosted trust fetch: false")
        print("registry sync: false")
        git = manifest.get("git") if isinstance(manifest.get("git"), dict) else {}
        print(f"tag status: {git.get('tag_status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
