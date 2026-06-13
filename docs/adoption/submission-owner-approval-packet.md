# Submission Owner Approval Packet

Status: `blocked_pending_owner_approval`.

Purpose: make A3.4 external submission evidence unblockable without letting an
agent, maintainer, or launch checklist submit Unlimited Skills to an external
marketplace, registry, directory, or discovery surface by accident.

This packet is an approval template only. It does not submit anywhere, does not
claim that any surface accepted Unlimited Skills, and does not authorize Codex
or another agent to act unless `permission_to_submit` is explicitly `yes` for a
specific destination.

## Required Packet Fields

Every destination must have a completed owner approval packet before any
external submission is sent:

| Field | Required value |
| --- | --- |
| `destination` | Exact marketplace, registry, directory, or discovery surface. |
| `current_rule_check_date` | Date when the current destination rules were checked. Must be refreshed on the submission day. |
| `submission_owner` | Person or role accountable for the submission and follow-up. |
| `exact_listing_copy_reference` | Exact repo file, section, commit, or external draft used as listing copy. |
| `submitter` | One of `owner`, `Codex`, or `human_delegate`. |
| `permission_to_submit` | One of `yes` or `no`. `no` is the default until the owner changes it. |
| `evidence_required_after_submission` | Evidence that must be captured after sending, such as submission URL, issue, screenshot reference, rejection summary, or accepted listing URL. |
| `blocked_claims_acknowledged` | Explicit acknowledgment that blocked claims will not be used. |
| `fallback_if_rejected` | Concrete fallback if the destination rejects, blocks, or ignores the listing. |

## Blocked Claims Acknowledgment

The owner approval packet must acknowledge that the submission copy contains:

- no paid CTA;
- no payment link;
- no checkout path;
- no hosted readiness claim;
- no team readiness claim;
- no enterprise readiness claim;
- no delivery promise;
- no guaranteed marketplace acceptance claim;
- no telemetry, tracking pixel, analytics SDK, automatic upload, private social
  scraping, prompt collection, tool input collection, or tool output collection
  claim drift.

If a destination requires one of these claims, mark the packet and tracker row
as blocked. Do not submit.

## Packet Template

Copy this block into the tracker note, an owner issue, or a private operator
handoff before any submission:

```yaml
destination:
current_rule_check_date:
submission_owner:
exact_listing_copy_reference:
submitter: owner | Codex | human_delegate
permission_to_submit: no
evidence_required_after_submission:
blocked_claims_acknowledged:
fallback_if_rejected:
```

## Current Packets

All current packets are intentionally blocked until the owner fills the fields
and changes `permission_to_submit` to `yes`.

### Claude Code Plugin Marketplace

```yaml
destination: Claude Code plugin marketplace
current_rule_check_date: refresh on submission day
submission_owner: release owner
exact_listing_copy_reference: docs/adoption/marketplace-listing-copy.md at the selected release commit
submitter: owner | Codex | human_delegate
permission_to_submit: no
evidence_required_after_submission: submission URL or owner-owned screenshot reference; accepted listing URL if published; rejection reason if rejected
blocked_claims_acknowledged: no paid CTA, no payment link, no hosted/team/enterprise readiness claim, no delivery promise, no guaranteed acceptance claim, no telemetry/upload claim drift
fallback_if_rejected: keep tracker row not_submitted or rejected with evidence; route feedback to listing-copy backlog; do not claim acceptance
```

### MCP Registry / Discovery

```yaml
destination: MCP Registry / discovery surface
current_rule_check_date: refresh on submission day
submission_owner: release owner
exact_listing_copy_reference: docs/adoption/marketplace-listing-copy.md at the selected release commit
submitter: owner | Codex | human_delegate
permission_to_submit: no
evidence_required_after_submission: registry submission URL or issue; accepted listing URL if published; rejection/blocker reason if local CLI gateway packages are not accepted
blocked_claims_acknowledged: no hosted MCP server claim, no hosted/team/enterprise readiness claim, no paid CTA, no payment link, no delivery promise, no guaranteed acceptance claim
fallback_if_rejected: mark tracker row blocked or rejected with reason; keep Unlimited Skills described as a local CLI gateway; do not claim registry acceptance
```

### GitHub Repository Discovery

```yaml
destination: GitHub repository discovery
current_rule_check_date: refresh on action day
submission_owner: release owner
exact_listing_copy_reference: README.md, docs/adoption/marketplace-listing-copy.md, and the selected release notes at the selected release commit
submitter: owner | Codex | human_delegate
permission_to_submit: no
evidence_required_after_submission: repository topic/settings diff, PR, issue, or release link; no external acceptance claim unless a specific GitHub surface accepts the listing
blocked_claims_acknowledged: no paid CTA, no payment link, no hosted/team/enterprise readiness claim, no delivery promise, no guaranteed discovery outcome
fallback_if_rejected: keep tracker row not_submitted or blocked; use ordinary README/topic hygiene only
```

## Submission Rule

A submission may proceed only when all of these are true:

1. The destination row exists in
   [marketplace-submission-tracker.md](marketplace-submission-tracker.md).
2. The owner approval packet for that exact destination is complete.
3. `current_rule_check_date` is the current submission day.
4. `exact_listing_copy_reference` points to the exact copy being submitted.
5. `submitter` is explicit.
6. `permission_to_submit` is `yes`.
7. The blocked claims acknowledgment is complete.
8. Evidence requirements and fallback are explicit.

If any item is missing, A3.4 remains `blocked_pending_owner_approval`.

## Related Docs

- [Marketplace submission tracker](marketplace-submission-tracker.md)
- [Marketplace submission runbook](marketplace-submission-runbook.md)
- [Marketplace listing copy](marketplace-listing-copy.md)
- [Marketplace/listing launch pack](marketplace-listing-launch-pack.md)
