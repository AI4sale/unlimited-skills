from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

WALKTHROUGH = ROOT / "docs" / "product" / "v0.6.4" / "money-saved-meter-reproduce-measurements.md"
VALUE_MODEL = ROOT / "docs" / "product" / "v0.6.4" / "money-saved-meter-value-model.md"
JSON_CONTRACT = ROOT / "docs" / "product" / "v0.6.4" / "money-saved-meter-json-contract.v1.md"
BEFORE_AFTER = ROOT / "docs" / "product" / "v0.6.4" / "money-saved-meter-before-after-command.md"
CALL_REPORT = ROOT / "docs" / "product" / "v0.6.4" / "money-saved-meter-100-call-value-report.md"
LIMITATIONS = ROOT / "docs" / "reports" / "v0.6.4-money-saved-meter-known-limitations.md"
CLI_CONTRACTS = ROOT / "docs" / "cli-contracts.md"

REQUIRED_DOCS = [WALKTHROUGH, VALUE_MODEL, JSON_CONTRACT, BEFORE_AFTER, CALL_REPORT, LIMITATIONS, CLI_CONTRACTS]

REQUIRED_COMMANDS = [
    "unlimited-skills money-saved meter --json",
    "--mode before",
    "--mode after",
    "--compare",
    "--fixture-100-call",
    "python scripts/verify-money-saved-100-call-report.py --json",
    "python scripts/verify-money-saved-meter-100-call-fixture.py --json",
]

REQUIRED_BOUNDARY_PHRASES = [
    "cadence, not billing math",
    "dollars are disabled by default",
    "tokens are estimates",
    "local-only",
]

REQUIRED_LINKS = [
    "money-saved-meter-value-model.md",
    "money-saved-meter-json-contract.v1.md",
    "money-saved-meter-before-after-command.md",
    "money-saved-meter-100-call-value-report.md",
    "v0.6.4-money-saved-meter-known-limitations.md",
]

FORBIDDEN_CLAIMS = [
    "exact tokens saved",
    "exact money saved",
    "bill reduction guaranteed",
    "guaranteed bill reduction",
    "hosted telemetry-backed savings",
    "provider billing reconciliation",
]

ALLOWED_CONTEXTS = {
    "exact tokens saved": "Forbidden claims",
    "exact money saved": "Forbidden claims",
    "bill reduction guaranteed": "Forbidden claims",
    "hosted telemetry-backed savings": "Forbidden claims",
    "provider billing reconciliation": "Forbidden claims",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _read(path: Path) -> str:
    _require(path.exists(), f"required doc missing: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def _forbidden_claim_is_only_named_as_forbidden(text: str, claim: str) -> bool:
    lower = text.lower()
    index = lower.find(claim)
    if index == -1:
        return True
    section_start = lower.rfind("\n## ", 0, index)
    section = lower[section_start:index] if section_start != -1 else lower[:index]
    return "forbidden" in section[-300:] or "must not" in section[-300:] or "does not" in section[-300:]


def verify_reproduction_docs() -> dict[str, Any]:
    docs = {path: _read(path) for path in REQUIRED_DOCS}
    walkthrough = docs[WALKTHROUGH]
    lower = walkthrough.lower()

    for command in REQUIRED_COMMANDS:
        _require(command in walkthrough, f"walkthrough missing command: {command}")

    for phrase in REQUIRED_BOUNDARY_PHRASES:
        _require(phrase in lower, f"walkthrough missing boundary phrase: {phrase}")

    for link in REQUIRED_LINKS:
        _require(link in walkthrough, f"walkthrough missing link/reference: {link}")

    for claim in FORBIDDEN_CLAIMS:
        _require(
            _forbidden_claim_is_only_named_as_forbidden(walkthrough, claim),
            f"forbidden claim appears as an affirmative claim: {claim}",
        )

    cli_contracts = docs[CLI_CONTRACTS]
    limitations = docs[LIMITATIONS]
    call_report = docs[CALL_REPORT]

    for text, name in [
        (cli_contracts, "docs/cli-contracts.md"),
        (limitations, "known limitations"),
        (call_report, "100-call value report"),
    ]:
        _require(
            "money-saved-meter-reproduce-measurements.md" in text,
            f"{name} must link to reproduction walkthrough",
        )

    return {
        "schema_version": 1,
        "report_type": "money_saved_meter_reproduction_docs_verification",
        "ok": True,
        "checked_docs": [str(path.relative_to(ROOT)).replace("\\", "/") for path in REQUIRED_DOCS],
        "required_commands": REQUIRED_COMMANDS,
        "required_boundary_phrases": REQUIRED_BOUNDARY_PHRASES,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Money Saved Meter reproduction docs and claim boundaries.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable verification result.")
    args = parser.parse_args()

    result = verify_reproduction_docs()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("money saved meter reproduction docs verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
