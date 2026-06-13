# Public-Alpha Signal Rollup 002

Date checked: 2026-06-13

Scope: generated public-alpha adoption signal rollup for Unlimited Skills.
This report uses only public aggregate sources, local repository files, and
optional owner-provided manual aggregate input. It does not add telemetry,
tracking pixels, analytics SDKs, hidden identifiers, private user data,
prompt collection, tool input collection, tool output collection, or hosted
query forwarding.

Privacy boundary: no telemetry; no auto-upload; no tracking pixels; no
analytics SDKs; no hidden identifiers; no private user data; no prompt
collection; no tool input collection; no tool output collection; no hosted
query forwarding.

Blocked data paths: no hosted query forwarding; no private social scraping.

## Rollup Summary

- Distribution state: PyPI package `unlimited-skills==0.5.3` is `available`.
- Release state: GitHub release `v0.5.3-alpha` is `available`.
- Feedback state: `low_signal` / `no_feedback_yet` unless public/manual reports are added.
- Marketplace state: not_submitted=3.
- Claim state: no marketplace submission, paid outreach, payment links,
  hosted/team/enterprise readiness claims, external acceptance claims, or
  delivery promises are made by this rollup.

## Data Sources Checked

| Source | Mode | Result |
| --- | --- | --- |
| PyPI JSON for `unlimited-skills` | live_public | latest `0.5.3`; recent releases: 0.5.0, 0.5.1, 0.5.2, 0.5.3; error: none |
| GitHub release `v0.5.3-alpha` | live_public | name `v0.5.3-alpha - local event privacy hardening`; prerelease `True`; published `2026-06-13T20:18:36Z`; error: none |
| GitHub repo counters for `AI4sale/unlimited-skills` | live_public | 5 stars, 0 forks, 0 watchers; error: none |
| GitHub public issues | live_public | 0 non-PR issues returned; open PRs: #119 feat: add MCP profile bundle publisher and signing ceremony (E19); error: none |
| Marketplace tracker | local file | `docs/adoption/marketplace-submission-tracker.md`; statuses: not_submitted=3; error: none |

## Installation/Discovery Signals

- PyPI availability: `unlimited-skills==0.5.3`.
- GitHub release availability: `v0.5.3-alpha`.
- GitHub public interest counters: 5 stars, 0 forks, 0 watchers.
- PyPI download counts are not inferred from PyPI JSON because that endpoint
  does not expose download counts.

## First-Value Signals

- First-value reports: none included by default.
- Install-friction reports: none included by default.
- Skill-not-invoked reports: none included by default.
- MCP savings reports: none included by default.
- Decision state: `no_feedback_yet` until manual issue reports or
  owner-provided public aggregate summaries are attached.

## Feedback/Issues

- Public issues returned: 0.
- Open PRs observed: #119 feat: add MCP profile bundle publisher and signing ceremony (E19).
- The parked PR #119 remains outside this adoption rollup unless the owner
  explicitly reopens it.
- Do not infer private usage from silence. Silence means unknown, not success.

## Marketplace/Listing Status

- Tracker statuses: not_submitted=3.
- A3.4 actual submission evidence remains `blocked_pending_owner_approval`
  until the owner approval packet names exact destinations, submission owner,
  exact listing copy reference, submitter, evidence requirements, fallback, and
  `permission_to_submit: yes`.
- Keep all marketplace rows `not_submitted` until there is a dated owner action
  and evidence link.

## Social/LinkedIn Launch Signal

- Owner-provided manual social input: not provided.
- LinkedIn or other social replies/comments are not inferred from private accounts.
- Signal state: `no_feedback_yet` unless a public/manual source is added.

## Signal Quality Assessment

- Signal quality: `low_signal`.
- Feedback state: `no_feedback_yet`.
- This rollup is useful as a reproducible baseline, not as proof of adoption.
- Next rollups should compare only public aggregate counters and manual
  redacted feedback artifacts.

## Blockers

| Blocker | Owner | Action | Fallback |
| --- | --- | --- | --- |
| No manual first-value reports | Release owner | Ask for three redacted first-value or install-friction reports | Publish a focused install/first-value request |
| Marketplace submission evidence missing | Project owner | Complete the owner approval packet with exact destinations, submission owner, exact listing copy reference, submitter, evidence requirements, fallback, and `permission_to_submit: yes` | Keep all marketplace rows `not_submitted` |
| Social signal not provided | Release owner | Add owner-provided aggregate social JSON if available | Keep `no_feedback_yet` |

## Next Actions

1. Generate the next rollup with
   `python scripts/generate-public-alpha-signal-rollup.py --out docs/adoption/public-alpha-signal-rollup-003.md`.
2. Attach optional owner-provided aggregate social input with `--social-json`
   only when the owner supplies it intentionally.
3. Keep issue triage and support responses aligned with
   `docs/adoption/support-response-pack.md`.

## Non-Goals and Claim Guard

This rollup does not implement or claim telemetry, automatic upload, analytics,
private social scraping, marketplace submission, paid CTA, payment links,
hosted service readiness, team readiness, enterprise readiness, SLA/support
delivery, external acceptance, or production hosted gateway availability.
