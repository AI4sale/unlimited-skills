from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "releases" / "v0.6.4-alpha.release-manifest.json"
READINESS = ROOT / "docs" / "reports" / "v0.6.4-release-readiness-package.md"
CLAIM_BOUNDARY = ROOT / "docs" / "reports" / "v0.6.4-money-saved-meter-release-claim-boundary.md"
FINAL_LIMITATIONS = ROOT / "docs" / "reports" / "v0.6.4-known-limitations-final.md"

REQUIRED_ITEMS = ["US-064-000", "US-064-001", "US-064-002", "US-064-003", "US-064-004"]
REQUIRED_PRS = [183, 184, 186, 187, 188, 189, 190, 191, 192, 193]
REQUIRED_COMMANDS = [
    "python scripts/generate-router-inventory.py --check",
    "python scripts/verify-router-inject-v2-fixture.py --json",
    "python scripts/verify-money-saved-100-call-report.py --json",
    "python scripts/verify-money-saved-meter-100-call-fixture.py --json",
    "python scripts/verify-money-saved-reproduction-docs.py --json",
    "python scripts/verify-v06-frozen-contracts.py --json",
    "python scripts/verify-feedback-report-boundaries.py",
    "git diff --check",
]
BOUNDARY_PHRASES = [
    "GO_WITH_LIMITS",
    "local-only",
    "tokens and dollars are estimates",
    "dollars are disabled by default",
    "100-call frame is a local reporting cadence, not billing math",
]
FORBIDDEN_AFFIRMATIVE_CLAIMS = [
    "exact token savings",
    "exact money savings",
    "guaranteed bill reduction",
    "provider billing reconciliation",
    "hosted telemetry-backed savings",
    "live hosted dashboard",
    "paid-tier exports",
    "team, business, or enterprise rollout",
]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _read(path: Path) -> str:
    _require(path.exists(), f"missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def _claim_only_in_blocked_context(text: str, claim: str) -> bool:
    lower = text.lower()
    index = lower.find(claim.lower())
    if index == -1:
        return True
    context = lower[max(0, index - 240) : index + len(claim) + 240]
    return any(marker in context for marker in ["blocked", "do not claim", "does not include", "not include"])


def verify_release_readiness() -> dict[str, Any]:
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"release manifest is invalid JSON: {exc}") from exc

    readiness = _read(READINESS)
    claim_boundary = _read(CLAIM_BOUNDARY)
    final_limitations = _read(FINAL_LIMITATIONS)
    combined = "\n".join([readiness, claim_boundary, final_limitations])

    _require(manifest.get("release") == "v0.6.4-alpha", "manifest release mismatch")
    _require(manifest.get("package_version") == "0.6.4", "manifest package version mismatch")
    _require(manifest.get("release_decision", {}).get("recommendation") == "GO_WITH_LIMITS", "missing GO_WITH_LIMITS decision")
    _require(manifest.get("release_decision", {}).get("release_publish_allowed") is False, "release_publish_allowed must be false")
    _require(manifest.get("release_decision", {}).get("release_execution_authorized") is False, "release execution must be false")
    _require(manifest.get("implemented_items") == REQUIRED_ITEMS, "implemented item list mismatch")

    tracked_prs = manifest.get("tracked_prs", [])
    _require([item.get("number") for item in tracked_prs] == REQUIRED_PRS, "tracked PR list mismatch")
    _require(
        next(item for item in tracked_prs if item.get("number") == 190).get("role") == "planning_support",
        "#190 must remain planning support",
    )
    _require(
        next(item for item in tracked_prs if item.get("number") == 193).get("role") == "review_support",
        "#193 must remain review support",
    )

    for doc in manifest.get("required_docs", []):
        _require((ROOT / doc).exists(), f"manifest required doc missing: {doc}")

    commands = manifest.get("verification_commands", [])
    for command in REQUIRED_COMMANDS:
        _require(command in commands, f"manifest missing verification command: {command}")
        _require(command in readiness, f"readiness checklist missing command: {command}")

    for phrase in BOUNDARY_PHRASES:
        _require(phrase.lower() in combined.lower(), f"missing release boundary phrase: {phrase}")

    for claim in FORBIDDEN_AFFIRMATIVE_CLAIMS:
        _require(
            _claim_only_in_blocked_context(combined, claim),
            f"forbidden claim appears outside blocked context: {claim}",
        )

    blocked = manifest.get("blocked_surfaces", {})
    for surface in [
        "push_nudge",
        "persistent_meter_state_writer",
        "paid_tier_exports",
        "hosted_telemetry",
        "billing_provider_reconciliation",
        "exact_token_money_claims",
        "team_business_enterprise_rollout",
        "marketplace_submission",
        "pypi_publish",
        "tag_creation",
    ]:
        _require(blocked.get(surface) is True, f"blocked surface must be true: {surface}")

    return {
        "schema_version": 1,
        "report_type": "v064_release_readiness_verification",
        "ok": True,
        "release": manifest["release"],
        "decision": manifest["release_decision"]["recommendation"],
        "implemented_items": manifest["implemented_items"],
        "tracked_prs": [item["number"] for item in tracked_prs],
        "verification_command_count": len(commands),
        "release_publish_allowed": manifest["release_decision"]["release_publish_allowed"],
        "release_execution_authorized": manifest["release_decision"]["release_execution_authorized"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify v0.6.4 Money Saved Meter release-readiness package.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable verification result.")
    args = parser.parse_args()

    result = verify_release_readiness()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("v0.6.4 release-readiness verification passed")
    return 0
