# Local ROI Receipt

Local ROI receipt is a v0.6 specification for a future local-only command that
summarizes the value a user has already measured on their own machine.

It is not implemented yet. The development-ready spec is
[releases/v0.6-local-roi-receipt-spec.md](releases/v0.6-local-roi-receipt-spec.md).

## Planned Commands

```bash
unlimited-skills roi receipt
unlimited-skills roi receipt --format markdown
unlimited-skills roi receipt --format json
unlimited-skills roi receipt --since 7d
unlimited-skills roi receipt --out roi-receipt.md
```

## What The Receipt May Show

Only aggregate or derived local-safe values:

- installed Unlimited Skills version;
- local library skill count;
- quickstart status;
- MCP savings summary from `mcp savings`;
- suggest count;
- skill view/use count;
- suggest-to-view/use aggregate conversion;
- `learning-summary --events` aggregate funnel metrics;
- `feedback prepare` availability/status;
- generated timestamp;
- local-only/no-upload notice.

## What The Receipt Must Never Show

- prompts;
- raw queries;
- raw tasks;
- tool inputs;
- tool outputs;
- skill bodies;
- MCP schemas;
- raw `events.jsonl`;
- raw `feedback.jsonl`;
- raw `.mcp.json` or `.claude.json`;
- environment names or values;
- tokens, keys, or proofs;
- local absolute paths;
- user identifiers;
- tracking identifiers.

## Required Notice

Every receipt must carry this wording:

> This receipt is a local estimate from your own machine. It is not telemetry,
> not a benchmark guarantee, and not a paid ROI promise.

## Status

This is a local-first adoption spec. It does not add telemetry, upload,
analytics, tracking pixels, sales/payment flows, hosted readiness, team
readiness, enterprise readiness, universal savings promises, or #119/E19 work.
