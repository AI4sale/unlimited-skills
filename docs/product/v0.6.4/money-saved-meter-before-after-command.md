# Money Saved Meter Before/After Measurement Command

**Roadmap item:** US-064-002
**Status:** local pull command implemented. This is not the push nudge, state
writer, paid-tier export, release gate, version bump, tag, or publish step.

## Purpose

`unlimited-skills money-saved meter` gives users a reproducible local
before/after install measurement flow. It converts existing local MCP savings
and optional gateway audit summaries into the v0.6.4 Money Saved Meter value
model without uploading anything and without printing raw private inputs.

## Reproduce: Measure Before and After Install

Before installing or switching to the Unlimited Skills gateway:

```powershell
unlimited-skills mcp savings --json > before-mcp-savings.json
unlimited-skills money-saved meter --json --mode before --mcp-savings-json before-mcp-savings.json --out before-meter.json
```

After install and some local usage:

```powershell
unlimited-skills mcp savings --json > after-mcp-savings.json
unlimited-skills money-saved meter --json --mode after --mcp-savings-json after-mcp-savings.json --compare before-meter.json --out after-meter.json
```

The comparison is local and aggregate-only. When both reports contain measured
context bytes, the command reports the byte delta. Token values remain estimates
using the documented `bytes_divided_by_4` heuristic. Dollar value is unavailable
by default.

## Command Contract

```text
unlimited-skills money-saved meter
unlimited-skills money-saved meter --json
unlimited-skills money-saved meter --mode before|after|current
unlimited-skills money-saved meter --mcp-savings-json <file>
unlimited-skills money-saved meter --audit-log <file>
unlimited-skills money-saved meter --compare <before-meter.json>
unlimited-skills money-saved meter --out <file>
```

Default output is Markdown. `--json` emits `report_type=money_saved_meter`.
`--out` writes the selected format only to the explicit local file. The command
does not write `<root>/.learning/savings-meter.json` and does not emit an
ambient nudge.

## Source Inputs

Allowed inputs:

- an existing `unlimited-skills mcp savings --json` artifact;
- the latest sanitized local `mcp_savings` event when no artifact is supplied;
- an optional MCP gateway audit log for aggregate `summary.total_calls`;
- local router metrics for aggregate router invocation counts;
- a prior Money Saved Meter JSON report for local before/after comparison.

The command strips server names, schemas, commands, env, local paths, and raw MCP
payloads from output.

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

The command is local-only: no telemetry, upload, hosted calls, billing provider,
marketplace submission, or release publication.
