"""Verify the adoption marketplace/listing launch pack.

This verifier is intentionally text-level: A3.2 is a launch-prep docs task,
not a marketplace submission. It checks that the paste-ready listing copy and
the operator launch pack stay aligned with the v0.5 public-alpha boundaries.
"""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LISTING_COPY = ROOT / "docs" / "adoption" / "marketplace-listing-copy.md"
LAUNCH_PACK = ROOT / "docs" / "adoption" / "marketplace-listing-launch-pack.md"
APPROVAL_PACKET = ROOT / "docs" / "adoption" / "submission-owner-approval-packet.md"
SUBMISSION_TRACKER = ROOT / "docs" / "adoption" / "marketplace-submission-tracker.md"
SUBMISSION_RUNBOOK = ROOT / "docs" / "adoption" / "marketplace-submission-runbook.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def verify() -> list[str]:
    errors: list[str] = []
    listing = read(LISTING_COPY)
    launch_pack = read(LAUNCH_PACK)
    approval_packet = read(APPROVAL_PACKET)
    submission_tracker = read(SUBMISSION_TRACKER)
    submission_runbook = read(SUBMISSION_RUNBOOK)
    combined = f"{listing}\n{launch_pack}\n{approval_packet}\n{submission_tracker}\n{submission_runbook}"
    listing_words = re.sub(r"\s+", " ", listing.lower().replace(">", " "))

    for command in (
        "pip install unlimited-skills",
        "unlimited-skills quickstart",
        "unlimited-skills mcp install --claude-code --dry-run",
        "unlimited-skills mcp install --claude-code",
        "unlimited-skills mcp install status",
        "unlimited-skills mcp savings",
        "/plugin marketplace add AI4sale/unlimited-skills",
        "/plugin install unlimited-skills@unlimited-skills",
    ):
        require(command in combined, f"missing launch command: {command}", errors)

    for source_url in (
        "https://code.claude.com/docs/en/plugins",
        "https://code.claude.com/docs/en/plugin-marketplaces",
        "https://modelcontextprotocol.io/registry/about",
        "https://registry.modelcontextprotocol.io/",
    ):
        require(source_url in launch_pack, f"missing source check URL: {source_url}", errors)

    listing_lower = listing.lower()
    for required in (
        "free public alpha",
        "no telemetry",
        "nothing in this plugin or its cli is for sale",
        "github issues",
        "docs/releases/v0.5.0-alpha-known-issues.md",
    ):
        require(required in listing_words, f"listing copy missing boundary wording: {required}", errors)

    forbidden_listing_claims = (
        "paid tier",
        "paid plan",
        "checkout",
        "buy now",
        "purchase",
        "hosted team",
        "hosted/team features are available",
        "enterprise-ready",
        "production hosted gateway",
        "automatic telemetry",
    )
    for claim in forbidden_listing_claims:
        if claim in ("paid tier", "checkout", "purchase"):
            # The "Nothing for sale" section may negate these words; require
            # the known negation if the word appears.
            continue
        require(claim not in listing_lower, f"listing copy contains blocked claim: {claim}", errors)

    require(
        "there are no paid tiers on offer, no checkout, and no purchase path" in listing_words,
        "listing copy must explicitly negate paid tiers, checkout, and purchase path",
        errors,
    )
    require(
        "must not imply a hosted mcp service" in launch_pack.lower(),
        "launch pack must preserve local gateway wording for MCP discovery",
        errors,
    )

    combined_lower = combined.lower()
    for required in (
        "submission-owner-approval-packet.md",
        "blocked_pending_owner_approval",
        "current_rule_check_date",
        "exact_listing_copy_reference",
        "submitter: owner | codex | human_delegate",
        "permission_to_submit: no",
        "permission_to_submit: yes",
        "evidence_required_after_submission",
        "blocked_claims_acknowledged",
        "fallback_if_rejected",
        "does not submit anywhere",
        "no hosted/team/enterprise readiness claim",
        "no guaranteed marketplace acceptance claim",
    ):
        require(required in combined_lower, f"approval packet missing guardrail: {required}", errors)
    return errors


def main() -> int:
    errors = verify()
    if errors:
        print("marketplace/listing launch pack verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("marketplace/listing launch pack verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
