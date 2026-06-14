# v0.6.4 Money Saved Meter — Privacy & Security Design (O064-02)

**Roadmap ref:** `...#v0.6.4`. **Status:** planning/design (no code).
**Inputs:** v0.6.3 privacy patterns (`search_core.py:event_safe_payload`,
`feedback.py:assert_feedback_report_safe`, `learning_loop.py:assert_privacy_safe`)
and existing savings surfaces (`mcp/savings.py`, `roi_receipt.py`).

## Verdict: PASSABLE_DESIGN

The Money Saved Meter can be built privacy-safe by reusing the v0.6.3 fail-closed
pattern, **provided** the field classification below is enforced and a
`assert_meter_safe`-style gate is added with planted-needle fixtures.

## Field classification

| Field | Class | Rule |
| --- | --- | --- |
| `calls_in_window` (e.g. 100) | **safe** | integer count |
| `schema_bytes_avoided` | **safe** | measured aggregate, no content |
| `est_tokens_avoided` | **safe** | derived (`bytes // 4`); label "estimated" |
| `gateway_standing_bytes` | **safe** | local measurement |
| `route_type` / `gateway_type` | **safe** | enum (gateway vs direct), not a path |
| `window_started_bucket` / `ts_bucket` | **safe** | coarse time bucket, not exact ts of a private action |
| `est_dollars` | **conditional** | only if user set a local rate; label "estimated, your rate"; off by default |
| `server_name` | **conditional** | allowed in pull `mcp savings` (already), but the **push nudge** should aggregate, not name servers, to avoid leaking private server names in a passive surface |
| raw prompts / task / query | **unsafe** | never |
| skill bodies / MCP schema contents | **unsafe** | never (only byte sizes) |
| absolute/local paths | **unsafe** | never |
| tokens / keys / secrets / env values | **unsafe** | never |
| install id / machine id | **unsafe** | never embedded |

## Output rules (CLI / JSON / logs / docs)

- **CLI push nudge:** aggregate counts/bytes/estimated-tokens only; no server
  names, no paths. One opt-out env/flag.
- **JSON:** same safe fields; include explicit `privacy` block with all-false
  upload/telemetry flags (mirror `_privacy_flags`).
- **Local meter state file** (e.g. `<root>/.learning/savings-meter.json`):
  stores only safe aggregates + last-window bucket; runs through the safety
  assertion before write.
- **Docs examples:** synthetic numbers only; no real paths/servers.

## Failure behavior (fail-closed)

If the meter cannot guarantee a safe payload (e.g. a server name would appear in a
passive nudge, or a forbidden field is present), **suppress the nudge** and fall
back to "run `mcp savings` for details" — never emit a partially-redacted line.

## Tests Codex must implement

- `assert_meter_safe` fail-closed unit test with planted needles (raw path, `sk_`/
  `ghp_` token, `BEGIN PRIVATE KEY`, a fake prompt) — all must raise.
- Nudge-aggregation test: server names absent from the push payload.
- Dollar-off-by-default test; dollar-on requires explicit local rate.
- Meter state file privacy-grep test.

## Recommendation

**PASSABLE_DESIGN.** Reuse the v0.6.3 fail-closed gate; enforce the table above;
keep dollars off by default; suppress (don't redact) on any doubt. No code changes
made in this design.
