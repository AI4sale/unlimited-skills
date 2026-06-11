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
RELEASE = "v0.4.4-alpha"
VERSION = "0.4.4"
MANIFEST = ROOT / "docs" / "releases" / "v0.4.4-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.4.4-alpha.md",
    ROOT / "docs" / "releases" / "v0.4.4-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.4.4-alpha-known-issues.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
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
    "local_windows_user_path": r"[A-Za-z]:\\Users\\tedja\\",
    "local_repo_path": r"D:\\git\\",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} MCP tool-profile verification failed: {message}")


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
    path = ROOT / "scripts" / "run-v044-alpha-mcp-tool-profiles-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v044_alpha_mcp_tool_profiles_smoke", path)
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
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("publication_branch") == "release/v0.4.4-alpha-mcp-tool-profile-integration", "publication branch mismatch")
    require(git.get("tag_status") == "not_created_by_codex", "Codex must not create v0.4.4-alpha tag")
    prs = payload.get("required_prs") if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    for number in (91, 92, 93, 94):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    boundary = payload.get("safety_boundary") if isinstance(payload.get("safety_boundary"), dict) else {}
    for key in ("alpha_only", "fixture_mode", "profile_runtime_enforcement", "mcp_tool_profile_integration"):
        require(boundary.get(key) is True, f"safety boundary must set {key}")
    for key in (
        "production_rollout",
        "production_hosted_calls",
        "hosted_gateway",
        "automatic_telemetry",
        "oauth_upstreams",
        "remote_upstreams",
        "mcp_resources",
        "mcp_prompts",
        "arbitrary_shell_execution",
        "auto_publish",
        "live_billing",
        "pypi",
        "full_catalog_distribution",
        "codex_pushes_tag",
    ):
        require(boundary.get(key) is False, f"safety boundary must disable {key}")
    return payload


def assert_docs() -> None:
    for path in RELEASE_DOCS:
        require(path.is_file(), f"missing release doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in PUBLIC_DOCS if path.exists()).lower()
    for phrase in (
        "v0.4.4-alpha",
        "permissioned mcp tool profile",
        "default-deny",
        "visible",
        "callable",
        "tool_not_visible",
        "tool_not_callable",
        "profile_not_found",
        "profile_invalid",
        "profile_loaded",
        "sha-256",
        "no oauth",
        "no remote upstream",
        "no resources",
        "no prompts",
        "no hosted gateway",
        "no production hosted calls",
        "no automatic telemetry",
    ):
        require(phrase in text, f"docs missing required wording: {phrase}")


def assert_smoke(report: dict[str, Any]) -> None:
    require(report.get("status") == "passed", "smoke status mismatch")
    require(report.get("release") == RELEASE, "smoke release mismatch")
    for key in ("production_hosted_calls", "hosted_gateway", "oauth", "remote_upstreams", "mcp_resources", "mcp_prompts", "arbitrary_shell_execution", "automatic_telemetry"):
        require(report.get(key) is False, f"smoke must disable {key}")
    proofs = report.get("proofs") if isinstance(report.get("proofs"), dict) else {}
    require(proofs.get("default_deny", {}).get("code") == -32011, "default-deny proof missing")
    require(proofs.get("selected_profile_by_cli") is True, "CLI profile selection proof missing")
    require(proofs.get("selected_profile_by_env") is True, "env profile selection proof missing")
    require(proofs.get("visible_only_search", {}).get("hidden_hits") == [], "visible-only search proof missing")
    require(proofs.get("hidden_schema_refusal", {}).get("code") == -32011, "hidden schema refusal proof missing")
    require(proofs.get("non_callable_call_refusal", {}).get("code") == -32012, "non-callable refusal proof missing")
    require(proofs.get("inheritance_narrowing", {}).get("code") == -32011, "inheritance narrowing proof missing")
    require(proofs.get("fail_closed", {}).get("missing_code") == -32013, "missing profile fail-closed proof missing")
    require(proofs.get("fail_closed", {}).get("invalid_code") == -32014, "invalid profile fail-closed proof missing")
    audit = proofs.get("profile_audit", {})
    require(audit.get("profile_loaded_row") is True, "profile_loaded audit proof missing")
    require(audit.get("profile_sha256") == audit.get("profile_sha256_expected"), "profile SHA proof missing")
    require(proofs.get("no_resources_or_prompts") is True, "resources/prompts proof missing")


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
    parser = argparse.ArgumentParser(description="Verify v0.4.4-alpha MCP tool-profile integration gate.")
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
    smoke = load_smoke().collect_evidence(run_pytest=False)
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
        "codex_pushes_tag": False,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} MCP tool-profile integration verification passed")
        print(f"manifest: {MANIFEST.relative_to(ROOT)}")
        print(f"current checkout sha: {current_head}")
        print("default-deny / visible-only / non-callable / fail-closed proofs: passed")
        print("profile audit row and SHA proof: passed")
        print("no OAuth/resources/prompts/hosted gateway: passed")
        print("private material scan: passed")
        print("tag status: Codex must not create or push v0.4.4-alpha")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
