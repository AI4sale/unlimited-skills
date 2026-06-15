# O064-05 — Money Saved Meter: Implementation-Readiness Review of #179

**Roadmap ref:** `docs/roadmaps/unlimited-skills/UNLIMITED-SKILLS-PRIVATE-ROADMAP-v0.6.3-to-v0.6.13.md#v0.6.4`
**Status:** planning review (no code). **Reviewer:** Opus.
**Subject:** the v0.6.4 planning batch merged as #179
(`money-saved-meter-product-story.md`, `-acceptance-matrix.md`, `-tier-bonuses.md`,
`o064-02-...-privacy-design.md`), cross-checked against the Codex code map
`docs/reports/v0.6.4-money-saved-meter-implementation-map.md` (#178).

## Verdict: **PASS_WITH_FIXES**

The plan is implementation-ready. Two required fixes were the exact items Hermes
flagged pre-merge; #179 merged before they landed, so they are carried as a
post-merge follow-up (#180). With #180 in, this review is **PASS**.

## Required fixes (status)

| # | Fix | Why it blocks a clean build | Status |
| --- | --- | --- | --- |
| F1 | Allowed claim must not say "skill/skill-body context" — only MCP **schema** context + tracked surfaces (`mcp savings`, ROI receipt, router metrics) | Skill-body savings are **not measured**; the build could otherwise be coded/tested against a number that has no accounting source | Landed in **#180** |
| F2 | Docs must state the 100-call window is a **cadence/usage window**, not a per-call exact-billing claim | Prevents the build from multiplying one standing-context measurement into a fake "exact tokens saved over 100 calls" figure | Landed in **#180** |

## Checked items (the two Hermes asked for)

### 1. 100-call cadence semantics — **OK (post-#180)**
- The window is a **trigger cadence**, not an accounting multiplier. The nudge
  reports the *current standing* context cost avoided (from `mcp savings`), surfaced
  once per N calls — it does **not** sum a per-call delta across 100 calls.
- Acceptance matrix T3 (exactly one nudge at the boundary; window resets) and T2
  (no premature nudge) correctly encode cadence-as-trigger. T5 keeps tokens as
  `bytes // 4` estimated. No "× 100" math anywhere. **Consistent.**

### 2. MCP-vs-skill savings wording — **OK (post-#180)**
- Savings are bounded to surfaces with real accounting: MCP **schema** byte sizes
  (`mcp/savings.py`), ROI receipt, router metrics. Skill-body context is explicitly
  out. The §3 claim and the new claim-boundary note now match the code map.

## Additional readiness checks (beyond the two)

- **Right denominator.** Product story §2 already reconciles the C064-00 map:
  the per-100-calls nudge must track **gateway calls** (audit-report
  `total_calls`), since `record_router_call` counts skill-router *probes*, a
  different denominator. The "join gateway-call-count to latest `mcp savings`" does
  not exist yet — this is the one genuinely new piece of code to build. **Flagged,
  not a blocker.**
- **Privacy gate present in plan.** O064-02 specifies `assert_meter_safe` fail-closed
  with planted-needle fixtures and nudge-aggregation (no server names). Readiness:
  **yes**, provided the gate is built before the push surface ships.
- **Backward-compat named.** Acceptance T13/T14 freeze `mcp savings` / ROI receipt
  output. **Good** — the meter is additive.
- **Opt-out + non-blocking.** Push nudge must be suppressible and never block a
  command (T11). **Specified.**

## What is NOT ready / explicitly deferred (correct)
- No implementation; v0.6.4 build stays blocked until **US-063-005** closes.
- Dollars off by default; no telemetry/hosted surfaces.

## Recommendation
**PASS_WITH_FIXES → PASS once #180 merges.** No scope change. The single new build
primitive is the gateway-call-count to savings join behind a cadence trigger and an
`assert_meter_safe` gate; everything else reuses existing pull surfaces.

---

### Evidence summary
- **Verdict:** PASS_WITH_FIXES (PASS after #180).
- **Two required fixes** = Hermes pre-merge scrub, both in #180.
- **New code surface:** gateway-call cadence join + `assert_meter_safe`; the rest is reuse.
- **Build gate:** US-063-005 still open.
