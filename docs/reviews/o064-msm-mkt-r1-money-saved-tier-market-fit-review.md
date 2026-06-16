# O064-MSM-MKT-R1 — Money Saved tier market-fit review

**Reviewer:** Opus (tier-implementation/review lane)
**Date:** 2026-06-16
**Scope:** v0.6.4 Money Saved tier ladder — Registered (#194), Team (#210), Business (#211), Enterprise (#212) — reviewed for *buyer value*: is each paid tier a real, runnable capability a buyer would pay for, not a disclaimer or a doc?
**Verdict:** **PASS** (each tier delivers distinct, verifiable buyer value; positioning is honest and defensible).

> Companion to [O063-MKT-R1](o063-mkt-r1-tier-market-fit-review.md) (the v0.6.3 learning-loop tier market-fit review). Same lens, money-saved surface.

## 1. The buyer question each tier answers

| Tier | Buyer | The question it answers | Artifact they walk away with |
|---|---|---|---|
| **Free** (`money-saved meter`) | Individual evaluator | "Is this tool actually saving me context/tokens?" | A local before/after aggregate report |
| **Registered** (`registered-export`, #194) | Individual / champion | "Can I keep a portable receipt of my own savings?" | A schema-versioned local savings export |
| **Team** (`team-rollup`, #210) | Team lead | "What are my N engineers saving, in one view?" | A local multi-member rollup (exact calls + measured bytes + token estimates) |
| **Business** (`admin-export`, #211) | Admin / ops | "Can I slice savings by team/workspace/agent-class/project and load it into my BI?" | A local **CSV + JSON** admin export, grouped |
| **Enterprise** (`evidence-pack` + `verify-evidence-pack`, #212) | Procurement / security / finance | "Can I get *auditable, tamper-evident* proof I can hand to a reviewer?" | A content-hash-sealed local evidence pack + an **independent verifier** |

Each row is a different buyer with a different job-to-be-done, and each ships as a **runnable command that emits an artifact** — the owner's bar for a real tier (runnable function + artifact + tests + personal verification), not a docs-only promise.

## 2. Where the money is — ranked by paid-wedge strength

1. **Enterprise is the strongest paid wedge.** The `verify-evidence-pack` verifier is the differentiator: it re-reads the pack from disk and fails closed on any tamper (`ok=false`, exit 1), proves the Registered→Team→Business→Enterprise schema chain, proves measured-vs-estimated separation with dollars disabled, and proves the privacy boundary — all **locally, with no egress**. For a regulated / security-conscious buyer, "evidence I can verify myself without sending data anywhere" is exactly what unblocks procurement. Nothing in the local-first competitive set (LangSmith / Langfuse / Helicone are hosted-telemetry models) offers a buyer-runnable tamper-evident evidence pack.
2. **Business is the practical revenue tier.** CSV that an admin can open in Excel / load into BI, grouped by the four labels they already think in (team / workspace / agent_class / project), with measured facts kept separate from estimates. This is the "I can put a number in a slide" tier. Honest separation of measured vs estimated is a *trust* feature, not a limitation — it survives a skeptical CFO.
3. **Registered is a sound free-to-paid hinge.** A portable local receipt that costs nothing to produce and creates the artifact the upper tiers aggregate.
4. **Team is the weakest tier and should be positioned honestly.** Its inputs are **gathered out of band** — there is no hosted sync; an operator collects member exports manually. That manual-gather step is real friction and limits Team's standalone appeal. It is correctly scoped (no false "live team dashboard" claim), but it should be sold as "the on-ramp to Business / Enterprise admin reporting," not as a destination. The hosted / live-sync version is future work and must not be implied now.

## 3. Honesty check (what protects the position)

- **No exact-money / exact-token / bill-reduction claim** anywhere — these appear only in `forbidden_claims`. Tokens are always labelled `estimated`; **dollars are disabled by default** at every tier (no local price configured). This is the single most important credibility property: the product never overclaims savings, so the numbers survive scrutiny.
- **No hosted dashboard / billing / telemetry / SSO / SCIM / governance / signature-enforced** claim is asserted; each appears only as an explicit non-claim. The Enterprise pack states plainly that no cryptographic signature is produced — it is *content-hash* tamper-evidence, not a PKI signature, and it says so.
- **Local-first, no egress** is consistent end to end and is the core wedge against the hosted-telemetry incumbents.

## 4. Risks / recommendations (non-blocking)

- **Team manual-gather friction** is the main go-to-market weakness. Recommend marketing Team as a step toward Business, and tracking demand for an opt-in local sync helper as a *future* tier (not v0.6.4).
- **"Estimated tokens" needs a one-line buyer-facing explanation** in sales collateral so the estimate is read as conservative-by-design, not as vagueness.
- **Enterprise should lead the paid pitch** for regulated / security / procurement ICPs; Business leads for ops / finance buyers who just need a number in a report.

## 5. Verdict

**PASS.** Every paid tier is real, runnable, independently verifiable functionality with a distinct buyer and artifact — not disclaimers or docs. The positioning is honest (measured vs estimated, dollars off, no false hosted / enterprise claims), which is what makes the savings numbers defensible. Lead paid motion with **Enterprise (verifier-backed evidence)** for regulated buyers and **Business (admin CSV/JSON)** for ops / finance buyers; treat **Team** as an on-ramp and acknowledge its manual-gather friction rather than papering over it.
