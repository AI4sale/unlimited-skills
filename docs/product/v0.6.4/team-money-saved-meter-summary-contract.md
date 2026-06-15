# O064-10 — Team-tier Money Saved Meter: Local Summary Contract

**Roadmap ref:** `...#v0.6.4`. **Tier:** Team. **Status:** build contract (no code).
**Blocked:** until **US-063-005 GO**. **Builds on:** Free meter (O064-08) +
Registered export (O064-09).

## Valuable Final Product
A Team-tier contract for a **shareable local team savings summary**: aggregate
context/tokens avoided across team members, produced locally and shared over the
team's **own** channel — with **no** live dashboard, **no** private publishing, **no**
automatic sync, **no** telemetry.

## 1. What Team adds (and only this)
- A **local summary artifact** that aggregates per-member savings exports (the
  Registered local exports) into one team-level view: total + per-member-alias
  bytes/estimated-tokens avoided.
- Sharing is **manual** over the team's own channel (the user moves the file). The
  tool provides no upload/sync/publish verb.

## 2. Aggregation contract
- Inputs: member-produced local exports (O064-09 schema), gathered by the team
  **out of band** (the tool does not fetch them over a network).
- Output fields: `team_total_schema_bytes_avoided` (measured),
  `team_total_est_tokens_avoided` (estimated), and a `members[]` list of
  `{alias, schema_bytes_avoided, est_tokens_avoided}`.
- `schema_version` present for future compatibility.

## 3. Privacy contract (fail-closed)
- **Aliases are member-local labels** — NOT OS usernames, emails, or machine ids.
- Aggregates only; **no server names**, no paths, no prompts, no skill bodies, no
  tokens/keys. Runs `assert_meter_safe` before write; suppress/abort on any unsafe
  field.
- No cross-member raw data — only each member's already-safe aggregate export.

## 4. Claim boundary
- Allowed: "local team summary; **no dashboard, no upload**."
- Forbidden: "team dashboard", "hosted audit", "SLA", "auto-sync", any live/hosted
  framing; exact-dollar/exact-token claims.

## 5. Backward compatibility
- Additive; reads Registered exports + local aggregates; changes nothing in
  `mcp savings`, ROI receipt, the Free meter, or the Registered export.

## 6. Acceptance
- Summary aggregates correctly from N member exports (sum check).
- Alias test: no OS user / email / machine id appears.
- Privacy-grep: no servers/paths/keys (T9/T15 analog); no network verb.
- Dollars off by default.

## 7. Explicitly NOT in Team (v0.6.4)
No dashboard, no hosted audit log, no SLA, no auto-sync, no telemetry, no automatic
dollars, no entitlement enforcement.

---

### Evidence summary
- **VFP:** one local, manually-shared team savings summary — no dashboard/upload.
- **Privacy:** member-local aliases, aggregates only, fail-closed gate.
- **Claim:** "local team summary; no dashboard, no upload."
