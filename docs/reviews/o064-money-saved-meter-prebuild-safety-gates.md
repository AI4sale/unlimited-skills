# O064-13 — Money Saved Meter: Pre-Build Privacy & Safety Gate Spec

**Roadmap ref:** `...#v0.6.4`. **Status:** release-blocking gate spec (no code).
**Blocked:** build until **US-063-005 GO**. **Purpose:** a spec Codex converts
directly into tests. Closes the two HIGH risks from O064-06 (**R2** exact-token/
dollar overclaim, **R3** passive-surface privacy leak). Reuses v0.6.3 gates
(`search_core.py:event_safe_payload`, `feedback.py:assert_feedback_report_safe`,
`learning_loop.py:assert_privacy_safe`).

## Release-blocking rule
The Money Saved Meter MUST NOT ship unless **every** gate below passes. Any failure is
a **release blocker**, not a warning. Default posture is **suppress, don't redact**.

## Gate A — `assert_meter_safe` (fail-closed payload gate)
Runs before every meter write/emit (push nudge, state file, `--json`, tier exports).

**Forbidden in any meter payload (each must raise):**
- absolute/local paths
- secrets/tokens/keys (`sk_...`, `ghp_...`, `BEGIN PRIVATE KEY`, env values)
- raw prompts / task text / query text
- skill bodies / MCP schema **contents** (only byte sizes allowed)
- install id / machine id / OS user / email
- server names **in a passive/push payload** (allowed only in pull `mcp savings`)

**Required test (planted needles):** fixture with `/home/user/secret`, `sk_live_x`,
`ghp_x`, `-----BEGIN PRIVATE KEY-----`, a fake prompt, a real-looking server name in a
push payload → **each raises**; on raise the nudge/export is **suppressed**.

## Gate B — Overclaim guard (closes R2)
- `est_tokens_*` MUST be labeled "estimated"; never presented as an exact count.
- `schema_bytes_*` may be labeled "measured".
- `est_dollars` is **off by default**; ON only with explicit local
  `--price-per-1k-tokens`, rendered "~ $Z (estimated, your rate)" — never a default
  market price.
- The cadence window MUST NOT be multiplied into a "saved over N calls" billing
  figure.
- **Required tests:** token-label test; dollars-off-by-default test; dollars-on
  requires explicit rate; no "x window" math in output.

## Gate C — Passive-surface aggregation (closes R3)
- The **push nudge** payload is aggregate-only: no server names, no per-item detail.
- **Required tests:** with 2+ named servers configured, the push payload contains
  aggregates only (no server name string); state-file privacy-grep is clean.

## Gate D — Suppress-don't-redact behavior
- On any doubt (a forbidden field would appear, or a safe payload cannot be
  guaranteed), the surface **suppresses** the line and falls back to "run `mcp
  savings` for details". It MUST NOT emit a partially-redacted line.
- **Required test:** inject one unsafe field → output is fully suppressed, not
  masked.

## Gate E — No-egress / local-only
- No network call, no telemetry, no upload from any meter surface or tier export.
- **Required test:** run all meter surfaces with network asserted blocked → no
  outbound attempt; `privacy` JSON block all-false.

## Pass/fail examples
- **PASS:** `Last ~100 gateway calls: ~12,800 measured schema bytes / ~3,200
  estimated tokens of standing MCP context avoided (local estimate).`
- **FAIL (suppressed):** payload would include `server="acme-internal-mcp"` in a push
  nudge → gate C raises → nudge suppressed.
- **FAIL (suppressed):** `est_dollars` present with no local rate → gate B raises.
- **FAIL (suppressed):** `path=/home/uK/.config/...` in state file → gate A raises.

## Required test names (suggested)
`test_assert_meter_safe_planted_needles`, `test_meter_tokens_labeled_estimated`,
`test_meter_dollars_off_by_default`, `test_meter_dollars_on_requires_local_rate`,
`test_meter_no_per_window_billing_math`, `test_push_nudge_aggregate_only_no_servers`,
`test_meter_state_file_privacy_grep`, `test_meter_suppress_not_redact`,
`test_meter_no_network_egress`, `test_meter_json_privacy_block_all_false`.

## Verdict rules (release gate)
- **GREEN to ship:** Gates A–E all pass.
- **BLOCK:** any single gate fails → v0.6.4 does not ship; fix and re-run.
- These gates are **in addition to** the v0.6 frozen-contract + boundary verifiers
  (which must also stay green).

---

### Evidence summary
- **5 release-blocking gates** (A safe-payload, B overclaim, C passive-aggregation,
  D suppress-don't-redact, E no-egress) closing R2 + R3.
- **10 named tests** + pass/fail examples for direct Codex conversion.
- **Default posture:** suppress, don't redact. Any gate fail = release blocker.
