# ORI2-PRE-05 — Public Claim Boundary (Router Inject v2)

**Task:** ORI2-PRE-05 (Opus preflight, optional, unblocked). **Status:** claim
guardrail, no source/runtime change. **Purpose:** fix the line between what the RI2
AGENTS.md/SKILL.md block and any surrounding copy MAY claim vs MUST NOT claim, so the
build does not leak unverified or hosted-only assertions into the public MIT surface.
Binds the existing review rules in `AGENTS.md:31-37` and the hook privacy contract in
`plugin/hooks/user_prompt_submit.py`.

## Why this exists

The inject block is read by every agent and lives in a public MIT repo. Inflated or
inaccurate claims there are both a trust problem (the agent over-relies) and a
public-honesty problem (the README-adjacent surface overstates what ships). RI2 adds
counts and coverage claims, which is exactly where overstatement creeps in.

## CLAIM_ALLOWED (with limits)

- The **inventory count** and **per-collection split**, *as generated* from the live
  library, with the generation basis recorded (rubric C1). Allowed because it is
  verifiable and drift-guarded.
- The **domain coverage** signal, *as derived* from the checked-in mapping, including
  honest "empty" domains (ORI2-PRE-03 honesty rule).
- That `suggest` is a **fast local probe** (~1s typical) — matches the hook's design
  and existing SKILL.md wording.
- That **local Community Core commands** (`search/list/view/where/suggest/use/
  feedback`) work offline without registration — already stated and true.

## CLAIM_FORBIDDEN

- **F1 — Rounded/marketing totals** ("200+ skills", "hundreds of workflows") that the
  drift guard cannot verify. Use the generated number or nothing.
- **F2 — Coverage the taxonomy does not back.** No "covers every domain" / "always has
  a skill" phrasing; the table must be able to show gaps.
- **F3 — Hosted/registration features as if they were local/free.** Hosted catalog,
  community submissions, team sync, dashboard/cloud are registration-gated
  (`AGENTS.md:37`) — RI2 copy must not imply they ship in the MIT core.
- **F4 — Security features not yet client-enforced.** Per `AGENTS.md:33-34`, signature
  verification is planned until client enforcement exists; current enforcement is
  SHA256 + safe extraction. RI2 must not claim cryptographic signature enforcement.
- **F5 — A runtime "phase-boundary hook" that enforces freshness.** No such event
  exists (ORI2-PRE-01 R3); the freshness rule is model-self-applied. Claiming runtime
  enforcement would be false.
- **F6 — Quality/winrate claims** ("the right skill every time", measured uplift) with
  no benchmark attached. The `suggest` ranking quality is out of RI2's evidence scope.
- **F7 — Privacy claims beyond the contract.** Do not assert "nothing leaves your
  machine" wholesale; state the actual contract (prompt text → local CLI only; hosted
  calls carry no prompt text/paths/secrets/customer names; skills referenced by NAME).

## Reviewer check (ORI2 grading hook)

For every quantitative or capability claim in the RI2 block: is it (a) generated/
verifiable, (b) backed by the taxonomy, (c) not a hosted-only or planned-only feature
stated as shipped? Any "no" → request changes. Cross-check against `AGENTS.md:31-37`
so RI2 does not contradict the standing review rules.

## Note

This artifact is the public-claim half of acceptance; functional acceptance lives in
ORI2-PRE-02. A build can be functionally correct and still FAIL here on an overstated
claim — both gates must pass.
