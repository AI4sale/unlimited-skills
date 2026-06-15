# ORI2-PRE-07 — RI2-01..04 Instant-Review Forms

**Task:** ORI2-PRE-07 (Opus preflight, unblocked). **Status:** review forms, no
source/runtime change. **Purpose:** pre-built per-task checklists so that when Codex
opens the RI2-01..04 implementation PRs, the Opus reviewer (ORI2-01..04) grades each
in minutes against fixed criteria instead of re-deriving them. Forms are keyed to the
acceptance rubric `ori2-pre-router-inject-v2-acceptance-rubric.md` (Sections A/B/C) and
the specs in PRE-03/PRE-04/PRE-05.

**Provisional task→deliverable mapping** (confirm against Codex's actual split; the
forms are organized by deliverable so they hold even if task numbering shifts):

| RI2 task | Assumed deliverable | Rubric section |
| --- | --- | --- |
| RI2-01 | Inventory + domain generator and drift guard | C, PRE-03 |
| RI2-02 | AGENTS.md inject block (the always-loaded surface) | A, PRE-05 |
| RI2-03 | router SKILL.md re-scope of "do not search again" | B |
| RI2-04 | 100-step fixture + runner | PRE-04, rubric E |

Each item: mark PASS / PWF / FAIL, cite `file:line` evidence. Any must-have FAIL →
request changes.

---

## Form RI2-01 — Inventory + domain generator & drift guard

- [ ] C1 Counts are **generated** from `list --json` (or equivalent), not hand-typed.
- [ ] C2 Drift-guard test fails when AGENTS.md counts diverge beyond declared tolerance.
- [ ] C3 Generation is deterministic (two runs → identical output).
- [ ] PRE-03 Unit of count = routable skill; references/scripts excluded.
- [ ] PRE-03 De-dup by resolved name (no alias double-count).
- [ ] PRE-03 Per-collection split (ecc/superpowers/local) present; total = sum after de-dup.
- [ ] PRE-03 Domain table from a **checked-in mapping**, not editorial.
- [ ] PRE-03 Empty domains shown as empty (honesty rule); no silent drops.
- [ ] PRE-03 Explicit "other/uncategorized" bucket exists and is non-silent.
- [ ] PRE-03 Domain row count scannable (≤ ~15).
- Evidence: __________  Verdict: __________

## Form RI2-02 — AGENTS.md inject block

- [ ] A1 `suggest` named as the **primary** entry point (search/view/where secondary).
- [ ] A2 Exact command present: `unlimited-skills suggest "<3-8 keyword phase summary>" --json --card --limit 1`.
- [ ] A3 Phase-level freshness rule; "substantive phase boundary" defined (cross-ref PRE-04).
- [ ] A4 Inventory snapshot embedded (generated, per RI2-01).
- [ ] A5 Domain coverage table embedded.
- [ ] A6 Anti-spam bound (≤1 lookup per phase; no within-phase re-query storm).
- [ ] A7 Tier interpretation (silence / name hint / card) consistent with `user_prompt_submit.py`.
- [ ] A8 Privacy line (no prompt text / paths / secrets / customer names to hosted calls; skills by NAME).
- [ ] A9 Kill switch `UNLIMITED_SKILLS_NO_INJECT` documented.
- [ ] PRE-05 No forbidden claims (F1 marketing totals, F2 over-coverage, F3 hosted-as-free, F4 unenforced security, F5 fake runtime hook, F6 unbacked quality, F7 over-broad privacy).
- Evidence: __________  Verdict: __________

## Form RI2-03 — router SKILL.md re-scope

- [ ] B1 The "do not search again" rule (current `skills/router-hermes/SKILL.md:56`) is scoped to the **current phase** only.
- [ ] B2 SKILL.md cross-references the AGENTS.md phase-freshness rule (no contradiction).
- [ ] B3 No remaining wording readable as "stop using the router for the rest of the run".
- [ ] Parity check: if other router variants exist (`router-claude-code`, `router-openclaw`, `skill-router`), the same re-scope is applied or a reason is given.
- Evidence: __________  Verdict: __________

## Form RI2-04 — 100-step fixture + runner

- [ ] PRE-04 Fixture has 10 phases with ≥4 domain-change boundaries flagged `requires_requery: true`.
- [ ] PRE-04 Includes negative same-domain transitions where re-query is NOT expected.
- [ ] PRE-04 Runner reports re-query count vs expected.
- [ ] PRE-04 PASS = threshold met at flagged boundaries AND no re-query on negatives.
- [ ] PRE-04 Expressed at the guidance/decision level (does the agent decide to re-query), not as a claim a runtime hook forced it (R3 honesty).
- [ ] Rubric E The PR attaches the fixture run as acceptance evidence.
- Evidence: __________  Verdict: __________

---

## Cross-cutting checks (all RI2 PRs)

- [ ] Scope do-not list (rubric D): no fake runtime phase hook (D-x1); no run-wide "don't search again" regression (D-x2); no hand-typed counts (D-x3); no Money Saved Meter / v0.6.4 changes (D-x4); no unenforced hosted/security claims (D-x5).
- [ ] Gate respected: PR does not assume an owner waiver / US-063-005 acceptance that is not recorded.
- [ ] Tests pass; no unrelated files touched.

## Reviewer output

One verdict per form + one overall. Map each PASS to the gap (D1–D5) it closes so the
review demonstrably resolves the PRE-01 problem statement.
