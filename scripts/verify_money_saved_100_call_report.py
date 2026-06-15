from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unlimited_skills.money_saved_meter import (
    build_100_call_value_report_from_sources,
    format_money_saved_meter_markdown,
)
try:
    from scripts.verify_money_saved_meter_100_call_fixture import verify_fixture_report
except ModuleNotFoundError:
    from verify_money_saved_meter_100_call_fixture import verify_fixture_report

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "money_saved_meter"
DEFAULT_MCP_SAVINGS = FIXTURE_DIR / "100-call-mcp-savings.json"
DEFAULT_AUDIT_LOG = FIXTURE_DIR / "100-call-gateway-audit.jsonl"
DEFAULT_EXPECTED_JSON = FIXTURE_DIR / "100-call-value-report.json"
DEFAULT_MARKDOWN_EXCERPT = FIXTURE_DIR / "100-call-markdown-excerpt.md"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return payload


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def verify_reproducible_report(
    *,
    mcp_savings_path: Path = DEFAULT_MCP_SAVINGS,
    audit_log_path: Path = DEFAULT_AUDIT_LOG,
    expected_json_path: Path = DEFAULT_EXPECTED_JSON,
    markdown_excerpt_path: Path = DEFAULT_MARKDOWN_EXCERPT,
) -> dict[str, Any]:
    source_payload = _load_json(mcp_savings_path)
    expected = _load_json(expected_json_path)
    generated = build_100_call_value_report_from_sources(
        mcp_savings_report=source_payload,
        audit_log=audit_log_path,
    )
    verification = verify_fixture_report(generated)

    if _stable_json(generated) != _stable_json(expected):
        raise SystemExit("100-call generated report differs from expected fixture JSON")

    markdown = format_money_saved_meter_markdown(generated)
    excerpt = markdown_excerpt_path.read_text(encoding="utf-8")
    if excerpt not in markdown:
        raise SystemExit("100-call Markdown excerpt is not present in generated Markdown")

    serialized = _stable_json(generated)
    forbidden_needles = [
        "redacted-fixture-upstream",
        "exact tokens saved.",
        "exact money saved.",
        "bill reduction guaranteed.",
        "hosted telemetry-backed savings.",
        "provider billing reconciliation.",
    ]
    for needle in forbidden_needles:
        if needle in serialized or needle in markdown:
            raise SystemExit(f"forbidden needle present in generated report: {needle}")

    return {
        **verification,
        "source_mcp_savings": str(mcp_savings_path.relative_to(ROOT)),
        "source_audit_log": str(audit_log_path.relative_to(ROOT)),
        "expected_json": str(expected_json_path.relative_to(ROOT)),
        "markdown_excerpt": str(markdown_excerpt_path.relative_to(ROOT)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Money Saved Meter 100-call report from source fixtures.")
    parser.add_argument("--mcp-savings", default=str(DEFAULT_MCP_SAVINGS), help="MCP savings source fixture JSON.")
    parser.add_argument("--audit-log", default=str(DEFAULT_AUDIT_LOG), help="Gateway audit source fixture JSONL.")
    parser.add_argument("--expected-json", default=str(DEFAULT_EXPECTED_JSON), help="Expected 100-call output JSON fixture.")
    parser.add_argument("--markdown-excerpt", default=str(DEFAULT_MARKDOWN_EXCERPT), help="Expected Markdown excerpt fixture.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable verification result.")
    args = parser.parse_args()

    result = verify_reproducible_report(
        mcp_savings_path=Path(args.mcp_savings),
        audit_log_path=Path(args.audit_log),
        expected_json_path=Path(args.expected_json),
        markdown_excerpt_path=Path(args.markdown_excerpt),
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("money saved meter 100-call report verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
