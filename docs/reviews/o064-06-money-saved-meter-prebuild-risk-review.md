# O064-06 — Money Saved Meter: Pre-Build Risk Review

**Roadmap ref:** `...#v0.6.4`. **Status:** planning review (no code). **Reviewer:** Opus.
**Scope:** the six build risks named for the v0.6.4 Money Saved Meter, each with a
concrete trigger, a mitigation grounded in existing code, and an acceptance hook.
Grounded on `mcp/savings.py`, `roi_receipt.py`, `search_core.py`,
`audit_inspector.py`, and the v0.6.3 privacy gates.

## Risk register

### R1 — Noisy / annoying push nudge — **MEDIUM**
- **Trigger:** the nudge fires too often, mid-command, or repeats the same window,
  training users to ignore it (or uninstall).
- **Mitigation:** cadence is a single fire at the window boundary with reset
  (acceptance T3); nudge appended *after* an existing surface, never interrupting
  (T11); one opt-out env/flag; suppress when there is nothing new to say (empty
  state T1). Default cadence conservative (>=100 gateway calls), tunable locally.
- **Acceptance hook:** T1, T2, T3, T11.

### R2 — Exact-token / exact-dollar overclaim — **HIGH**
- **Trigger:** the meter presents `bytes // 4` as a precise token count, or renders
  a default market dollar price, making a legally/ethically unsafe savings claim.
- **Mitigation:** tokens always labeled "estimated"; bytes "measured"; dollars
  **off by default**, on only with an explicit local `--price-per-1k-tokens`, and
  rendered "~ $Z (estimated, your rate)". The 100-call window is cadence, not a
  per-call billing multiplier (#180 wording). Forbidden-claims list in O064-01 §4
  and O064-07.
- **Acceptance hook:** T5, T6, T7; O064-07 forbidden-claims grep.

### R3 — Privacy leak in a passive surface — **HIGH**
- **Trigger:** a nudge that fires *without the user asking* leaks a private server
  name, a path, a token, or prompt text into a log/state file/stdout.
- **Mitigation:** `assert_meter_safe` fail-closed gate (O064-02) with planted
  needles (path, `sk_`/`ghp_` token, `BEGIN PRIVATE KEY`, fake prompt) — all must
  raise and **suppress** the nudge (never partial-redact); push payload aggregates
  only, **no server names** (server names allowed only in the pull `mcp savings`,
  not the passive push). Reuse v0.6.3 `event_safe_payload` / `FORBIDDEN_TEXT_RE`.
- **Acceptance hook:** T8, T9, T10; meter-state privacy-grep.

### R4 — Schema / counter drift — **MEDIUM**
- **Trigger:** the meter joins the **wrong denominator** — `record_router_call`
  (skill-router *probes*) instead of gateway `total_calls` (audit report) — so the
  "per-100-calls saved" number describes a different activity than the savings.
- **Mitigation:** cadence tracks **gateway calls** (`audit_inspector.py:summary.
  total_calls`); the meter joins that count to the latest `mcp savings` numbers
  (the join the C064-00 map confirms does not exist yet). Document the denominator
  in the JSON schema; pin field names.
- **Acceptance hook:** T4 (bytes match `mcp savings`), T12 (JSON schema), T16
  (frozen-contract verifiers).

### R5 — Backward-compatibility regression — **MEDIUM**
- **Trigger:** adding the meter changes `mcp savings` or ROI-receipt output, or
  mutates `router-metrics.json` shape, breaking existing pull consumers.
- **Mitigation:** the meter is **additive** — it reads existing surfaces, writes
  only its own `<root>/.learning/savings-meter.json`. Freeze the two pull surfaces
  with golden-output tests; run v0.6 frozen-contract + boundary verifiers.
- **Acceptance hook:** T13, T14, T16.

### R6 — JSON / stdout contract risk — **MEDIUM**
- **Trigger:** `--json` emits an unstable shape, or stdout interleaves the nudge
  with machine-readable output, breaking scripts.
- **Mitigation:** `--json` emits a fixed safe-field set plus an explicit `privacy`
  block with all-false upload/telemetry flags; the human push nudge never writes to
  the `--json` stream; opt-out honored in both. Version the JSON schema.
- **Acceptance hook:** T11, T12.

## Cross-cutting

- **Fail-closed beats best-effort:** on any doubt the meter **suppresses** the nudge
  and points to `mcp savings` for detail — never emits a partially-redacted line.
- **Estimate honesty is a first-class invariant**, not a footnote (R2 + #180).
- **One new primitive only:** the gateway-call to savings join behind a cadence
  trigger. Keeping the blast radius this small is itself the strongest risk control.

## Overall: **PROCEED (build-ready) with R2/R3 as gating, fail-closed**

No HIGH risk is unmitigated by an existing pattern. R2 (overclaim) and R3 (passive
leak) must be enforced as **ship gates**; R1/R4/R5/R6 are covered by the acceptance
matrix. Build remains blocked until US-063-005.

---

### Evidence summary
- **6 risks** with trigger + mitigation + acceptance hook.
- **HIGH:** R2 overclaim, R3 passive-leak — both fail-closed ship gates.
- **Smallest blast radius:** one new join; everything else reuses pull surfaces.
