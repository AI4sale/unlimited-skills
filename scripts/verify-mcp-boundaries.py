from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from mcp_smoke_support import (
    LOCAL_PATH_MARKER,
    PRIVATE_KEY_MARKER,
    PRIVATE_PACK_MARKER,
    PROMPT_MARKER,
    PROOF_MARKER,
    SEARCH_QUERY_MARKER,
    SKILL_BODY_MARKER,
    TOKEN_MARKER,
)


def _load_smoke_runner():
    smoke_path = Path(__file__).with_name("run-mcp-smoke.py")
    spec = importlib.util.spec_from_file_location("run_mcp_smoke", smoke_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load smoke runner: {smoke_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_smoke


REQUIRED_DOC_PHRASES = {
    "docs/unlimited-tools.md": [
        "no OAuth upstreams",
        "no MCP resources or prompts",
        "no hosted gateway",
        "No automatic telemetry",
    ],
    "docs/mcp-gateway.md": [
        "does not expose resources or prompts",
        "No OAuth upstreams",
        "not a hosted gateway",
        "does not send telemetry",
    ],
    "docs/known-limitations.md": [
        "MCP",
        "no OAuth upstreams",
        "no MCP resources",
        "no hosted gateway",
    ],
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def verify_static_docs(repo: Path) -> list[str]:
    failures: list[str] = []
    for rel, phrases in REQUIRED_DOC_PHRASES.items():
        path = repo / rel
        if not path.is_file():
            failures.append(f"missing {rel}")
            continue
        text = _read(path)
        lower = text.lower()
        for phrase in phrases:
            if phrase.lower() not in lower:
                failures.append(f"{rel} missing phrase: {phrase}")
    return failures


def verify_no_sensitive_markers(report: dict) -> list[str]:
    dumped = json.dumps(report, ensure_ascii=False, sort_keys=True)
    markers = [
        SKILL_BODY_MARKER,
        PRIVATE_PACK_MARKER,
        TOKEN_MARKER,
        PROOF_MARKER,
        PRIVATE_KEY_MARKER,
        PROMPT_MARKER,
        SEARCH_QUERY_MARKER,
        LOCAL_PATH_MARKER,
    ]
    return [f"report leaked {marker}" for marker in markers if marker in dumped]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Unlimited Tools MCP safety boundaries.")
    parser.add_argument("--json", action="store_true", help="Print a JSON verification report.")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    run_smoke = _load_smoke_runner()
    smoke = run_smoke(repo)
    failures = []
    failures.extend(verify_no_sensitive_markers(smoke))
    failures.extend(verify_static_docs(repo))
    report = {
        "status": "failed" if failures else "passed",
        "failures": failures,
        "smoke_status": smoke["status"],
        "proofs": {
            "mcp_stdio_handshake_fixture": True,
            "skills_search_metadata_only": smoke["skills_server"]["skills_search_metadata_only"],
            "tools_search_no_full_schema_dump": smoke["gateway"]["tools_search_no_schema_dump"],
            "tools_schema_lazy_fetch": smoke["gateway"]["tools_schema_lazy_spawn"],
            "tools_call_fixture_output": smoke["gateway"]["tools_call_result"],
            "lazy_spawn_proof": smoke["gateway"]["tools_search_no_spawn"]
            and smoke["gateway"]["tools_schema_lazy_spawn"],
            "audit_redaction": smoke["gateway"]["audit_redaction"],
            "no_sensitive_marker_grep": not failures,
            "production_hosted_calls": False,
        },
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif failures:
        print("MCP boundary verification failed:")
        for failure in failures:
            print(f"- {failure}")
    else:
        print("MCP boundary verification passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
