# ORI2-PRE-08 — Owner Waiver Decision Brief (US-064-000 Router Inject v2)

**Task:** ORI2-PRE-08 (Opus preflight, unblocked). **Status:** decision brief for the
owner. **Important:** this brief does NOT grant or assume acceptance. It lays out the
state and options so the owner (and only the owner) decides. Opus does not hold
acceptance authority.

## Current state (verified 2026-06-15)

| Item | State | Source |
| --- | --- | --- |
| Registry PR #62 (RI2 roadmap gate) | **MERGED** 2026-06-15 11:24Z | `AI4sale/unlimited-skills-registry#62` |
| ORI2-PRE pack PR #183 (this review series) | **OPEN**, Hermes approved-for-merge | `unlimited-skills#183` |
| US-063-005 (Money Saved Meter readiness) | **NOT accepted** (blocked pending human owner acceptance) | chat / roadmap |
| RI2-01..04 (Router Inject v2 implementation) | **GATED** — cannot start | gate below |
| Money Saved Meter v0.6.4 BUILD | separately blocked, **not** part of this decision | roadmap |

## The gate (Hermes's design)

RI2-01..04 may start **only** when: **#62 merged** (✅ done) **AND** (**US-063-005
accepted** OR **explicit owner waiver for US-064-000 pre-build work**).

So the single remaining blocker is the second clause. Either US-063-005 gets accepted
(unrelated work, the Money Saved Meter readiness), or the owner issues a narrow waiver
that lets Router Inject v2 proceed **without** coupling it to US-063-005.

## Options

**Option A — Strict gate (wait for US-063-005 acceptance).**
RI2 waits until Money Saved Meter readiness is accepted. *Pro:* one linear queue, no
parallel work. *Con:* Router Inject v2 — the fix for the weakened skill-inject the
owner explicitly flagged — is blocked behind an unrelated item; the 100-step gap stays
live in `main` meanwhile.

**Option B — Limited waiver for US-064-000 only (recommended).**
Owner waives the US-063-005 coupling **for Router Inject v2 only**, so RI2-01..04 can
start now against the approved acceptance pack (#183). Money Saved Meter BUILD,
version bump, tag, and publish stay blocked. *Pro:* the inject fix the owner wants
moves immediately; scope is tightly bounded to one roadmap item; the acceptance rubric
and claim boundary are already in place to keep it honest. *Con:* one parallel lane to
track.

**Option C — Full no-go.**
Pause RI2 entirely. *Pro:* zero parallel work. *Con:* leaves the documented inject
weakness unaddressed indefinitely.

## Recommendation

**Option B.** The owner already named the weakened router inject as a real problem;
Router Inject v2 is its fix; #62 is merged and the acceptance criteria (PRE-01..05) are
written and approved. A narrow waiver scoped to US-064-000 unblocks exactly that work
without touching the Money Saved Meter release gates.

## Exact waiver text (for the owner to issue, if chosen)

> "I authorize Router Inject v2 (US-064-000, tasks RI2-01..04) to begin implementation
> now, waiving the US-063-005 acceptance precondition for this item only. Money Saved
> Meter v0.6.4 BUILD, version bump, tag, and publish remain blocked and are not covered
> by this waiver."

## Boundaries this brief respects

- Does not infer or record owner acceptance — the waiver is valid only when the owner
  states it.
- Keeps Router Inject v2 (US-064-000) separate from Money Saved Meter (v0.6.4).
- Does not authorize any release action (no bump/tag/publish).
