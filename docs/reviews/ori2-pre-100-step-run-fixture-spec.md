# ORI2-PRE-04 — 100-Step Agent-Run Review Fixture Spec

**Task:** ORI2-PRE-04 (Opus preflight, unblocked). **Status:** fixture spec, no
source/runtime change. **Purpose:** define the synthetic long-run fixture that proves
Router Inject v2 actually fixes the 100-step gap (R1/D3 in
`ori2-pre-current-main-inject-gap-audit.md`). Without this fixture, "phase-level
freshness" is an unverifiable claim. The build (RI2) ships the fixture; reviewers
(ORI2-04) run it as acceptance evidence (rubric E).

## What the fixture must prove

That an agent working a long task **re-queries `suggest` at substantive phase
boundaries** — not once at the top — and that the anti-spam bound prevents
within-phase re-query storms. It is a behavioral fixture about *when a lookup is
expected*, not a test of `suggest`'s ranking quality (that lives elsewhere).

## Definition: "substantive phase boundary"

A phase boundary occurs when the active task crosses into work of a **different
domain** (per the ORI2-PRE-03 taxonomy) or a **different deliverable kind**. Examples
that ARE boundaries: research → implementation; backend code → frontend UI;
implementation → security review; code → release/git workflow. Examples that are NOT
boundaries: continuing to edit two files in the same feature; fixing a typo;
re-reading the same spec. The fixture encodes specific boundaries so "expected
re-query" is unambiguous.

## Fixture shape

- **10 phases**, each a labeled segment of one continuous task, ordered to cross
  domains deliberately (so boundaries are real, not cosmetic).
- **≥4 phase boundaries that change domain** — these are the points at which a fresh
  `suggest` is REQUIRED. (10 phases yield 9 transitions; at least 4 must be
  domain-changing so the threshold is meaningful.)
- Each phase carries: a phase id, a short task summary the agent would naturally
  derive, the expected domain, and a flag `requires_requery: true|false`.
- A handful of **negative cases**: two consecutive phases in the SAME domain where a
  re-query is NOT required, to prove the anti-spam bound (rubric A6) holds.

### Illustrative phase ladder (the build may refine labels, must keep ≥4 boundaries)

| Phase | Summary (derived) | Domain | requires_requery |
| --- | --- | --- | --- |
| P1 | scope the task, read context | planning/architecture | true (first lookup) |
| P2 | design data model | backend/API | true (domain change) |
| P3 | implement endpoint | backend/API | false (same domain) |
| P4 | build the UI form | frontend/UI | true (domain change) |
| P5 | wire client calls | frontend/UI | false (same domain) |
| P6 | write tests | testing/QA | true (domain change) |
| P7 | fix a failing test | debugging | true (domain change) |
| P8 | security pass on input handling | security | true (domain change) |
| P9 | write the docs | docs/writing | true (domain change) |
| P10 | open PR, branch hygiene | git/release workflow | true (domain change) |

That ladder has **7 domain-changing boundaries** (≥4 satisfied) plus 2 negative
same-domain transitions (P2→P3, P4→P5).

## Pass / fail criteria

- **PASS** if, replaying the fixture under the RI2 guidance, the expected-re-query
  count meets/exceeds the threshold at the flagged boundaries AND no re-query is
  emitted on the negative same-domain transitions (anti-spam holds).
- **FAIL** if re-queries happen only at P1 (the one-shot regression), or fire on every
  phase including same-domain ones (spam regression).

## Mechanism notes (keep honest)

- Because no runtime phase-boundary event exists (R3), this fixture verifies the
  **doc-led, model-self-applied** behavior — i.e. given the RI2 AGENTS.md rule in
  context, the model recognizes the boundary and issues the lookup. The fixture
  should therefore be expressed at the guidance/decision level (does the agent decide
  to re-query at the flagged boundary?), not as a claim that a hook forced it.
- The `user_prompt_submit.py` ambient hook remains the turn-boundary backstop and is
  out of scope for this fixture (it does not fire mid-run by design).

## Deliverable

A checked-in fixture file (phases + expected flags) plus a small runner/harness that
reports re-query count vs expected, usable as the rubric-E evidence artifact.
