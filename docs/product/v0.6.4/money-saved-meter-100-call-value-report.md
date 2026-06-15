# Money Saved Meter 100-Call Value Report Fixture

**Roadmap item:** US-064-003
**Status:** deterministic local fixture and verifier implemented. This is not a
push nudge, persistent meter state writer, paid-tier export, release gate,
version bump, tag, or publish step.

## Purpose

The 100-call fixture proves that the Money Saved Meter can show cumulative saved
context over one complete local reporting window. The window is a cadence for
operator review, not billing math.

## Reproduce

```powershell
unlimited-skills money-saved meter --json --fixture-100-call --out 100-call-value-report.json
python scripts/verify-money-saved-100-call-report.py --json
```

The repository source fixtures and expected output live at:

```text
tests/fixtures/money_saved_meter/100-call-mcp-savings.json
tests/fixtures/money_saved_meter/100-call-gateway-audit.jsonl
tests/fixtures/money_saved_meter/100-call-before-meter.json
tests/fixtures/money_saved_meter/100-call-value-report.json
tests/fixtures/money_saved_meter/100-call-markdown-excerpt.md
```

## Contract

- `target_call_count=100`.
- `window_call_count=100`.
- `is_complete_window=true`.
- Exact values remain counts only.
- Context bytes are measured bytes from local aggregate MCP savings fixture data.
- Estimated tokens are labeled with `method=bytes_divided_by_4`.
- Dollar value is disabled by default and remains null.
- The report includes no raw prompts, task text, skill bodies, paths, secrets,
  customer names, private repo paths, raw MCP schemas, or raw MCP payloads.

## Boundaries

Allowed claim:

> Unlimited Skills estimates local context savings from routed skill/tool usage.

Forbidden claims remain:

- exact tokens saved;
- exact money saved;
- guaranteed bill reduction;
- hosted telemetry-backed savings;
- all skill-body savings measured exactly;
- provider billing reconciliation.

No hosted telemetry, upload, billing provider integration, marketplace
submission, release publication, or paid-tier export is introduced by this
fixture.

Partial and empty windows remain honest: they report counts so far and never
extrapolate exact tokens, exact dollars, or provider bill reduction.
