# MCP audit replay and policy impact simulator (E17)

`unlimited-skills mcp profiles replay-audit` takes the HISTORICAL redacted
MCP audit JSONL log (the E11 inspector's readers: the active file plus
rotated generations `.1`..`.N`, read chronologically; malformed lines
counted and skipped) and a PROPOSED policy -- a raw E09/E10 profile file, an
E13/E14 signed bundle, the E14/E15 trust artifacts, and optionally the
gateway upstream config -- and answers, before anything is applied:

- which historical tool calls would still pass under the proposed policy;
- which would be refused, with exactly which would-be refusal code;
- which workflows (tools with real historical usage) would break;
- which refusal codes would be generated, and how the impact distributes;
- whether the rollout is `safe`, `safe_with_warnings`, or `blocked`.

```
unlimited-skills mcp profiles replay-audit \
  [--audit-log FILE] [--profiles FILE] [--bundle FILE] \
  [--trusted-keys FILE | --trust-store DIR] [--audience-id ID]... \
  [--profile NAME] [--config GATEWAY_CONFIG] [--json]
```

`--audit-log` defaults to `<root>/.learning/mcp-audit.jsonl`. Exit codes:
0 for `safe` / `safe_with_warnings`, 1 for `blocked` or a missing log.

## Read-only by construction

The simulator never executes a tool, never spawns an upstream (no
subprocess use at all), never activates a profile, never writes an audit
row, never changes runtime state, and uses no network and no telemetry.
The proposed policy is resolved with the REAL machinery in dry-run --
`resolve_bundle_state` (E14 verification, including the E15 managed-store
default) and `resolve_profile_state` (E10 loading) run unchanged, mirroring
the gateway's own startup dispatch and the E16 rollout simulator -- never a
reimplementation. Historical refusal classification reuses the E11
inspector's readers and refusal-code tables.

## Event classification

Each audit row is classified as exactly one of:

- `tools_search` / `tools_schema` / `tools_call` -- gateway meta-tool calls;
- `skills` -- `skills_search` / `skills_view` / `skills_use` rows (not
  profile-gated, counted by class only);
- `other` -- any other tool name (counted, never replayed);
- `profile_loaded` -- lifecycle events, reported separately;
- malformed lines -- counted and skipped by the shared reader.

The historical outcome of a call row is `ok`, `profile_denied` (refusal
code in the policy family `-32011`..`-32019`), or `upstream_refusal`
(anything else: timeouts, protocol errors, spawn failures, unknown codes).

**Replayable events** are `tools_schema` and `tools_call` rows that carry a
fully qualified tool identity (the redacted `args.tool` field, written at
audit level `standard`). Rows lacking a tool identity (audit level
`minimal` drops the args shape) are COUNTED under
`events.missing_tool_identity`, never guessed.

## Impact computation

For each replayable call the proposed policy is evaluated in the gateway's
own per-request order: fail-closed profile state first, then visibility
(existence-neutral `-32011`, both call types), then callability (`-32012`,
`tools_call` only), then -- when `--config` is given -- the upstream trust
gates (`-32005` disabled, `-32010` future-remote-placeholder, plus
`upstream_not_configured` for upstreams the config does not know). The
evaluator only ever sees fully qualified tool names, never call arguments.

**The comparison axis is policy admission.** A historical call counts as
historically allowed when it succeeded OR was refused for a non-policy
runtime reason (the call had passed policy); it counts as historically
denied only when its refusal code is in the policy family. Replay predicts
policy, never runtime weather. Each replayed call lands in exactly one of:

- `unchanged_allowed` -- passed then, would pass now;
- `newly_denied` -- passed then, would be refused now (with the would-be
  code, e.g. `tool_not_visible (-32011)`);
- `newly_allowed` -- policy-denied then, would pass now;
- `unchanged_denied` -- policy-denied then, still denied.

Breakdowns repeat the same counters by tool, upstream, profile (the
historical row's profile field), would-be refusal code, UTC hour time
bucket derived from `ts` (`YYYY-MM-DDTHH:00Z`), and call type.

## Detections

Each detectable condition is a distinct finding with a severity
(`problem` / `warning`), the same shape as the E16 doctor:

- `policy_hides_used_tool` (problem) -- the proposed policy hides a tool
  with successful historical calls;
- `tool_view_only_but_called` (problem) -- a tool with successful
  historical `tools_call` rows would become visible-but-not-callable;
- `bundle_verification_failure` (problem) -- the proposed bundle fails E14
  verification, with the exact would-be code and failing step;
- `revoked_issuer` (problem) -- the bundle's signing key or the bundle
  itself is revoked (`bundle_revoked`, `-32017`);
- `namespace_mismatch` (problem) -- a profile rule is outside the issuer's
  `allowed_upstream_namespaces` ceiling (`bundle_audience_mismatch`,
  `-32018`, step `namespace_ceiling`);
- `policy_fail_closed` (problem) -- any fail-closed proposed state;
- `input_error` / `gateway_config_invalid` (problem) -- inputs the gateway
  would refuse at startup;
- `missing_tool_identity`, `malformed_rows`, `nothing_to_replay`
  (warnings).

## Recommendation and thresholds

- `blocked` -- the proposed policy itself fails closed (bundle verification
  failure, invalid profile file, signed-required refusal), an input the
  gateway would refuse at startup is present, OR more than **20%**
  (`BLOCK_BREAKAGE_RATIO = 0.20` in
  `unlimited_skills/mcp/audit_replay.py`) of the replayed historical calls
  become newly denied;
- `safe_with_warnings` -- anything became newly denied (at or under the
  threshold) or any finding fired;
- `safe` -- no replayed call changes outcome and no finding fired.

## JSON report document

One document per run (`schemas/mcp-audit-replay-report.schema.json`, draft
2020-12, `additionalProperties: false`): `report_type:
"mcp-audit-replay-report"`, `schema_version: 1`, `generated_at` (the only
wall-clock field; comparisons ignore it -- the rest of the document is
deterministic for the same inputs), plus `inputs`, `log`, `policy`,
`verification`, `events`, `impact`, `breakdowns`, `findings`, and
`recommendation`. Generated example:
`examples/mcp/audit-replay-report.example.json`.

## Privacy

The report contains tool names, upstream names, profile names, counts,
refusal codes, timestamps/buckets, and documented non-sensitive hashes
(bundle SHA-256) ONLY. It never contains argument values, results, error
text copied from audit rows, prompts, tokens, proofs, signature values,
key material, or local filesystem paths -- file inputs are reported as
basenames, and the test suite re-scans every string in the report with the
audit writer's own `looks_secret` / path heuristics.

Implementation: pure functions in `unlimited_skills/mcp/audit_replay.py`;
tests in `tests/test_mcp_audit_replay.py`. MCP v1 schemas are alpha and may
break before v0.6.

See also: [mcp-audit-inspector.md](mcp-audit-inspector.md),
[mcp-profile-rollout.md](mcp-profile-rollout.md),
[mcp-permissioned-tool-profiles.md](mcp-permissioned-tool-profiles.md),
[mcp-signed-profile-bundles.md](mcp-signed-profile-bundles.md),
[mcp-trust-store.md](mcp-trust-store.md).
