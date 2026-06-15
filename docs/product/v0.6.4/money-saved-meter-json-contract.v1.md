# Money Saved Meter JSON Contract v1

**Roadmap item:** US-064-001
**Status:** model/spec only. This contract names the future JSON shape but does
not implement a runtime command or writer.

## Contract Identity

Required top-level identity fields:

| Field | Type | Required value |
| --- | --- | --- |
| `schema_version` | integer | `1` |
| `report_type` | string | `money_saved_meter_value_model` |
| `generated_at` | string or null | ISO-8601 UTC timestamp when generated, or null for fixtures. |
| `mode` | string | `empty`, `example`, or future runtime mode. |

## Stable Top-Level Fields

The v1 contract has these stable top-level fields:

```text
schema_version
report_type
generated_at
mode
model_scope
window
source_inputs
exact_counts
measured_bytes
estimates
disabled_by_default
forbidden_fields
claim_boundary
privacy
next_actions
```

Future runtime tasks may add optional fields, but must not change the meaning of
these fields before a new schema version.

## Window Object

`window` defines the local reporting cadence:

| Field | Type | Meaning |
| --- | --- | --- |
| `label` | string | Human-readable window name, for example `per_100_call_reporting_window`. |
| `target_call_count` | integer | Nominal cadence target. The v1 default is `100`. |
| `counted_call_kinds` | array[string] | Local call kinds counted in this window. |
| `window_call_count` | integer | Counted calls currently present. |
| `is_complete_window` | boolean | True only when the target is reached. |
| `cadence_not_billing_math` | boolean | Must be true. |
| `partial_window_policy` | string | Required explanation for incomplete windows. |

Partial windows report counts-so-far and must not extrapolate exact tokens,
exact dollars, or bill changes.

## Source Inputs Object

Each source input is a small object with:

```json
{
  "status": "available | unavailable | skipped",
  "source_kind": "router_inventory | router_metrics | sanitized_event_log | mcp_savings | roi_receipt",
  "privacy_boundary": "aggregate_only_no_raw_payloads"
}
```

Allowed source keys:

- `router_inject_v2_inventory_snapshot`
- `local_router_metrics`
- `sanitized_local_event_logs`
- `mcp_savings_context_budget`
- `compatible_roi_receipt`

## Exact Counts Object

Each exact-count field is an object:

```json
{
  "value": 0,
  "measurement_kind": "exact",
  "source": "local_router_metrics"
}
```

Required keys:

- `router_call_count`
- `suggested_skill_count`
- `injected_skill_card_count`
- `gateway_mcp_call_count`
- `window_call_count`

Exact counts do not imply token, dollar, or billing savings.

## Measured Bytes Object

Each measured-byte field is an object:

```json
{
  "value": null,
  "measurement_kind": "measured",
  "available": false,
  "source": "mcp_savings_context_budget",
  "reason": "no_local_artifact"
}
```

Required keys:

- `upstream_schema_bytes`
- `gateway_schema_bytes`
- `context_bytes_avoided`
- `skill_card_bytes_injected`

Measured byte values may be non-null only when local artifacts expose sizes.
Skill body savings are unavailable unless a future artifact measures skill-body
bytes directly.

## Estimates Object

Estimated fields are explicit and method-labeled:

```json
{
  "value": null,
  "measurement_kind": "estimated",
  "available": false,
  "method": null,
  "reason": "requires_measured_or_modeled_context_bytes"
}
```

Required keys:

- `estimated_tokens_avoided`
- `estimated_context_bytes_avoided`
- `estimated_dollar_value`

`estimated_tokens_avoided.method` should be `bytes_divided_by_4` when derived
from measured or modeled bytes. `estimated_dollar_value` must remain disabled
unless the user supplies local price config.

Dollar value remains unavailable unless local user configuration supplies a
price.

Dollar value remains unavailable unless local user configuration supplies a price.

## Disabled-by-Default Object

Required keys:

- `dollar_value`
- `provider_specific_price_assumptions`
- `hosted_telemetry`
- `billing_provider_integration`

Each value must include:

```json
{
  "enabled": false,
  "configured_locally": false,
  "reason": "disabled_by_default"
}
```

Future user-local configuration may enable dollar estimates, but cannot enable
hosted telemetry or billing-provider integration in this local model.

## Forbidden Fields Object

`forbidden_fields` must list the values that output must not contain:

- raw prompts
- raw task text
- skill bodies
- local absolute paths
- tokens, keys, secrets
- customer names
- hosted uploads
- private repo paths
- raw MCP tool input/output payloads

The list is a boundary declaration, not an output payload. A runtime
implementation must also scan serialized output for these classes.

## Claim Boundary Object

Required arrays:

- `allowed_claims`
- `forbidden_claims`

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

## Privacy Object

Required booleans:

```json
{
  "local_only": true,
  "upload": false,
  "hosted_telemetry": false,
  "raw_prompts_included": false,
  "raw_task_text_included": false,
  "skill_bodies_included": false,
  "local_absolute_paths_included": false,
  "tokens_keys_secrets_included": false,
  "customer_names_included": false,
  "private_repo_paths_included": false,
  "raw_mcp_payloads_included": false
}
```

## Fixture Requirements

The empty fixture must show zero counts, unavailable measurements, unavailable
estimates, disabled dollar value, and clear next actions.

The example fixture may show aggregate local counts and measured bytes, but must
not contain raw prompts, raw task text, skill bodies, local absolute paths,
tokens, keys, secrets, customer names, hosted uploads, private repo paths, raw
MCP tool input payloads, raw MCP tool output payloads, or raw MCP schemas.

The example fixture must not contain raw prompts.
