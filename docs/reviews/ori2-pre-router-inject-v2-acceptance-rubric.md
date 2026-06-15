# ORI2-PRE-02 — Router Inject v2 Acceptance Rubric

**Task:** ORI2-PRE-02 (Opus preflight, unblocked). **Status:** acceptance criteria,
no source/runtime change. **Purpose:** the pass/fail rubric an Opus reviewer
(ORI2-01..04) applies to the RI2-01..04 build. Codex builds *to* this rubric;
reviewers grade *against* it. Closes gaps D1–D5 from
`ori2-pre-current-main-inject-gap-audit.md` without over-scoping into the runtime
phase-event RI2 cannot yet hook (R1–R3).

**Verdict scale per item:** PASS / PASS_WITH_FIXES / FAIL. A single FAIL on a
must-have (M) item blocks acceptance. Should-have (S) items downgrade to
PASS_WITH_FIXES.

## Section A — AGENTS.md inject block (the always-loaded surface)

| # | Criterion | Must/Should | Pass condition |
| --- | --- | --- | --- |
| A1 | Names `suggest` as the primary entry point | M | The block shows the exact `suggest` command; `search`/`view`/`where` are secondary (closes D1) |
| A2 | Exact suggest command format present | M | Verbatim form: `unlimited-skills suggest "<3-8 keyword phase summary>" --json --card --limit 1` (matches `user_prompt_submit.py` call shape) |
| A3 | Phase-level freshness rule | M | States: re-run `suggest` at every **substantive phase boundary**, not once per session (closes D3); "phase boundary" is defined (see ORI2-PRE-04) |
| A4 | Inventory snapshot | M | Block carries total routable-skill count + per-collection counts (ecc / superpowers / local), generated not hand-typed (closes D5) |
| A5 | Domain coverage table | M | A domain→availability table the agent can scan to judge whether a lookup is worth it (closes D5; spec in ORI2-PRE-03) |
| A6 | Anti-spam bound | M | Explicit rule preventing re-query within the same phase / on trivially similar queries; bounds lookups per phase to 1 (closes the D4 over-correction without re-introducing spam) |
| A7 | Tier interpretation | S | Explains the 3 hint tiers (silence / name hint / card) so the agent reads injected context correctly, consistent with `user_prompt_submit.py` |
| A8 | Privacy line | M | Forbids sending prompt text, paths, secrets, customer names to hosted calls; skills referenced by NAME (matches existing AGENTS.md review rules + hook privacy contract) |
| A9 | Kill switch documented | S | References `UNLIMITED_SKILLS_NO_INJECT` behavior so operators know how to quiet it |

## Section B — Router SKILL.md edit

| # | Criterion | Must/Should | Pass condition |
| --- | --- | --- | --- |
| B1 | Re-scope "do not search again" | M | `router-hermes/SKILL.md:56` rule is scoped to **the current phase** only, not run-wide (closes D4) |
| B2 | Cross-reference phase rule | S | SKILL.md points to the AGENTS.md phase-freshness rule rather than contradicting it |
| B3 | No regression to lookup discouragement | M | No remaining wording that reads as "stop using the router for the rest of the run" |

## Section C — Inventory generation (no stale hand-typed numbers)

| # | Criterion | Must/Should | Pass condition |
| --- | --- | --- | --- |
| C1 | Counts are generated | M | The snapshot/table is produced by a script (e.g. from `list --json`), not a literal an editor must remember to update |
| C2 | Drift guard | M | A test/check fails if the AGENTS.md counts diverge from the live library count beyond a tolerance |
| C3 | Determinism | S | Generation is deterministic and reproducible in CI |

## Section D — Scope discipline (do-not list)

A build that does ANY of these FAILS regardless of A–C:

- D-x1 Adds a fake/aspirational runtime "phase boundary" hook and claims it enforces
  freshness (R3 says no such event exists yet — RI2 is doc-led).
- D-x2 Re-introduces run-wide "don't search again" wording (re-opens D4).
- D-x3 Hand-types skill counts that will silently rot (violates C1/C2).
- D-x4 Touches Money Saved Meter (v0.6.4) surfaces — out of lane.
- D-x5 Makes hosted/registration claims not yet enforced in client (violates A8 /
  public-claim boundary, see ORI2-PRE-05).

## Section E — Evidence required from the build

For acceptance the RI2 PR must attach: the rendered AGENTS.md block; the generator
script + sample output; the drift-guard test result; a diff of the SKILL.md re-scope;
and a run of the 100-step fixture (ORI2-PRE-04) showing ≥4 phase-boundary re-queries.

## Reviewer instruction

Grade each item, cite the file:line evidence, and produce one overall verdict. Any
M-item FAIL → request changes. Map each PASS back to the D1–D5 gap it closes so the
review demonstrably resolves the original problem statement.
