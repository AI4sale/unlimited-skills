# Money Saved Meter Reproducible Measurement Walkthrough

**Roadmap item:** US-064-004
**Status:** documentation and verifier path for local reproduction. This is not
the push nudge, persistent meter state writer, paid-tier export, release gate,
version bump, tag, publish, hosted telemetry, or marketplace submission.

This walkthrough is the single user path for reproducing the v0.6.4 Money Saved
Meter locally. It ties together the [value model](money-saved-meter-value-model.md),
the [JSON contract](money-saved-meter-json-contract.v1.md), the
[before/after command](money-saved-meter-before-after-command.md), the
[100-call fixture](money-saved-meter-100-call-value-report.md), and the
[known limitations](../../reports/v0.6.4-money-saved-meter-known-limitations.md).

## What The Meter Can Prove

The meter separates three classes of evidence:

- exact counts, such as router calls, gateway/MCP calls, and window call count;
- measured bytes, such as local MCP schema/context bytes when source artifacts
  expose byte sizes;
- estimates, such as tokens derived from measured bytes by a documented method.

The 100-call window is cadence, not billing math. It gives operators a stable
reporting frame for comparing output and verifying privacy boundaries. It does
not convert one local measurement into provider billing, exact tokens, exact
money, or a guaranteed billing outcome.

Tokens are estimates. Dollars are disabled by default. The command is local-only.

## Step 1: Empty Or Current Local Report

Use current mode when you want a local aggregate report without a before/after
comparison:

```powershell
unlimited-skills money-saved meter --json
```

The command emits `report_type=money_saved_meter` JSON. Without local source
artifacts, missing values remain unavailable or partial; the meter does not
invent complete-window values.

For Markdown output:

```powershell
unlimited-skills money-saved meter
```

## Step 2: Before Install Or Before Gateway Change

Capture the local MCP savings artifact before installing or changing the
Unlimited Skills gateway:

```powershell
unlimited-skills mcp savings --json > before-mcp-savings.json
unlimited-skills money-saved meter --json --mode before --mcp-savings-json before-mcp-savings.json --out before-meter.json
```

Keep `before-meter.json` locally. It contains aggregate-safe fields only and is
the baseline used for a later local comparison.

## Step 3: After Install Or After Gateway Change

After installing/configuring Unlimited Skills and collecting local use, capture
the after report and compare it with the before report:

```powershell
unlimited-skills mcp savings --json > after-mcp-savings.json
unlimited-skills money-saved meter --json --mode after --mcp-savings-json after-mcp-savings.json --compare before-meter.json --out after-meter.json
```

The comparison can show measured byte deltas when both local reports contain
measured context bytes. Token deltas remain estimates. Dollar value remains
disabled by default unless a future local price configuration is implemented.

## Step 4: Deterministic 100-Call Fixture

Use the fixture when you need a reproducible complete-window report that does
not depend on the current machine state:

```powershell
unlimited-skills money-saved meter --json --fixture-100-call --out 100-call-value-report.json
```

Verify the report source fixtures and expected output:

```powershell
python scripts/verify-money-saved-100-call-report.py --json
python scripts/verify-money-saved-meter-100-call-fixture.py --json
```

Both verifier scripts are local-only. They prove the deterministic fixture still
produces the expected complete 100-call report and that the report does not drift
into unsafe claims.

## Step 5: Interpret Complete And Partial Windows

A complete fixture window has:

```text
target_call_count=100
window_call_count=100
is_complete_window=true
cadence_not_billing_math=true
```

A partial window reports counts so far. It must not extrapolate exact tokens,
exact dollars, or provider bill reduction. Empty/current mode is valid when it
honestly reports unavailable source artifacts.

## Step 6: Compare JSON And Markdown

JSON is the contract surface. Markdown is the human-readable summary.

For the deterministic fixture, JSON and Markdown must agree on:

- target call count;
- window call count;
- complete versus partial status;
- measured context bytes avoided;
- estimated tokens avoided;
- dollar value disabled by default;
- the statement that the 100-call window is cadence/reporting, not billing math.

The stable Markdown excerpt lives in
`tests/fixtures/money_saved_meter/100-call-markdown-excerpt.md`. The expected
JSON output lives in
`tests/fixtures/money_saved_meter/100-call-value-report.json`.

## Step 7: Privacy Boundary Check

The meter output must not include:

- raw prompts;
- raw task text;
- skill bodies;
- local absolute paths;
- tokens, keys, or secrets;
- customer names;
- private repo paths;
- raw MCP schemas;
- raw MCP payloads;
- server command lines or environment values.

The verifier checks these boundaries against fixture output. For real local
reports, review the same boundary before sharing any artifact.

## What Is Not Implemented Yet

The current v0.6.4 development surface does not implement:

- push nudge;
- persistent meter state writer;
- paid-tier exports;
- hosted telemetry;
- provider billing integration;
- release, version bump, tag, PyPI publish, or marketplace submission.

The allowed claim remains narrow:

> Unlimited Skills estimates local context savings from routed skill/tool usage.
