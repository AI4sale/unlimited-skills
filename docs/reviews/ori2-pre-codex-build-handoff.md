# ORI2-PRE-06 — Codex RI2-01..04 Build Handoff (Router Inject v2 / US-064-000)

**Task:** ORI2-PRE-06 (Opus preflight, unblocked after #183/#184 merged). **Status:**
build handoff, no source/runtime change in THIS document. **Purpose:** convert the
merged preflight pack (ORI2-PRE-01..05, plus the PRE-07 review forms) into exact,
build-ready RI2-01..04 implementation tasks Codex can execute without guessing. This
document does **not** implement RI2 and does **not** infer an owner waiver.

## START CONDITION (hard gate)

RI2-01..04 implementation may begin **only** after one of:
- the owner records an explicit **waiver for US-064-000** (text in
  `ori2-pre-owner-waiver-brief.md`), **or**
- **US-063-005 is accepted**.

`#62` is merged; that condition is already satisfied. Until one of the two above is
recorded, this handoff is a plan, not a go.

## Global non-goals (apply to every RI2 task)

- No Money Saved Meter / v0.6.4 value-meter code or docs (out of lane).
- No version bump, tag, or publish.
- No new runtime "phase-boundary" hook claimed to enforce freshness — none exists
  (PRE-01 R3); RI2 is **doc-led, model-self-applied**, with `user_prompt_submit.py`
  as the existing turn-boundary backstop (leave it unchanged).
- No hand-typed skill counts (PRE-03 C1).
- No forbidden public claims (PRE-05 F1–F7).

## Source map (read before building)

- Gap statement: `ori2-pre-current-main-inject-gap-audit.md` (gaps D1–D5, R1–R3).
- Acceptance rubric: `ori2-pre-router-inject-v2-acceptance-rubric.md` (Sections A/B/C/D/E).
- Inventory/domain semantics: `ori2-pre-domain-taxonomy-inventory-review-spec.md`.
- 100-step fixture: `ori2-pre-100-step-run-fixture-spec.md`.
- Public claim boundary: `ori2-pre-public-claim-boundary.md`.
- Review forms (how each task is graded): `ori2-pre-ri2-review-forms.md`.

---

## RI2-01 — Inventory + domain snapshot generator & drift guard

- **Final product:** a script that emits the routable-skill inventory (total +
  per-collection) and the domain coverage table, plus a drift-guard test.
- **Files to inspect:** `plugin/` CLI surface and however `list --json` is produced;
  existing `tests/` layout (e.g. `tests/test_plugin_hooks.py`) for the test pattern;
  `packs/<collection>/skills/<category>/SKILL.md` paths for the domain mapping signal.
- **Files to change/add:** a generator script (suggested
  `scripts/generate_router_inventory.py` or a CLI subcommand); a checked-in
  domain-mapping file; a test (suggested `tests/test_router_inventory.py`).
- **Acceptance (rubric C + PRE-03):** counts generated from `list --json`, de-duped by
  resolved name, per-collection split summing to total; domain table from the
  checked-in mapping; empty domains shown (honesty rule); explicit
  other/uncategorized bucket; deterministic; drift guard fails on divergence beyond a
  declared tolerance; ≤ ~15 domain rows.
- **Evidence:** generator output sample; passing drift-guard test; two-run determinism
  proof.
- **Privacy:** counts/domains only — no skill bodies, no local paths in output.
- **Forbidden:** hand-typed numbers; hiding empty domains; per-skill listing.
- **Closes:** D5 (and feeds D1/D3 surfacing in RI2-02).

## RI2-02 — Root AGENTS.md Router Inject v2 block

- **Final product:** the always-loaded `AGENTS.md` inject block, between the existing
  `<!-- BEGIN UNLIMITED SKILLS -->` / `<!-- END UNLIMITED SKILLS -->` markers
  (currently `AGENTS.md:5-27`), rewritten to Router Inject v2.
- **Files to inspect:** `AGENTS.md` (current weak block lines 8-26; review rules
  31-37 must not be contradicted); RI2-01 generator output (embedded here).
- **Files to change:** `AGENTS.md` (only inside the markers + adjacent as needed).
- **Acceptance (rubric A + PRE-05):** names `suggest` as primary (A1, closes **D1**);
  exact command `unlimited-skills suggest "<3-8 keyword phase summary>" --json --card
  --limit 1` (A2); phase-level freshness rule with a defined "substantive phase
  boundary" (A3, closes **D2/D3**); embedded generated inventory snapshot (A4) +
  domain table (A5, closes **D5**); anti-spam bound, ≤1 lookup/phase (A6); tier
  interpretation matching `user_prompt_submit.py` (A7); privacy line (A8); kill-switch
  `UNLIMITED_SKILLS_NO_INJECT` documented (A9); no PRE-05 forbidden claims.
- **Evidence:** rendered block; confirmation counts came from RI2-01 (not typed).
- **Privacy:** skills by NAME; no paths/secrets/customer data; hosted-call limits.
- **Forbidden:** marketing totals; "covers everything"; fake runtime-hook claim.
- **Closes:** D1, D2, D3, D5.

## RI2-03 — Router SKILL.md / installer-rendered guidance update

- **Final product:** the router SKILL.md "do not search again" rule re-scoped to the
  current phase, consistent across rendered variants.
- **Files to inspect/change:** `skills/router-hermes/SKILL.md` (the run-wide rule is at
  line 56: "If `suggest` returns nothing, proceed … do not search again"); the sibling
  variants `skills/router-claude-code/SKILL.md`, `skills/router-openclaw/SKILL.md`,
  `skills/skill-router/SKILL.md`; and `plugin/skills/unlimited-skills/SKILL.md`. NOTE
  these carry installer placeholders (e.g. `{{HERMES_SH_LAUNCHER}}`,
  `{{UNLIMITED_SKILLS_LIBRARY_ROOT}}`) — preserve the templating; only change wording.
- **Acceptance (rubric B):** B1 rule scoped to current phase (closes **D4**); B2
  cross-references the AGENTS.md phase-freshness rule; B3 no remaining run-wide
  "stop using the router" reading; **parity** — apply the same re-scope to every router
  variant or record why not.
- **Evidence:** diff per variant; a grep showing no run-wide "do not search again"
  wording remains.
- **Forbidden:** breaking installer placeholders; diverging variants silently.
- **Closes:** D4.

## RI2-04 — Regression tests / 100-step fixture

- **Final product:** the 100-step fixture + runner that proves phase-boundary
  re-query behavior, per PRE-04.
- **Files to inspect:** `tests/` patterns; PRE-04 fixture spec.
- **Files to add:** a fixture file (10 phases, ≥4 domain-change boundaries flagged
  `requires_requery: true`, plus same-domain negatives); a runner/test reporting
  re-query count vs expected.
- **Acceptance (PRE-04 + rubric E):** threshold met at flagged boundaries; no re-query
  on negatives (anti-spam holds); expressed at the guidance/decision level (not a claim
  a hook forced it — R3 honesty); fixture run attached as acceptance evidence.
- **Evidence:** fixture run output.
- **Closes:** verifies D3 fix end-to-end.

---

## Task → gap → spec traceability (reviewer uses this)

| RI2 task | Closes gaps | Graded by |
| --- | --- | --- |
| RI2-01 | D5 | rubric C, PRE-03, form RI2-01 |
| RI2-02 | D1, D2, D3, D5 | rubric A, PRE-05, form RI2-02 |
| RI2-03 | D4 | rubric B, form RI2-03 |
| RI2-04 | D3 (verification) | PRE-04, rubric E, form RI2-04 |

Every RI2 task maps back to a PRE-01 gap and forward to a grading form, so the build
demonstrably closes the original problem and review is instant.

## Boundaries this handoff respects

- Does not implement RI2 (plan only).
- Does not infer or grant an owner waiver; restates the start condition as a gate.
- Keeps Router Inject v2 (US-064-000) separate from Money Saved Meter (v0.6.4).
