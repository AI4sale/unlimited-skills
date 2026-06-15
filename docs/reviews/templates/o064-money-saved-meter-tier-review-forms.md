# O064-TIER-06 — Money Saved Meter: Paid-Tier PR Review Forms

**Roadmap ref:** `...#v0.6.4`. **Status:** review templates (no code). **Reviewer:** Opus.
**Purpose:** pre-built per-tier checklists so that when Codex opens the tier
*implementation* PRs, the Opus reviewer grades each in minutes against fixed criteria
instead of re-deriving them. Same role the ORI2-PRE-07 forms played for Router Inject v2.

**These forms grade implementation against existing, already-shipped contracts — they
do not re-specify the tiers.** The tier *contracts* shipped in **PR #182** (O064-08..14)
and the Free-core value model in **PR #187** (US-064-001). Each form below maps to its
governing contract; a reviewer reads the contract, then fills the form against the PR.

## Source-of-truth map (read the contract, then grade the PR)

| Form | Tier | Governing contract (already in repo) |
| --- | --- | --- |
| TR-01 | Registered | `docs/product/v0.6.4/registered-money-saved-meter-export-contract.md` (O064-09) |
| TR-02 | Team | `docs/product/v0.6.4/team-money-saved-meter-summary-contract.md` (O064-10) |
| TR-03 | Business | `docs/product/v0.6.4/business-money-saved-meter-admin-export-contract.md` (O064-11) |
| TR-04 | Enterprise | `docs/reviews/enterprise-money-saved-meter-governance-boundary.md` (O064-12) |
| TR-05 | Cross-tier release claim | `docs/product/v0.6.4/money-saved-meter-cross-tier-release-matrix.md` (O064-13) + `docs/reviews/o064-07-money-saved-meter-public-claim-authorization.md` |

Shared references for every form: estimate honesty + claim limits — `money-saved-meter-value-model.md`
(O064-01 §3/§4/§7); privacy design — `docs/reviews/o064-02-money-saved-meter-privacy-design.md`;
acceptance/test gates — `money-saved-meter-acceptance-matrix.md` (O064-04, tests T1–T15).

**Verdict scale (every form):** `PASS` / `PASS_WITH_FIXES` / `BLOCKED`. A single
must-have (M) failure ⇒ `BLOCKED`. Should-have (S) failures downgrade to
`PASS_WITH_FIXES`. Cite `file:line` evidence for each judged item. Opus produces the
verdict only — **Opus does not grant acceptance / does not merge** (Codex is merge
authority).

---

## Cross-cutting checklist (apply to EVERY tier PR before the per-tier form)

**Privacy (fail-closed) — M unless noted**
- [ ] Runs the same `assert_meter_safe` fail-closed gate before writing any artifact;
      on a forbidden field it **aborts/suppresses**, never writes a partially-redacted file.
- [ ] Output carries **aggregates only**: no raw prompts, task text, skill bodies,
      local absolute paths, private-repo paths, server/MCP names, raw MCP schemas/payloads,
      tokens/keys/secrets, OS usernames, emails, or machine/install ids.
- [ ] Any tier label/alias is a **user-supplied local label**, not derived from OS
      identity or registration PII.
- [ ] No network verb introduced: no submit / sync / upload / publish / fetch-over-network.

**Claim boundary — M**
- [ ] No forbidden words present in code comments, CLI strings, docs, or release notes:
      *exact money saved*, *guaranteed bill reduction*, *hosted telemetry*, *live dashboard*,
      *enterprise governance enforced*, *provider reconciliation*.
- [ ] Dollars **disabled by default**; appear only with an explicit local rate and are
      labeled "estimated, your rate".
- [ ] Bytes labeled **measured**; tokens labeled **estimated** (`bytes // 4`); the
      100-call window framed as **local cadence, not billing math**.

**Scope discipline — M**
- [ ] Free-core meter behaviour (PR #187) is **unchanged** — tier work is strictly additive.
- [ ] No hosted backend, dashboard, billing/entitlement, or telemetry added.
- [ ] No release/tag/publish/version-bump in the PR.
- [ ] Does not reopen #119 / E19; touches only the tier's declared surface.
- [ ] Tests green; no unrelated files touched.

---

## Form TR-01 — Registered tier (export profile)

Governing contract: O064-09. The Registered bonus is **one bounded local, schema-versioned
savings export** — produced locally, stays local.

- [ ] **M** Adds a **local export command** writing a schema-versioned file
      (e.g. `savings-export-v1.json`); top-level `schema_version` present.
- [ ] **M** Body = the Free meter's safe aggregates only (`calls_in_window`,
      `schema_bytes_avoided` measured, `est_tokens_avoided = bytes // 4`,
      `gateway_standing_bytes`, coarse `window_*_bucket`).
- [ ] **M** `privacy` block with all upload/telemetry flags **false**; **no** `install_id`
      / machine id embedded (same safe-field set as Free).
- [ ] **M** **No submit/sync/upload verb** exists on the Registered surface (negative test).
- [ ] **S** `tier_context.registered` (if present) is optional and **absent by default**
      when registration data is unavailable; its absence does not error.
- [ ] **M** Backward-compat: does not change `mcp savings`, ROI receipt, or Free meter output.
- [ ] **S** Export validates against the documented `schema_version` shape (T9/T15 analog).
- Acceptance matrix to exercise: registration missing; registration present; export
  generated; privacy scan passes; **Free output byte-identical**.
- **Do NOT approve if:** the export uploads/syncs; embeds machine/install id or any PII;
  changes Free output; or implies a live hosted value view exists now.
- Evidence: __________  Verdict: __________

## Form TR-02 — Team tier (local rollup)

Governing contract: O064-10. The Team bonus is a **local summary that aggregates
member-produced Registered exports**, shared manually over the team's own channel.

- [ ] **M** Inputs are member-produced **O064-09 exports gathered out of band** — the tool
      does **not** fetch them over a network.
- [ ] **M** Output: `team_total_schema_bytes_avoided` (measured),
      `team_total_est_tokens_avoided` (estimated), and `members[]` of
      `{alias, schema_bytes_avoided, est_tokens_avoided}`; `schema_version` present.
- [ ] **M** Aliases are **member-local labels**, not OS usernames/emails/machine ids.
- [ ] **M** Deduplication rule applied for repeated/duplicate receipt imports.
- [ ] **M** Incompatible `schema_version` is **rejected** (not silently coerced).
- [ ] **M** No live sync / admin dashboard / central server / SLA introduced; sharing
      is manual (no upload/publish verb).
- [ ] **S** Missing optional labels handled gracefully (no crash, no PII fallback).
- Acceptance matrix to exercise: one receipt; multiple receipts; duplicate receipt;
  incompatible schema version; missing optional labels; **privacy-unsafe receipt rejected**.
- **Do NOT approve if:** the tool fetches receipts over a network; emits server names/paths;
  aliases leak OS identity; or a duplicate import double-counts.
- Evidence: __________  Verdict: __________

## Form TR-03 — Business tier (admin export)

Governing contract: O064-11. The Business bonus is a **local admin export** (CSV + JSON)
aggregating savings across teams/agent classes — import-ready for a *future* dashboard.

- [ ] **M** Produces a **local** admin export in **both CSV and JSON**; no upload; no
      dashboard/hosted audit exists in v0.6.4.
- [ ] **M** Measured vs estimated kept separate: `schema_bytes_avoided` + gateway call
      counts measured; `est_tokens_avoided` (`bytes // 4`) and any `est_dollars`
      (off by default) clearly estimated.
- [ ] **M** Project/workspace/deployment labels are **admin-supplied locally**, privacy-safe.
- [ ] **S** Savings-by-source breakdown (router / MCP gateway / skill-card injection /
      future-compatible fields) present and additive.
- [ ] **S** Report sections suit internal ROI review (counts, bytes, est tokens, optional
      local dollars, known limitations, privacy-proof flags).
- [ ] **M** Compatible with Free/Team contracts; no entitlement/billing/provider integration.
- Acceptance matrix to exercise: CSV export; JSON export; dollars disabled by default;
  local price config present; **no forbidden fields**; Free/Team compatibility.
- **Do NOT approve if:** dollars appear without explicit local rate; any hosted/billing
  hook is added; labels carry PII; or CSV/JSON disagree on the measured figures.
- Evidence: __________  Verdict: __________

## Form TR-04 — Enterprise tier (evidence pack)

Governing contract: O064-12. The Enterprise bonus is an **audit-safe local evidence pack**:
aggregate savings + a written method/assumptions statement, no data egress.

- [ ] **M** Produces a **local evidence pack** with a machine-readable **manifest** plus a
      written **method/assumptions statement** (what is measured, what is estimated, the
      `bytes // 4` heuristic, dollars off-by-default).
- [ ] **M** Includes **privacy-proof** and **schema/version-proof** sections; source-artifact
      inventory uses **safe labels only**.
- [ ] **M** **No data egress**: no automatic action, no enforcement, no remote submission.
- [ ] **S** Manifest hash is **stable for identical content** (reproducibility).
- [ ] **S** Optional signature-ready structure present **without claiming signature
      enforcement** unless signing code actually exists.
- [ ] **M** No SSO/SCIM, on-prem license server, hosted compliance store, or enforced
      policy sync in v0.6.4.
- Acceptance matrix to exercise: evidence pack generated; manifest validates; privacy
  proof passes; forbidden fields absent; **hash stable for identical content**; no
  cryptographic-signature claim unless code exists.
- **Do NOT approve if:** the pack egresses data; claims governance is "enforced"; claims a
  signature is verified without signing code; or the hash is non-deterministic for identical input.
- Evidence: __________  Verdict: __________

## Form TR-05 — Cross-tier release-claim review

Governing contract: O064-13 cross-tier release matrix + O064-07 public-claim authorization.
Run this **once** before any tier set ships, over the combined release surface.

- [ ] **M** Each tier's row in the release matrix matches what the PR actually makes live
      (Free = local meter base; Registered = export profile; Team = local rollup;
      Business = admin CSV/JSON; Enterprise = governance/evidence pack).
- [ ] **M** Allowed public claim per tier is the **release-note-safe line** from O064-13;
      nothing stronger appears anywhere (README, notes, CLI, comments).
- [ ] **M** Forbidden words absent across the whole surface (see cross-cutting claim list).
- [ ] **M** No fake paid feature; no hosted claim unless code exists; no telemetry claim;
      no exact token/dollar claim.
- [ ] **M** **Free contract not broken** by any tier addition.
- [ ] **S** Tier matrix, tier-bonuses doc (O064-03), and claim-authorization (O064-07) are
      mutually consistent — no tier promises more in one doc than another allows.
- **Do NOT approve if:** any tier ships a capability the matrix marks "NOT live"; any
  forbidden claim survives; or a tier doc and the matrix disagree on what is live.
- Evidence: __________  Verdict: __________

---

## Reviewer output

One verdict per applicable form + one overall. Map each PASS back to the tier contract
(O064-09..13) and the acceptance test (T1–T15) it satisfies, so the review demonstrably
confirms the PR honours the already-shipped contract without scope creep, privacy leak,
or claim inflation. Opus posts the verdict to the Hermes chat; **Codex merges**.
