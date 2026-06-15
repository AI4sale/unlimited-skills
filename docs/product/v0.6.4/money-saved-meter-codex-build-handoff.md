# O064-14 — Money Saved Meter: Codex Build Handoff

**Roadmap ref:** `...#v0.6.4`. **Status:** build briefing (no code). **Audience:**
Codex. **Purpose:** a single Codex-ready briefing that aggregates every O064 output so
the build can start the moment **US-063-005 GO** lands — with no guesswork.

## 0. Start condition (HARD gate)
Do **not** start coding until **US-063-005** (v0.6.3 release decision) is **GO**.
Until then this is planning only: no implementation, no version bump, no tag, no
release.

## 1. Inputs (authoritative)
| Source | Role |
| --- | --- |
| #178 — `docs/reports/v0.6.4-money-saved-meter-implementation-map.md` | code map: existing ROI/savings/router/audit surfaces |
| #179 — `money-saved-meter-{product-story,acceptance-matrix,tier-bonuses}.md`, `o064-02-...-privacy-design.md` | planning batch |
| #180 — claim scrub | MCP-schema (not skill) context; 100-call = cadence not billing |
| #181 — O064-05/06/07 | readiness (PASS_WITH_FIXES), risks (R2/R3 HIGH), claim authorization |
| O064-08..12 | per-tier build contracts (Free live; Registered/Team/Business/Enterprise bounded local) |
| O064-13 | release-blocking privacy/safety gate spec (Gates A–E) |

## 2. Implementation objective
Add a **local Money Saved Meter**: a periodic push nudge (and `--json`) that surfaces,
once per cadence window, the standing **MCP schema** context the gateway avoided —
**measured bytes**, **estimated tokens** (`bytes // 4`), dollars off by default. The
**one new primitive** is a join of the **gateway-call count**
(`audit_inspector.py:summary.total_calls`) to the latest `mcp savings` numbers behind a
cadence trigger; everything else reuses existing pull surfaces.

## 3. Strict non-goals
No hosted dashboard, no telemetry, no upload, no billing, no entitlement, no automatic
dollars, no per-prompt/per-task savings, no remote aggregation, no signed-artifact
claim. Do not change `mcp savings` / ROI-receipt output or `router-metrics.json` shape.

## 4. Free Core build scope (the live surface) — O064-08
- Cadence: gateway calls, default **100**, one nudge at boundary + reset, locally
  tunable; window = cadence, not billing.
- Push nudge appended after an existing surface; opt-out flag; never blocks a command.
- State file `<root>/.learning/savings-meter.json`: safe aggregates + last window
  bucket; passes the safety gate before write.
- `--json`: safe fields + `privacy` all-false block.

## 5. Tier export boundaries (bounded local, NOT live hosted)
- **Registered (O064-09):** one local schema-versioned export; **no submit verb**.
- **Team (O064-10):** local aggregate summary, member-local aliases; manual share; no
  dashboard/sync.
- **Business (O064-11):** local admin export, agent **classes** not raw tasks;
  exact-vs-estimated in separate labeled groups; import-ready for a *future* dashboard.
- **Enterprise (O064-12):** local audit-safe evidence pack + method statement; SHA256
  wording only, signature `not-claimed`; no SSO/SCIM/license/portal/billing.

## 6. Privacy / safety gates (release-blocking) — O064-13
Implement `assert_meter_safe` and Gates A–E. Default posture **suppress, don't
redact**. Required tests listed in O064-13 (`test_assert_meter_safe_planted_needles`,
`test_push_nudge_aggregate_only_no_servers`, `test_meter_suppress_not_redact`, ...). Any
gate fail = release blocker.

## 7. Test matrix (from O064-01 acceptance + O064-13)
Required to ship: T1–T6, T8–T14, T16 (acceptance matrix) **plus** Gates A–E.
Nice-to-have: T7 (dollars-on), T15 doc-grep automation.

## 8. Claim boundary (public) — O064-07 / #180
Allowed: "a local periodic estimate of MCP schema context avoided — measured bytes,
estimated tokens, optional user-supplied dollar estimate; local-only." Forbidden:
exact money, exact tokens, skill-body savings, summed per-window billing, telemetry/
hosted/upload, server names in passive surfaces (X1–X8).

## 9. Suggested Codex task split
1. **Build C1 — meter core:** gateway-call ↔ savings join + cadence trigger + state
   file (Free behaviour) behind `assert_meter_safe`.
2. **Build C2 — surfaces:** push nudge (opt-out, non-blocking) + `--json` + privacy
   block.
3. **Build C3 — safety gates + tests:** Gates A–E and named tests; frozen-contract +
   boundary verifiers stay green.
4. **Build C4 — tier exports:** Registered/Team/Business/Enterprise bounded local
   artifacts per their contracts.
5. **Build C5 — docs/release:** wire allowed claim + per-tier release-note-safe lines;
   T15 docs-grep.

## 10. Release blockers (must all be true to ship)
- US-063-005 = GO.
- Gates A–E green; acceptance required-set green; v0.6 frozen-contract + boundary
  verifiers green.
- `mcp savings` / ROI receipt unchanged (T13/T14).
- No telemetry/upload/billing; dollars off by default.
- Public claims within O064-07 / #180 boundary.

---

### Evidence summary
- **One briefing** aggregating #178/#179/#180/#181 + O064-08..13.
- **One new primitive:** gateway-call ↔ savings join behind a cadence trigger.
- **5-step Codex build split** (C1 core → C5 docs), all behind US-063-005 GO.
- **Release gated** on Gates A–E + acceptance + frozen-contract verifiers.
