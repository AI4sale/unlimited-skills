# v0.6.4 Money Saved Meter — Acceptance Gates & Test Matrix (O064-04)

**Roadmap ref:** `...#v0.6.4`. **Status:** planning/design (no code).
**Purpose:** a release-ready matrix Codex can turn into tests for the v0.6.4
implementation. Grounded on `mcp/savings.py`, `roi_receipt.py`,
`search_core.py:record_router_call`. Estimate honesty per O064-01 §7; privacy per
O064-02.

## Test matrix

| # | Test | Fixture / setup | Expected output | Failure mode caught |
| --- | --- | --- | --- | --- |
| T1 | Empty metrics state | no router calls / no meter file | nudge suppressed; "no data yet" on explicit query; exit 0 | crash/garbage on empty |
| T2 | First-call state | 1 router call | no premature nudge before threshold; counter increments | nudge fires too early |
| T3 | 100-call threshold | calls cross window N | exactly one nudge at the boundary; window resets | duplicate/missed nudge |
| T4 | Bytes-saved accounting | known schema sizes + gateway standing cost | `schema_bytes_avoided` == measured (matches `mcp savings`) | drift vs pull surface |
| T5 | Token estimate | bytes fixture | `est_tokens_avoided == bytes // 4`, labeled "estimated" | exact-count overclaim |
| T6 | Dollars disabled (default) | no local rate | no `$` figure; "dollar estimate unavailable" | implied market price |
| T7 | Dollars enabled | explicit `--price-per-1k-tokens` | "≈ $Z (estimated, your rate)" | false precision / default rate |
| T8 | Local-only storage | run meter | state only under `<root>/.learning/`; no network call | hidden upload |
| T9 | Privacy redaction (`assert_meter_safe`) | planted needles (path, `sk_`/`ghp_` token, `BEGIN PRIVATE KEY`, fake prompt) | each raises; nudge suppressed | leak in passive surface |
| T10 | No server names in push nudge | 2 named servers | push payload has aggregates only | server-name leak |
| T11 | CLI text output | normal window | one/two-line nudge, opt-out honored | nudge blocks/garbles command |
| T12 | JSON output | `--json` | safe fields + `privacy` all-false block | schema drift |
| T13 | Backward compat: `mcp savings` | run pull surface | unchanged output/contract | regression of existing surface |
| T14 | Backward compat: ROI receipt | run receipt | unchanged | regression |
| T15 | Docs examples synthetic | docs build/grep | no real paths/servers/dollars-as-fact | doc leak / overclaim |
| T16 | Frozen-contract / boundary verifiers | run v0.6 verifiers | green | contract regression |

## Required-to-ship vs nice-to-have

- **Required for v0.6.4 ship:** T1–T6, T8, T9, T10, T11, T12, T13, T14, T16.
- **Nice-to-have:** T7 (dollars-on), T15 doc-grep automation (manual review
  acceptable for alpha).

## Acceptance gates

1. All required tests green on refreshed main.
2. Push nudge proven aggregate-only + suppressible (T9/T10/T11).
3. No regression to `mcp savings` / ROI receipt (T13/T14).
4. No telemetry/upload/billing; dollars off by default (T6/T8).
5. Docs make estimate-vs-measured explicit (T5/T15).
6. v0.6 frozen-contract + boundary verifiers pass (T16).

## Non-goals

No feature implementation here; no version bump; no release. v0.6.4 coding is
blocked until the v0.6.3 US-063-005 release decision closes (Hermes).

---

### Evidence summary (for the task)

- **File:** `docs/product/v0.6.4/money-saved-meter-acceptance-matrix.md`
- **16 tests** with fixture, expected output, failure mode; required set named.
- **Acceptance gates** + backward-compat with `mcp savings` / ROI receipt.
