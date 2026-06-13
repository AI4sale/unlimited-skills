# Local ROI Receipt

`unlimited-skills roi receipt` prints a local, screenshot-friendly receipt that
summarizes aggregate value signals from your own machine.

The command is local-only. It does not upload data, contact a hosted service,
enable telemetry, add analytics, or read private skill bodies into the output.

## Commands

```bash
unlimited-skills roi receipt
unlimited-skills roi receipt --format markdown
unlimited-skills roi receipt --format json
unlimited-skills roi receipt --since 7d
unlimited-skills roi receipt --out roi-receipt.md
```

Default output is screenshot-friendly Markdown. The footer includes:
`Local-only: yes. Upload: no. Telemetry: no.`

`--format json` emits the schema-versioned JSON contract in
[schemas/roi-receipt.schema.json](../schemas/roi-receipt.schema.json). A
paste-safe example lives at
[examples/roi-receipt.example.json](../examples/roi-receipt.example.json).
The boundary verifier is
[scripts/verify-roi-receipt-boundaries.py](../scripts/verify-roi-receipt-boundaries.py).
`--out` writes the selected format to a local file and prints only a short
write status; it does not print the local output path.

## What The Receipt May Show

Only aggregate or derived local-safe values:

- installed Unlimited Skills version;
- local library skill count;
- quickstart status;
- MCP savings summary from the latest local `mcp savings` event, or a lab
  fallback summary when no local savings event exists;
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

## Legacy Logs

Post-v0.5.3 local events are sanitized before they are written. If the receipt
sees legacy pre-v0.5.3 rows with unsafe raw fields, it skips those rows and
marks the window as `unavailable_legacy_logs` instead of copying raw values.

## Required Notice

Every receipt carries this wording:

> This receipt is a local estimate from your own machine. It is not telemetry,
> not a benchmark guarantee, and not a paid ROI promise.

## Boundary

This command does not add upload, telemetry, analytics, tracking pixels,
sales/payment flows, hosted readiness, team readiness, enterprise readiness,
universal savings promises, ROI guarantees, or #119/E19 work.
