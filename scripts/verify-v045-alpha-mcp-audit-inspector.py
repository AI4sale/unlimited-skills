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
RELEASE = "v0.4.5-alpha"
VERSION = "0.4.5"
MANIFEST = ROOT / "docs" / "releases" / "v0.4.5-alpha.release-manifest.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.4.5-alpha.md",
    ROOT / "docs" / "releases" / "v0.4.5-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.4.5-alpha-known-issues.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "mcp-audit-inspector.md",
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
    raise SystemExit(f"{RELEASE} MCP audit inspector verification failed: {message}")


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
    path = ROOT / "scripts" / "run-v045-alpha-mcp-audit-inspector-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v045_alpha_mcp_audit_inspector_smoke", path)
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
    publication_branch = git.get("publication_branch")
    require(
        publication_branch
        in {
            "release/v0.4.5-alpha-mcp-audit-inspector-integration",
            "release/v0.4.5-alpha-final-publication",
        },
        "publication branch mismatch",
    )
    require(git.get("tag") == RELEASE, "manifest tag mismatch")
    expected_tag_status = (
        "pending_codex_publication_after_verifier"
        if publication_branch == "release/v0.4.5-alpha-final-publication"
        else "not_created_by_codex"
    )
    require(git.get("tag_status") == expected_tag_status, "v0.4.5-alpha tag status mismatch")
    prs = payload.get("required_prs") if isinstance(payload.get("required_prs"), dict) else {}
    public_numbers = [item.get("number") for item in prs.get("public", []) if isinstance(item, dict)]
    for number in (95, 97):
        require(number in public_numbers, f"manifest missing public PR #{number}")
    boundary = payload.get("safety_boundary") if isinstance(payload.get("safety_boundary"), dict) else {}
    for key in (
        "alpha_only",
        "fixture_mode",
        "mcp_audit_inspector_integration",
        "read_only_audit_inspection",
        "redaction_self_check",
        "schema_locked_report",
        "profile_runtime_enforcement",
    ):
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
        "audit_log_writes",
        "auto_publish",
        "live_billing",
        "pypi",
        "full_catalog_distribution",
    ):
        require(boundary.get(key) is False, f"safety boundary must disable {key}")
    expected_codex_pushes_tag = publication_branch == "release/v0.4.5-alpha-final-publication"
    require(boundary.get("codex_pushes_tag") is expected_codex_pushes_tag, "Codex tag publication policy mismatch")
    return payload


def assert_docs() -> None:
    for path in RELEASE_DOCS:
        require(path.is_file(), f"missing release doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in PUBLIC_DOCS if path.exists()).lower()
    for required in (
        "v0.4.5-alpha",
        "mcp audit inspector",
        "read-only",
        "audit-report",
        "json schema",
        "recent refusals",
        "redaction self-check",
        "rotated",
        "profile_loaded",
        "no argument values",
        "no error text",
        "no production hosted calls",
        "no hosted gateway",
        "no oauth",
        "no resources",
        "no prompts",
        "no automatic telemetry",
        "no full catalog distribution",
    ):
        require(required in text, f"docs missing required wording: {required}")


def assert_smoke(report: dict[str, Any]) -> None:
    require(report.get("status") == "passed", "smoke status mismatch")
    require(report.get("release") == RELEASE, "smoke release mismatch")
    for key in (
        "production_hosted_calls",
        "hosted_gateway",
        "oauth",
        "remote_upstreams",
        "mcp_resources",
        "mcp_prompts",
        "arbitrary_shell_execution",
        "automatic_telemetry",
        "audit_log_writes",
    ):
        require(report.get(key) is False, f"smoke must disable {key}")
    proofs = report.get("proofs") if isinstance(report.get("proofs"), dict) else {}
    require(proofs.get("json_schema_valid") is True, "JSON schema validation proof missing")
    recent = proofs.get("recent_refusals_safe", {})
    require(recent.get("newest_first") is True, "recent refusals ordering proof missing")
    require(recent.get("payload_absent") is True, "recent refusals payload redaction proof missing")
    require(recent.get("error_text_absent") is True, "recent refusals error-text proof missing")
    require(proofs.get("profiles", {}).get("present") is True, "profile section proof missing")
    require(proofs.get("redaction_clean_pass", {}).get("status") == "PASS", "clean redaction proof missing")
    require(proofs.get("redaction_clean_pass", {}).get("secret_absent") is True, "clean redaction secret absence proof missing")
    require(proofs.get("redaction_injected_fail_safe", {}).get("status") == "FAIL", "injected redaction failure proof missing")
    require(proofs.get("redaction_injected_fail_safe", {}).get("secret_values_absent") is True, "redaction suspect values leaked")
    require(proofs.get("rotated_logs", {}).get("oldest_first") is True, "rotated log ordering proof missing")
    require(proofs.get("missing_log", {}).get("code") == 1, "missing log exit proof missing")
    require(proofs.get("missing_log", {}).get("no_traceback") is True, "missing log traceback proof missing")
    require(proofs.get("read_only", {}).get("digest_unchanged") is True, "read-only digest proof missing")
    require(proofs.get("read_only", {}).get("mtime_unchanged") is True, "read-only mtime proof missing")


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
    parser = argparse.ArgumentParser(description="Verify v0.4.5-alpha MCP audit inspector integration gate.")
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
        "codex_pushes_tag": manifest.get("safety_boundary", {}).get("codex_pushes_tag"),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} MCP audit inspector integration verification passed")
        print(f"manifest: {MANIFEST.relative_to(ROOT)}")
        print(f"current checkout sha: {current_head}")
        print("read-only audit inspection: passed")
        print("recent refusals omit argument values and error text: passed")
        print("redaction self-check: passed")
        print("JSON schema/report contract: passed")
        print("no OAuth/resources/prompts/hosted gateway: passed")
        print("private material scan: passed")
        if report["codex_pushes_tag"] is True:
            print("tag status: pending Codex publication after final verifier")
        else:
            print("tag status: Codex must not create or push v0.4.5-alpha")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
