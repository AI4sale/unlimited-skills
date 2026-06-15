# O064-12 — Enterprise-tier Money Saved Meter: Local Evidence Pack & Governance Boundary

**Roadmap ref:** `...#v0.6.4`. **Tier:** Enterprise. **Status:** build contract /
governance review (no code). **Blocked:** until **US-063-005 GO**. **Builds on:**
Business admin export (O064-11).

## Valuable Final Product
An Enterprise-tier **audit-safe local evidence pack**: aggregate context-cost avoided
plus an explicit method/assumptions statement, suitable for governance review in
controlled environments — **local-only, policy-compatible, non-telemetry by default,
no auto-action**.

## 1. What Enterprise adds (and only this)
- A **local evidence pack**: the aggregate savings figures + a written
  **method/assumptions statement** (what is measured, what is estimated, the
  `bytes // 4` heuristic, dollars off-by-default), so a governance/compliance
  reviewer can defend the ROI claim with **no data egress**.
- No automatic action, no enforcement, no remote submission.

## 2. Governance boundary (v0.6.4 vs future)
| Capability | v0.6.4 (live) | Future (NOT in v0.6.4) |
| --- | --- | --- |
| ROI evidence | **local evidence pack** | hosted compliance portal |
| Identity | none required | SSO / SCIM |
| Licensing | none | on-prem license server |
| Billing | none | metered/enterprise billing |
| Egress | **none** | governed export pipeline |

## 3. Method/assumptions statement (required content)
- Bytes avoided are **measured** (MCP schema sizes); tokens are **estimated**
  (`bytes // 4`); dollars are **off by default** and, if enabled, use a local rate
  only.
- The 100-call window is a **cadence/usage window**, not per-call billing.
- Aggregates only — no prompts, no paths, no server names, no keys; the pack is a
  governance artifact, not raw telemetry.

## 4. Privacy / audit-safety contract (fail-closed)
- `assert_meter_safe` before write; suppress/abort on any unsafe field.
- Aggregates only; **no prompts/paths/keys/server names**.
- If a hash is used for any identifier, use **SHA256 wording only**, and state
  signature status as **`not-claimed`** (never imply signed/verified artifacts).

## 5. Claim boundary
- Allowed: "local audit-safe savings evidence; **no hosted features**."
- Forbidden: SSO/SCIM/on-prem-license/hosted-compliance/billing claims; any "signed"
  or "verified" evidence claim; exact-dollar/exact-token claims.

## 6. Acceptance
- Evidence pack contains aggregates + method statement; no raw prompts/paths/keys
  (grep test).
- Signature status renders `not-claimed`; no "signed"/"verified" wording.
- No SSO/SCIM/license/billing/hosted surface exists.
- Dollars off by default; estimates labeled.

## 7. Explicitly NOT in Enterprise (v0.6.4)
No SSO/SCIM, no on-prem license server, no hosted compliance portal, no billing, no
telemetry, no auto-action, no signed-artifact claim.

---

### Evidence summary
- **VFP:** local, audit-safe savings evidence pack + method statement; no egress.
- **Governance boundary:** local evidence now; SSO/license/portal explicitly future.
- **Safety:** fail-closed gate; SHA256 wording only; signature `not-claimed`.
- **Claim:** "local audit-safe savings evidence; no hosted features."
