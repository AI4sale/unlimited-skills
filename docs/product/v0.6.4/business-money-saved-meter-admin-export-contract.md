# O064-11 — Business-tier Money Saved Meter: Admin Export Contract

**Roadmap ref:** `...#v0.6.4`. **Tier:** Business. **Status:** build contract (no
code). **Blocked:** until **US-063-005 GO**. **Builds on:** Team summary (O064-10).

## Valuable Final Product
A Business-tier contract for an **admin-readable local savings/backlog export**:
per-team / per-agent aggregate savings that lets ops quantify where the gateway helps
most — **import-ready for a future dashboard**, but in v0.6.4 strictly a **local
file**, not a live hosted feature.

## 1. What Business adds (and only this)
- A **local admin export** (JSON/YAML) aggregating savings across teams/agent
  **classes**, plus a simple "where the gateway helps most" prioritization derived
  from the aggregates.
- The file is **import-ready** for a *future* Business dashboard — it is **not**
  uploaded, and no dashboard/hosted audit exists in v0.6.4.

## 2. Local export vs future hosted (the Business boundary)
| Aspect | v0.6.4 (live) | Future (NOT in v0.6.4) |
| --- | --- | --- |
| Admin savings export | **local file** | hosted dashboard import |
| Prioritization view | local, from aggregates | live org analytics |
| Audit log | none | hosted audit log |
| Billing/entitlement | none | metered billing |

## 3. Exact vs estimated fields (kept separate)
- **Measured (exact):** `schema_bytes_avoided` per team/agent-class, gateway call
  counts.
- **Estimated:** `est_tokens_avoided` (`bytes // 4`), any `est_dollars` (off by
  default, local rate only).
- The export renders these in **separate, clearly-labeled** groups so an importer
  never treats an estimate as a measured fact.

## 4. Privacy contract (fail-closed)
- Aggregates over **workflow/agent classes**, NOT raw tasks; **no client
  identities**, no prompts, no paths, no server names, no tokens/keys.
- `assert_meter_safe` before write; suppress/abort on any unsafe field. No hosted
  audit log is produced.

## 5. Claim boundary
- Allowed: "local export a future dashboard could import."
- Forbidden: "Business dashboard", "hosted audit log", "entitlement", "billing", any
  live/hosted/metered framing; exact-dollar/exact-token claims.

## 6. Backward compatibility
- Additive; reads Team/Registered aggregates; changes nothing in existing surfaces.

## 7. Acceptance
- Export validates against documented schema; exact vs estimated fields in separate
  labeled groups.
- Privacy: agent **classes** only, no client identity, no raw task (grep test).
- No hosted-audit / billing / entitlement surface exists.
- Dollars off by default.

## 8. Explicitly NOT in Business (v0.6.4)
No Business dashboard, no hosted audit log, no entitlement enforcement, no billing,
no telemetry, no automatic dollars.

---

### Evidence summary
- **VFP:** local admin savings/backlog export, import-ready for a *future* dashboard.
- **Exact vs estimated** kept in separate labeled groups.
- **Privacy:** agent/workflow classes, no client identity; fail-closed gate.
- **Claim:** "local export a future dashboard could import."
