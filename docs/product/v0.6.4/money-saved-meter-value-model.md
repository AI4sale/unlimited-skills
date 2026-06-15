# v0.6.4 Money Saved Meter Value Model

**Roadmap item:** US-064-001
**Status:** model/spec only. This document does not implement a runtime meter,
CLI command, nudge writer, state file, version bump, release, tag, publish, or
hosted surface.

## Purpose

The Money Saved Meter explains the local value of Unlimited Skills by showing how
the router and MCP gateway avoid flooding the agent with every skill body and
every upstream MCP tool schema. The model is deliberately conservative:

- exact counts are counts only;
- byte measurements are measured only when existing local artifacts expose byte
  sizes;
- token savings are estimates;
- dollar value is disabled unless the user provides local pricing config;
- no hosted telemetry, billing-provider reconciliation, raw prompt, raw task, or
  raw MCP payload is required or allowed.

The user-facing claim is:

> Unlimited Skills estimates local context savings from routed skill/tool usage.

## Source Inputs

The model may read only existing local, privacy-safe signals:

| Input | Allowed use | Boundary |
| --- | --- | --- |
| Router Inject v2 inventory snapshot | Count available routing coverage and document which router inventory version was used. | Do not emit local paths, private collection paths, skill bodies, or raw domain token lists beyond approved aggregate docs. |
| Local router metrics | Count router calls, suggested skills, injected skill cards, delivery tier, and retrieval path aggregates. | Do not emit prompts, raw task text, query hashes, full skill bodies, or local absolute paths. |
| Local event logs after privacy sanitizer | Read aggregate safe events such as sanitized `mcp_savings`, router delivery, and learning counters. | Reject unsafe legacy rows and do not read raw prompt/task/query payloads. |
| MCP savings and gateway context-budget artifacts | Measure available schema bytes, gateway meta-tool bytes, and local savings bytes when artifacts expose them. | Do not emit raw MCP schemas, server configs, command lines, env values, server names, or raw tool payloads. |
| Existing ROI receipt where compatible | Reuse aggregate privacy notices, local-only flags, and compatible savings summary fields. | Do not change existing ROI receipt fields in this task. |

## Exact Counted Fields

These fields are exact local counts when the source artifact exists. They are not
token, dollar, or billing claims.

The exact counted fields are router call count, suggested skill count, injected
skill card count, and gateway/MCP call count.

Exact counted fields: router call count, suggested skill count, injected skill card count, gateway/MCP call count.

| Field | Meaning | Source |
| --- | --- | --- |
| `exact_counts.router_call_count` | Number of local router invocations in the reporting window. | Local router metrics. |
| `exact_counts.suggested_skill_count` | Number of skills suggested by the router in the window, counted from safe aggregate rows. | Router metrics or sanitized event rows. |
| `exact_counts.injected_skill_card_count` | Number of skill cards injected into the agent context in the window. | Router metrics, hook delivery metadata, or sanitized event rows. |
| `exact_counts.gateway_mcp_call_count` | Number of MCP gateway meta-tool calls when gateway audit summaries exist. | MCP audit report summary. |

The model may also include `exact_counts.window_call_count`, which is the count
used for per-100-call framing. It must state whether it counts gateway calls,
router calls, or both.

## Measured Byte Fields

Byte fields are measured only when local artifacts expose sizes. Missing byte
artifacts must be represented as unavailable, not guessed.

| Field | Meaning | Source |
| --- | --- | --- |
| `measured_bytes.upstream_schema_bytes` | Full upstream MCP `tools/list` schema bytes measured locally. | MCP savings/context-budget artifact. |
| `measured_bytes.gateway_schema_bytes` | Gateway meta-tool schema bytes measured locally. | MCP savings/context-budget artifact. |
| `measured_bytes.context_bytes_avoided` | Difference between upstream schema bytes and gateway schema bytes. | Derived only from measured byte fields. |
| `measured_bytes.skill_card_bytes_injected` | Size of injected router skill cards when the local surface exposes the card bytes. | Hook/router delivery artifact. |

Skill-body savings are not exact unless a future local artifact explicitly
measures the before/after skill-body bytes. Without that artifact, skill routing
may be described as an estimate of avoided context pressure, not as measured
skill-body savings.

## Estimated Fields

Estimated fields must carry an explicit `measurement_kind: "estimated"` marker
and must name their method.

| Field | Meaning | Required label |
| --- | --- | --- |
| `estimates.estimated_tokens_avoided` | Estimated tokens avoided from measured or modeled context bytes. | Estimated tokens. |
| `estimates.estimated_context_bytes_avoided` | Estimated context bytes avoided when derived from body/schema size assumptions rather than direct measurement. | Estimated context bytes. |
| `estimates.estimated_dollar_value` | Optional estimated dollar value from locally configured pricing. | Estimated dollars, user local rate. |

The default token method is `bytes_divided_by_4`, matching existing local ROI
and MCP savings heuristics. Any later method must be named and documented.

## Disabled-by-Default Fields

These fields must be unavailable until the user explicitly configures them
locally:

- dollar value;
- provider-specific price assumptions;
- billing model names;
- token price per 1K or 1M tokens;
- anything requiring hosted telemetry;
- anything requiring billing-provider integration.

When unavailable, the output must say why, for example:

```json
{
  "enabled": false,
  "configured_locally": false,
  "reason": "disabled_by_default_no_local_price_config"
}
```

## Explicitly Forbidden Fields

The Money Saved Meter output must never include:

- raw prompts;
- raw task text;
- skill bodies;
- local absolute paths;
- tokens, keys, secrets;
- customer names;
- hosted uploads;
- private repo paths;
- raw MCP tool input/output payloads;
- raw MCP schemas;
- MCP server command lines or env values;
- billing-provider account identifiers.

If a source row contains any of these values, the meter must reject, skip, or
sanitize the row before producing output.

## Claim Boundary

Allowed claims:

- "Unlimited Skills estimates local context savings from routed skill/tool usage."
- "Bytes may be measured when local artifacts expose sizes."
- "Tokens and dollars are estimates."

Forbidden claims:

- "exact tokens saved"
- "exact money saved"
- "bill reduction guaranteed"
- "hosted telemetry-backed savings"
- "all skill-body savings measured exactly"
- "provider billing reconciliation"

Public wording must describe the meter as local, aggregate, privacy-safe, and
estimate-forward. It must not imply a bill guarantee or hosted analytics.

## Per-100-Call Framing

"100 calls" is a local reporting window and cadence, not billing math.

The contract must define:

- `target_call_count`: the nominal cadence, normally `100`;
- `counted_call_kinds`: which local calls count, such as `gateway_mcp_call` and
  `router_call`;
- `window_call_count`: how many counted calls are currently present;
- `is_complete_window`: whether the window reached `target_call_count`;
- `partial_window_policy`: how incomplete windows are shown.

Partial windows are reported as counts-so-far. They must not be extrapolated into
exact savings, exact tokens, or exact dollars.

Empty-state output must be useful and honest: counts are zero, byte measurements
are unavailable, estimates are unavailable, dollar value is disabled, and the
next action tells the user which local command or usage surface can generate
safe source artifacts.

## Output Rules

Every JSON output conforming to this model must:

- include `schema_version`;
- include `report_type: "money_saved_meter_value_model"`;
- separate exact counts, measured bytes, estimates, disabled-by-default fields,
  forbidden fields, source inputs, and claim boundary;
- mark estimate fields explicitly;
- avoid raw prompt/task/tool/schema/path/customer/private-repo data;
- use local-only privacy flags;
- state that it is model/spec only until a later runtime task implements a
  command or nudge.

## Non-Goals

US-064-001 does not implement:

- a Money Saved Meter CLI command;
- a per-100-call nudge;
- a state file writer;
- a runtime meter module;
- hosted analytics;
- billing provider integration;
- exact dollar claims;
- version bump, tag, publish, release, marketplace, hosted, team, business, or
  enterprise rollout.
