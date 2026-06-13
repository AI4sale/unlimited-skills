# Public-Alpha Signal Rollup Template

Use this template for public-alpha adoption rollups when the generated report
needs manual review or owner-supplied aggregate context.

The preferred path is the reproducible generator:

```bash
python scripts/generate-public-alpha-signal-rollup.py --fixture-mode --out /tmp/rollup.md
python scripts/generate-public-alpha-signal-rollup.py --out docs/adoption/public-alpha-signal-rollup-002.md
```

Optional owner-provided social context must be a local aggregate JSON file and
must be called out as owner-provided input:

```bash
python scripts/generate-public-alpha-signal-rollup.py \
  --out docs/adoption/public-alpha-signal-rollup-002.md \
  --social-json owner-social-summary.json
```

Do not add telemetry, tracking pixels, analytics SDKs, hidden identifiers,
private user data, prompt collection, tool input collection, tool output
collection, hosted query forwarding, private social scraping, paid CTAs,
payment links, hosted/team/enterprise readiness claims, marketplace acceptance
claims, or delivery promises.

Required privacy boundary: no telemetry; no auto-upload; no tracking pixels;
no analytics SDKs; no hidden identifiers; no private user data; no prompt
collection; no tool input collection; no tool output collection; no hosted
query forwarding.

Blocked data paths: no hosted query forwarding; no private social scraping.

## Rollup Summary

- Distribution state:
- Release state:
- Feedback state:
- Marketplace state:
- Claim state:

## Data Sources Checked

| Source | Mode | Result |
| --- | --- | --- |
| PyPI JSON | public aggregate |  |
| GitHub release | public aggregate |  |
| GitHub repository counters | public aggregate |  |
| GitHub public issues | public/manual |  |
| Marketplace tracker | local file |  |
| Owner social JSON | owner-provided manual aggregate |  |

## Installation/Discovery Signals

- PyPI package:
- GitHub release:
- GitHub stars/forks/watchers:
- Marketplace/listing status:

## First-Value Signals

- First-value feedback reports:
- Install-friction reports:
- Skill-not-invoked reports:
- MCP savings reports:
- Decision state:

## Feedback/Issues

- Public issues returned:
- Open PRs observed:
- Repeated blockers:

## Marketplace/Listing Status

- Tracker statuses:
- A3.4 status:
- Evidence link requirements:

## Social/LinkedIn Launch Signal

- Owner-provided manual social input:
- Public URL:
- Aggregate metrics:
- Summary:

## Signal Quality Assessment

- Signal quality:
- Feedback state:
- Confidence limits:

## Blockers

| Blocker | Owner | Action | Fallback |
| --- | --- | --- | --- |
|  |  |  |  |

## Next Actions

1. 
2. 
3. 

## Non-Goals and Claim Guard

This rollup must not claim telemetry, automatic upload, analytics, private
social scraping, marketplace submission, paid CTA, payment links, hosted
service readiness, team readiness, enterprise readiness, SLA/support delivery,
external acceptance, or production hosted gateway availability.
