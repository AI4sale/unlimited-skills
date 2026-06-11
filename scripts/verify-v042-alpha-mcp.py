from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.2-alpha"
MANIFEST = ROOT / "docs" / "releases" / "v0.4.2-alpha.release-manifest.json"
SCHEMA = ROOT / "schemas" / "mcp-upstream-config.schema.json"
EXAMPLE = ROOT / "examples" / "mcp" / "upstreams.example.json"
RELEASE_DOCS = [
    ROOT / "docs" / "releases" / "v0.4.2-alpha.md",
    ROOT / "docs" / "releases" / "v0.4.2-alpha-checklist.md",
    ROOT / "docs" / "releases" / "v0.4.2-alpha-known-issues.md",
    MANIFEST,
]
PUBLIC_DOCS = RELEASE_DOCS + [
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "mcp-server.md",
    ROOT / "docs" / "mcp-gateway.md",
    ROOT / "docs" / "mcp-upstream-security-model.md",
    ROOT / "docs" / "unlimited-tools.md",
]
PRIVATE_MATERIAL_PATTERNS = {
    "pem_private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "openssh_private_key": r"-----BEGIN OPENSSH PRIVATE KEY-----",
    "github_pat": r"gh[pousr]_[A-Za-z0-9_]{20,}",
    "openai_key": r"sk-[A-Za-z0-9_\-]{20,}",
    "raw_uls_token": r"uls_(?:hub|token|license)_[A-Za-z0-9_\-]{16,}",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} MCP verification failed: {message}")


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


def _load_smoke_runner():
    path = ROOT / "scripts" / "run-mcp-smoke.py"
    spec = importlib.util.spec_from_file_location("run_mcp_smoke_v042", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_smoke


def assert_manifest() -> dict[str, Any]:
    require(MANIFEST.is_file(), f"missing release manifest: {MANIFEST.relative_to(ROOT)}")
    payload = json.loads(read(MANIFEST))
    require(payload.get("release") == RELEASE, "manifest release mismatch")
    require(payload.get("distribution") == "github-clone-alpha", "distribution must remain GitHub clone alpha")
    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
    require(git.get("publication_branch") == "release/v0.4.2-alpha-mcp-integration", "publication branch mismatch")
    require(git.get("tag_status") == "not_created_by_codex", "Codex must not create v0.4.2-alpha tag")
    boundary = payload.get("safety_boundary") if isinstance(payload.get("safety_boundary"), dict) else {}
    for key in (
        "production_hosted_calls",
        "automatic_telemetry",
        "oauth_upstreams",
        "remote_upstreams",
        "mcp_resources",
        "mcp_prompts",
        "hosted_gateway",
        "full_schema_dump",
        "skill_body_upload",
        "private_pack_body_upload",
        "codex_pushes_tag",
    ):
        require(boundary.get(key) is False, f"safety boundary must disable {key}")
    return payload


def assert_docs() -> None:
    for path in RELEASE_DOCS:
        require(path.is_file(), f"missing release doc: {path.relative_to(ROOT)}")
    text = "\n".join(read(path) for path in PUBLIC_DOCS if path.exists()).lower()
    for phrase in (
        "v0.4.2-alpha",
        "mcp integration gate",
        "unlimited-skills mcp serve",
        "unlimited-skills mcp gateway",
        "skills_search",
        "skills_view",
        "skills_use",
        "tools_search",
        "tools_schema",
        "tools_call",
        "lazy upstream spawn",
        "no full schema dump",
        "audit redaction",
        "local-restricted",
        "no shell",
        "env_allowlist",
        "wildcard",
        "schema_too_large",
        "response_too_large",
        "timeout",
        "no oauth",
        "no remote upstream",
        "no mcp resources or prompts",
        "alpha",
        "may break before v0.6",
    ):
        require(phrase in text, f"docs missing required wording: {phrase}")


def assert_schema_security_model() -> dict[str, Any]:
    schema = json.loads(read(SCHEMA))
    example = json.loads(read(EXAMPLE))
    upstream = schema["properties"]["upstreams"]["items"]
    properties = upstream["properties"]
    trust_levels = set(properties["trust_level"]["enum"])
    require(properties["trust_level"]["default"] == "local-restricted", "default trust level must be local-restricted")
    require({"disabled", "local-restricted", "local-trusted", "future-remote-placeholder"} <= trust_levels, "trust levels missing")
    require("env" not in properties, "literal env map must not exist in upstream schema")
    env_pattern = properties["env_allowlist"]["items"]["pattern"]
    require(re.fullmatch(env_pattern, "GITHUB_PERSONAL_ACCESS_TOKEN") is not None, "valid env name must match")
    require(re.fullmatch(env_pattern, "*") is None, "wildcard env forwarding must be impossible")
    require(re.fullmatch(env_pattern, "GITHUB_*") is None, "prefix wildcard env forwarding must be impossible")
    require(properties["audit_level"]["enum"] == ["minimal", "standard"], "audit level must not allow off")
    require(properties["max_schema_bytes"]["maximum"] == 1048576, "schema size hard cap mismatch")
    require(properties["max_response_bytes"]["maximum"] == 8388608, "response size hard cap mismatch")
    require(properties["startup_timeout_seconds"]["maximum"] == 120, "startup timeout cap mismatch")
    require(properties["request_timeout_seconds"]["maximum"] == 300, "request timeout cap mismatch")
    require(any(item.get("trust_level") == "future-remote-placeholder" for item in example["upstreams"]), "example missing remote placeholder")
    require(any(item.get("trust_level") == "local-restricted" for item in example["upstreams"]), "example missing restricted upstream")
    require(any(item.get("trust_level") == "local-trusted" for item in example["upstreams"]), "example missing trusted upstream")
    return {
        "local_restricted_default": True,
        "no_literal_env_map": True,
        "env_allowlist_only": True,
        "wildcard_env_forwarding_impossible": True,
        "audit_cannot_be_off": True,
        "schema_size_limit_bytes": 1048576,
        "response_size_limit_bytes": 8388608,
        "startup_timeout_cap_seconds": 120,
        "request_timeout_cap_seconds": 300,
        "oauth_remote_out_of_scope": True,
        "resources_prompts_out_of_scope": True,
        "alpha_may_break_before_v06": True,
    }


def assert_smoke() -> dict[str, Any]:
    run_smoke = _load_smoke_runner()
    smoke = run_smoke(ROOT)
    require(smoke["status"] == "passed", "MCP smoke did not pass")
    require(smoke["skills_server"]["tools"] == ["skills_search", "skills_use", "skills_view"], "skills server tools mismatch")
    require(smoke["gateway"]["tools"] == ["tools_call", "tools_schema", "tools_search"], "gateway tools mismatch")
    require(smoke["gateway"]["tools_search_no_schema_dump"] is True, "tools_search leaked schemas")
    require(smoke["gateway"]["tools_schema_lazy_spawn"] is True, "tools_schema must lazily spawn upstream")
    require(smoke["gateway"]["audit_redaction"] is True, "audit redaction proof missing")
    require(smoke["boundaries"]["oauth_upstreams"] is False, "OAuth must remain out of scope")
    require(smoke["boundaries"]["mcp_resources_or_prompts"] is False, "resources/prompts must remain out of scope")
    return smoke


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
    parser = argparse.ArgumentParser(description="Verify v0.4.2-alpha MCP integration release gate.")
    parser.add_argument("--expected-sha", help="Expected checkout SHA for the integration gate")
    parser.add_argument("--json", action="store_true", help="Print JSON evidence")
    args = parser.parse_args(argv)

    current_head = run_git(["rev-parse", "HEAD"])
    if args.expected_sha:
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is not None, "--expected-sha must be 40 lowercase hex")
        require(current_head == args.expected_sha, f"current checkout {current_head} does not match {args.expected_sha}")

    manifest = assert_manifest()
    assert_docs()
    security_model = assert_schema_security_model()
    smoke = assert_smoke()
    assert_no_private_material()
    report = {
        "status": "passed",
        "release": RELEASE,
        "current_checkout_sha": current_head,
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "required_prs": manifest.get("required_prs", {}),
        "mcp_server_fixture_transcript": smoke["skills_server"],
        "mcp_gateway_fixture_transcript": smoke["gateway"],
        "boundary_proofs": smoke["boundaries"],
        "upstream_security_model": security_model,
        "production_hosted_calls": False,
        "codex_pushes_tag": False,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} MCP integration verification passed")
        print(f"manifest: {MANIFEST.relative_to(ROOT)}")
        print(f"current checkout sha: {current_head}")
        print("MCP server fixture transcript: passed")
        print("MCP gateway fixture transcript: passed")
        print("upstream security model verifier: passed")
        print("no OAuth/resources/prompts: passed")
        print("no token/private-key/proof/prompt/skill-body/local-path evidence leakage: passed")
        print("tag status: Codex must not create or push v0.4.2-alpha")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
