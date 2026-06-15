# O064-07 — Money Saved Meter: Public Claim Authorization (Draft)

**Roadmap ref:** `...#v0.6.4`. **Status:** planning review (no code). **Reviewer:** Opus.
**Purpose:** the authorized public wording for the v0.6.4 Money Saved Meter — what
may and may not be said in release notes, README, and marketing. Binds the build and
the docs-grep test (acceptance T15). Consistent with O064-01 §3/§4, O064-02, and the
#180 claim scrub.

## Verdict: **CLAIM_ALLOWED_WITH_LIMITS**

The feature may be announced publicly, restricted to the allowed claim below and the
estimate-honesty limits. It is **not** authorized to claim exact money, exact tokens,
or any hosted/telemetry capability.

## Authorized public claim (use verbatim or tighter)

> "v0.6.4 adds a local **Money Saved Meter**: a periodic, privacy-safe estimate of the
> standing **MCP schema** context Unlimited Skills avoided loading over your recent
> calls — **measured bytes**, **estimated tokens**, and an optional **user-supplied
> dollar estimate**. All numbers are computed and stored **locally**; nothing is
> uploaded."

### Allowed supporting lines
- "Bytes avoided are measured; tokens are an estimate (`bytes // 4`)."
- "Shown automatically every ~N calls — a usage cadence, not a per-call bill."
- "Dollar figures are off by default and use only a rate you set."
- "Works offline; no account, no telemetry, no upload."
- Per-tier release-note-safe lines from O064-03 (Free = live local meter; paid tiers
  = local future-compatible exports, **not** live hosted features).

## Forbidden claims (must NOT appear publicly)

| # | Forbidden | Why |
| --- | --- | --- |
| X1 | "Saved you $Z" / any **exact or guaranteed** dollar figure | dollars are an opt-in local estimate, never guaranteed |
| X2 | "Saved N tokens" as an **exact count** | tokens are the `bytes // 4` heuristic |
| X3 | "Saved skill/skill-body context" | skill-body savings are **not measured** (#180); only MCP schema context is |
| X4 | "Saved X over your last 100 calls" as **summed per-call billing** | the window is a cadence, not an accounting multiplier |
| X5 | "We tracked / we measured your usage", "dashboard", "analytics" | implies hosted telemetry; the meter is local-only |
| X6 | Any "uploaded / synced / sent to AI4SALE" framing | no network egress in v0.6.4 |
| X7 | Naming a specific MCP server in a public/passive context | server names are private; push aggregates only |
| X8 | Comparative market-price savings ("save $X vs GPT-4 context") | not measured; implies a billing model we do not run |

## Limits that condition the authorization
1. Every public surface separates **measured** (bytes) from **estimated** (tokens),
   and marks dollars **estimated + opt-in**.
2. No public number is presented without the word "local" / "estimate" in context.
3. Paid-tier copy must not imply a live hosted/billing feature exists in v0.6.4
   (exports are local + future-compatible only).
4. The docs-grep test (T15) enforces: no real paths, no real server names, no
   dollars-as-fact in shipped docs.

## Recommendation
**CLAIM_ALLOWED_WITH_LIMITS.** Ship the allowed claim + supporting lines; enforce the
forbidden list via the T15 grep and review. Re-confirm at release time once
US-063-005 closes and the implementation matches this wording.

---

### Evidence summary
- **Verdict:** CLAIM_ALLOWED_WITH_LIMITS.
- **Allowed claim:** local periodic estimate of MCP schema context avoided — bytes
  measured, tokens estimated, dollars optional/local.
- **8 forbidden claims** (X1-X8) bound to the T15 docs-grep gate.
