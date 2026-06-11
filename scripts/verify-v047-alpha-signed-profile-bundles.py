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
RELEASE = "v0.4.7-alpha"
VERSION = "0.4.7"
MANIFEST = ROOT / "docs" / "releases" / "v0.4.7-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.4.7-alpha.md",
    ROOT / "docs" / "releases" / "v0.4.7-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.4.7-alpha-known-issues.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "SECURITY.md",
    ROOT / "docs" / "mcp-signed-profile-bundles.md",
    ROOT / "docs" / "mcp-permissioned-tool-profiles.md",
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
    raise SystemExit(f"{RELEASE} signed profile bundles verification failed: {message}")


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
    path = ROOT / "scripts" / "run-v047-alpha-signed-profile-bundles-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v047_alpha_signed_profile_bundles_smoke", path)
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
            "release/v0.4.7-alpha-signed-profile-bundles-integration",
            "release/v0.4.7-alpha-final-publication",
        },
        "publication branch mismatch",
    )
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    require(
        git.get("tag_status")
        in {
            "not_created_by_codex",
            "pending_codex_publication_after_verifier",
        },
        "manifest tag status mismatch",
    )
    prs = payload.get("required_prs") if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    for number in (102, 103):
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
    ):
        require(boundary.get(key) is True, f"safety boundary must set {key}")
    require(
        boundary.get("codex_must_not_push_tag") is True or boundary.get("codex_pushes_tag") is True,
        "safety boundary must document Codex tag policy",
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
        "v0.4.7-alpha",
        "signed mcp profile bundle",
        "alpha",
        "may break before v0.6",
        "local mit core may still allow unsigned profiles",
        "registered/business signed-required behavior is future-gated",
        "no oauth",
        "no resources",
        "no prompts",
        "no production signing keys",
        "no hosted trust fetch",
        "no registry sync",
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
        "raw_local_profile_path",
        "valid_signed_bundle",
        "bad_signature_refusal",
        "unknown_key_refusal",
        "expired_bundle_refusal",
        "revoked_bundle_refusal",
        "wrong_audience_refusal",
        "namespace_violation_refusal",
        "audit_provenance",
    ):
        proof = proofs.get(key)
        require(isinstance(proof, dict) and proof.get("status") == "passed", f"smoke proof missing: {key}")
    for key in ("no_registry_sync", "no_hosted_trust_fetch", "no_production_signing_keys"):
        require(proofs.get(key) is True, f"smoke boolean proof missing: {key}")


def assert_no_private_material() -> None:
    offenders: list[str] = []
    for path in PUBLIC_DOCS:
        if not path.exists():
            continue
        text = read(path)
        for name, pattern in PRIVATE_MATERIAL_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    require(not offenders, "possible private material in public docs: " + ", ".join(offenders))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify v0.4.7-alpha signed profile bundles integration gate.")
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
        "codex_pushes_tag": manifest.get("git", {}).get("tag_status")
        == "pending_codex_publication_after_verifier",
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} signed profile bundles integration verification passed")
        print(f"manifest: {MANIFEST.relative_to(ROOT)}")
        print(f"current checkout sha: {current_head}")
        print("fixture signed bundle smoke: passed")
        print("hosted trust fetch: false")
        print("registry sync: false")
        if report["codex_pushes_tag"]:
            print("tag status: final publication may tag after publication verifier")
        else:
            print("tag status: Codex must not create or push v0.4.7-alpha")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
