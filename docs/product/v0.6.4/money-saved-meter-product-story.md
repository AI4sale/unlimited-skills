# v0.6.4 Money Saved Meter — Product Story & Claim Boundary (O064-01)

**Roadmap ref:** `docs/roadmaps/unlimited-skills/UNLIMITED-SKILLS-PRIVATE-ROADMAP-v0.6.3-to-v0.6.13.md#v0.6.4`
**Status:** planning/design only. **v0.6.4 feature coding is blocked until the
v0.6.3 US-063-005 release decision is closed** (Hermes). No code here.
**Grounding:** built on existing PULL surfaces — `unlimited_skills/mcp/savings.py`
(`build_savings_report`: `total_bytes`, `total_est_tokens`, `gateway_bytes`,
`savings_bytes`, `savings_pct`; token heuristic `est_tokens = bytes // 4`),
`unlimited_skills/roi_receipt.py`, and `search_core.py:record_router_call`
(`router-metrics.json`: `total_invocations`, `by_day`, `last_call`).

## 1. Primary user story

"As a local Unlimited Skills user, after some real use I want to be shown —
without asking — a short, honest estimate of how much standing context (MCP
schema bytes / estimated tokens) the gateway saved me over my last N calls, so I
can see the tool is paying for itself."

## 2. The pull → push distinction (the actual v0.6.4 delta)

- **Already exists (PULL):** `mcp savings` and the ROI receipt compute savings
  **when the user asks**.
- **v0.6.4 adds (PUSH / periodic):** a value **nudge** surfaced automatically at a
  cadence (e.g. every 100 router calls), e.g.:
  > "Last 100 calls: ~X schema bytes / ~Y estimated tokens of standing MCP context
  > avoided via the gateway (local estimate)."
  The meter is an *aggregator + cadence trigger* over existing measurements, not a
  new measurement engine.

> **Counter reconciliation (vs Codex C064-00 map, `docs/reports/v0.6.4-money-saved-meter-implementation-map.md`):**
> use the **right denominator**. `router-metrics.json` (`record_router_call`)
> counts **skill-router probes**, NOT gateway tool calls. Gateway tool-call
> counts live in the audit report (`mcp audit-report` /
> `audit_inspector.py:summary.total_calls`, `per_tool`, `per_upstream`). For a
> "per-100-calls MCP context saved" nudge the cadence should track **gateway
> calls** (audit `total_calls`), since that is the activity the MCP savings refer
> to; a router-probe cadence is a different (skill-retrieval) denominator. The
> meter joins the latest `mcp savings` numbers to the gateway call count — a join
> the map confirms does not exist yet.

## 3. Exact allowed release claim

> "v0.6.4 adds a local Money Saved Meter: a periodic, privacy-safe estimate of the
> standing MCP/skill context Unlimited Skills avoided loading over your recent
> calls. All numbers are local estimates."

## 4. Forbidden claims

- "Saved you $Z" as a **precise/guaranteed** figure (dollars are optional and must
  be labeled *estimated*, see §7).
- "Saved tokens" as an exact count (the `bytes // 4` heuristic is an estimate).
- Any hosted/telemetry/billing/"we tracked your usage" framing.
- Any per-prompt or per-task savings tied to user content.

## 5. Expected CLI / output UX

- **Push nudge** (one or two lines) appended to an existing local surface (e.g.
  after `suggest`/quickstart, or via the daemon) once a cadence threshold is met.
  Off by an env/flag opt-out; never blocks the command.
- **Pull view** unchanged: `mcp savings` / ROI receipt remain the detailed surface.
- **`--json`** form emits the same aggregate fields machine-readably.

## 6. Local-only / privacy boundary

- Reads only local measurements (MCP schema sizes, gateway standing cost, router
  call counts). No prompts, no task text, no skill bodies, no paths.
- No network, no telemetry, no upload. The meter is a local aggregate over local
  counters. (Detailed field classification → O064-02.)

## 7. Estimation honesty (avoid false precision)

- Tokens are **estimated** (`bytes // 4`); always labeled "estimated tokens".
- Bytes avoided are **measured** (schema byte sizes) — may be labeled "measured".
- Dollars are **off by default**. If enabled, require an explicit local
  `--price-per-1k-tokens` input and render as "≈ $Z (estimated, your rate)";
  never a default/implied market price.
- Fallback when price/estimation is unavailable: show bytes + estimated tokens
  only, and state "dollar estimate unavailable (no local rate set)".

## 8. What counts as user value

The user gets passive, ongoing proof of value (context/tokens avoided) without
running a command — turning a one-time "nice number" into a standing reason to
keep the gateway installed. Ties to PRIORITY-#1 (adoption/sales proof) as a
local, honest ROI signal.

## 9. Explicitly NOT in v0.6.4

No hosted dashboard, no telemetry, no billing, no entitlement, no per-tier live
paid features, no automatic dollar claims, no remote aggregation.

---

### Evidence summary (for the task)

- **File:** `docs/product/v0.6.4/money-saved-meter-product-story.md`
- **Allowed claim:** §3. **Forbidden claims:** §4.
- **Estimate labeling:** §7 — bytes measured, tokens estimated, dollars
  off-by-default and approximate-only.
- **Reusable surfaces:** `mcp/savings.py`, `roi_receipt.py`, `record_router_call`.
- **Blocked:** v0.6.4 implementation until v0.6.3 US-063-005 closes.
