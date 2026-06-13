# Marketplace Submission Tracker

Purpose: track every public-alpha listing or discovery submission for
Unlimited Skills in one place.

This tracker is evidence, not marketing copy. Do not mark any surface as
submitted, accepted, rejected, or blocked unless there is a dated owner action
or evidence link. Re-check the current rules for each surface immediately
before sending anything.

## Status Vocabulary

- `not_submitted`: the surface is identified, but no submission was sent.
- `submitted`: the submission was sent and is waiting for a response.
- `accepted`: the surface accepted or published the listing, with evidence.
- `rejected`: the surface rejected the listing, with the reason recorded.
- `blocked`: submission cannot proceed until the blocker is resolved.

## Required Fields

Every row must carry these fields. A submission also requires a completed owner
approval packet in
[submission-owner-approval-packet.md](submission-owner-approval-packet.md)
before `date_submitted` can be filled.

| Field | Required meaning |
| --- | --- |
| `surface` | Marketplace, registry, directory, or discovery surface. |
| `submission_url` | Current URL for the submission form, docs, registry, or issue. |
| `submission_owner` | Person or role responsible for the next action. |
| `date_checked` | Date the current submission rules were last checked. |
| `date_submitted` | Date submitted, or blank when not submitted. |
| `status` | One of `not_submitted`, `submitted`, `accepted`, `rejected`, `blocked`. |
| `blocker` | What prevents the next action, or `none`. |
| `next_action` | Concrete next owner action. |
| `evidence_link` | URL, PR, issue, release, screenshot reference, or `none`. |
| `notes` | Short factual note; no unsupported claims. |

## Owner Approval Packet Fields

A3.4 remains `blocked_pending_owner_approval` until the owner completes these
fields for the exact destination:

| Field | Required meaning |
| --- | --- |
| `destination` | Exact marketplace, registry, directory, or discovery surface. |
| `current_rule_check_date` | Date when the current rules were checked; must be refreshed on the submission day. |
| `submission_owner` | Person or role accountable for the submission and follow-up. |
| `exact_listing_copy_reference` | Exact repo file, section, commit, or external draft used as listing copy. |
| `submitter` | One of `owner`, `Codex`, or `human_delegate`. |
| `permission_to_submit` | One of `yes` or `no`; default is `no`. |
| `evidence_required_after_submission` | Evidence to capture after sending, such as submission URL, issue, screenshot reference, rejection summary, or accepted listing URL. |
| `blocked_claims_acknowledged` | Confirmation that blocked claims are not used. |
| `fallback_if_rejected` | Concrete fallback if the destination rejects, blocks, or ignores the listing. |

## Tracker

Rollup status: as of
[`public-alpha-signal-rollup-002.md`](public-alpha-signal-rollup-002.md), all
tracked surfaces remain `not_submitted`. A3.4 actual submission evidence stays
`blocked_pending_owner_approval` until the owner approves exact destinations,
submission owner, listing copy, submitter, and Codex submission permission in
the owner approval packet.

| surface | submission_url | submission_owner | date_checked | date_submitted | status | blocker | next_action | evidence_link | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Code plugin marketplace | https://code.claude.com/docs/en/plugins | release owner | 2026-06-13 |  | not_submitted | current Claude Code CLI validation must be run immediately before submission | Run `claude plugin validate .`, re-check current submission docs, then submit with marketplace copy if still allowed. | none | Track as a plugin marketplace submission only after owner action. |
| MCP Registry / discovery | https://registry.modelcontextprotocol.io/ | release owner | 2026-06-13 |  | not_submitted | verify whether a local CLI gateway package is accepted by the current registry rules | Re-check current registry rules and submit only if the surface accepts PyPI/local CLI gateway metadata. | none | Do not imply hosted MCP server availability. |
| GitHub repository discovery | https://github.com/AI4sale/unlimited-skills | release owner | 2026-06-13 |  | not_submitted | repo topics and release copy need owner review | Align topics and README/release copy with local-first public alpha positioning. | https://github.com/AI4sale/unlimited-skills/releases/tag/v0.5.1-alpha | Repository exists; this is discovery hygiene, not external acceptance. |

## Claim Guard

Allowed:

- free public alpha;
- local-first;
- no telemetry;
- no auto-upload;
- PyPI package `unlimited-skills==0.5.3`;
- GitHub release `v0.5.3-alpha`;
- measured MCP savings and frozen eval numbers already present in the repo.

Blocked:

- paid CTA;
- payment link;
- hosted/team/enterprise readiness claim;
- production hosted gateway claim;
- guaranteed marketplace acceptance;
- delivery promise;
- unsupported claim that a surface accepted the project.

## A3.4 Approval Rule

Do not send a submission or claim submission evidence until:

1. the destination row is current;
2. the owner approval packet is complete;
3. `permission_to_submit` is `yes`;
4. `submitter` is explicit;
5. `exact_listing_copy_reference` points to the exact copy being sent;
6. every destination has a fresh current-rule check;
7. evidence and fallback are written before sending.

If the owner has not completed those fields, keep the row `not_submitted` and
keep A3.4 `blocked_pending_owner_approval`.

## Update Rule

When a submission changes state:

1. Re-check the current rules for that surface.
2. Update `date_checked`.
3. Update `date_submitted` only after a submission is actually sent.
4. Add an evidence link or screenshot reference when available.
5. Record blockers and next owner action in plain language.
6. Keep rejected and blocked rows; do not delete inconvenient history.

## Related Docs

- [Marketplace/listing launch pack](marketplace-listing-launch-pack.md)
- [Marketplace listing copy](marketplace-listing-copy.md)
- [Marketplace submission runbook](marketplace-submission-runbook.md)
- [Submission owner approval packet](submission-owner-approval-packet.md)
- [Public-alpha feedback triage workflow](feedback-triage-workflow.md)
