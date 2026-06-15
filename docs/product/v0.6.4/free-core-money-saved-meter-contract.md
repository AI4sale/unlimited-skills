# O064-08 — Free Core Money Saved Meter: Build Contract

**Roadmap ref:** `...#v0.6.4`. **Tier:** Free / Community Core. **Status:** build
contract (no code). **Blocked:** implementation until **US-063-005 GO**.
**Grounding:** `mcp/savings.py` (`build_savings_report`), `roi_receipt.py`,
`search_core.py:record_router_call`, `audit_inspector.py:summary.total_calls`,
v0.6.3 privacy gates. Claim boundary per #180 + O064-07.

## Valuable Final Product
A build-ready Free Core contract for the **local** Money Saved Meter: the one live,
fully-shipping surface of v0.6.4. Free Core gets the live meter; paid tiers
(O064-09..12) get bounded local exports only.

## 1. Behaviour (live in Free Core)
- **Push nudge:** one or two lines appended after an existing local surface once a
  cadence threshold is met. Example: `Last ~100 gateway calls: ~X schema bytes / ~Y
  estimated tokens of standing MCP context avoided (local estimate).`
- **Pull surfaces unchanged:** `mcp savings` and ROI receipt remain the detailed
  views; the meter does not alter their output.
- **`--json`:** emits the same safe aggregate fields + a `privacy` block.

## 2. Cadence contract
- The window is the **gateway-call** count from `audit_inspector.py:summary.
  total_calls` — NOT `record_router_call` (skill-router probes, a different
  denominator).
- Default threshold: **100 gateway calls**, locally tunable.
- Exactly **one** nudge at the boundary; window then resets. No premature nudge.
- The window is a **cadence / usage window**, NOT a per-call billing multiplier.

## 3. Measurement contract
| Quantity | Class | Rule |
| --- | --- | --- |
| `schema_bytes_avoided` | **measured** | from `mcp/savings.py` (`savings_bytes`) |
| `est_tokens_avoided` | **estimated** | `bytes // 4`; always labeled "estimated" |
| `gateway_standing_bytes` | measured | local |
| `calls_in_window` | exact int | gateway-call count |
| `est_dollars` | **off by default** | only with explicit local `--price-per-1k-tokens`; render "~ $Z (estimated, your rate)" |

## 4. Privacy contract (fail-closed)
- Reuse v0.6.3 pattern: an `assert_meter_safe`-style gate runs **before** any
  write/emit. On any forbidden field or a server name in the passive nudge →
  **suppress** the nudge (never partial-redact), fall back to "run `mcp savings`".
- Push nudge is **aggregate-only**: no server names, no paths, no prompts, no skill
  bodies, no tokens/keys. (Server names are allowed only in the pull `mcp savings`.)
- Local state file: `<root>/.learning/savings-meter.json`, safe aggregates + last
  window bucket only; passes the safety assertion before write.

## 5. Local-only / no-egress
No network, no telemetry, no upload, no account. The meter is a local aggregate over
local counters.

## 6. Backward compatibility
- `mcp savings` and ROI receipt output **frozen** (golden tests).
- `router-metrics.json` shape unchanged; the meter only **reads** counters and writes
  its own state file.

## 7. Opt-out / non-blocking
- One env/flag opt-out for the push nudge; the nudge never blocks or garbles a
  command; `--json` consumers unaffected when opted out.

## 8. Acceptance (maps to O064-01 matrix)
T1 empty, T2 first-call, T3 boundary/reset, T4 bytes match `mcp savings`, T5 token
estimate, T6 dollars-off-default, T8 local-only storage, T9 `assert_meter_safe`,
T10 no server names in push, T11 CLI non-blocking, T12 JSON, T13/T14 backward compat,
T16 frozen-contract verifiers.

## 9. Explicitly NOT in Free Core
No export file (that is Registered+), no team/admin aggregation, no hosted anything,
no automatic dollars, no version bump until release.

---

### Evidence summary
- **VFP:** live local Free Core meter (the only fully-shipping v0.6.4 surface).
- **Cadence:** gateway calls (audit `total_calls`), default 100, one nudge/reset.
- **Honesty:** bytes measured, tokens estimated, dollars off-by-default.
- **Fail-closed:** suppress on any unsafe field; aggregate-only push.
