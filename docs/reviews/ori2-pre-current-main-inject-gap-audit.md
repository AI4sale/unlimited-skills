# ORI2-PRE-01 — Current `main` Skill-Inject Gap Audit (100-step run case)

**Task:** ORI2-PRE-01 (Opus preflight, unblocked). **Status:** review artifact, no
source/runtime change. **Scope:** document exactly where and how the skill-lookup
inject is weakened in current `main`, separated into **docs gaps** and
**runtime-hook gaps**, for the long autonomous-run ("100-step") case. This is the
problem statement the Router Inject v2 (US-064-000) acceptance rubric (ORI2-PRE-02)
must close.

**Baseline reviewed:** `origin/main` @ `d20d099`.
**Surfaces audited:** `AGENTS.md`, `skills/router-hermes/SKILL.md`,
`plugin/hooks/user_prompt_submit.py`, `plugin/hooks/session_start.py`.

## The failure mode this audit targets

An agent on a long autonomous run does not receive a fresh user prompt at each
internal phase boundary. It loads `AGENTS.md` once, may run a skill lookup once,
then works through many phases (research → design → code → tests → release …)
without re-querying the router. The library is most valuable exactly at those later
phase boundaries (a new domain appears), and that is precisely where current `main`
provides no standing instruction or runtime trigger to look again.

## Docs gaps

### D1 — `AGENTS.md` never names the primary entry point (`suggest`)
- **Evidence:** `AGENTS.md` mentions `suggest` **0 times** (it documents only
  `search`/`where`/`view`/`list`, lines 14-24). The fast ~1s probe that the whole
  router is built around is absent from the always-loaded surface.
- **Effect:** the one file guaranteed to be in context tells the agent to reach for
  the slow `search` path, not the calibrated `suggest` path the hooks use.

### D2 — Passive, one-shot framing
- **Evidence:** `AGENTS.md:10` — "Before doing substantive work, check whether
  Unlimited Skills has a relevant skill." A single pre-work check, phrased as a
  passive "check whether," with no notion of repetition across a run.
- **Effect:** satisfied once at session start; nothing re-arms it for step 2…100.

### D3 — No phase-boundary freshness rule
- **Evidence:** neither `AGENTS.md` nor `router-hermes/SKILL.md` defines "substantive
  phase boundary" or instructs a re-query when the task crosses into a new
  domain/phase.
- **Effect:** the high-value mid-run lookups never happen.

### D4 — Router SKILL.md actively discourages re-querying
- **Evidence:** `skills/router-hermes/SKILL.md:56` — "If `suggest` returns nothing,
  proceed with the task — do not search again with synonyms." Correct as anti-spam
  for a *single* phase, but with no phase scoping it reads as a run-wide "don't look
  again."
- **Effect:** compounds D2/D3 — the explicit instruction is to stop looking.

### D5 — No inventory / domain snapshot in the always-loaded surface
- **Evidence:** `AGENTS.md` carries no count of routable skills and no domain
  coverage map. The agent cannot tell whether the library plausibly covers the
  domain it just entered, so it cannot judge when a lookup is worth it.
- **Effect:** lookups are driven by vague triggers, not by knowledge of what exists.

## Runtime-hook gaps

### R1 — Ambient injection is turn-scoped, not phase-scoped (the core gap)
- **Evidence:** `plugin/hooks/user_prompt_submit.py` runs the `suggest` probe and
  injects a tiered skill hint/card, but it fires on the **UserPromptSubmit** event —
  i.e. once per human prompt. In a 100-step autonomous run there is no
  UserPromptSubmit between internal phases, so the hook does not re-fire mid-run.
- **Effect:** the strongest existing mechanism (ambient injection) is invisible to
  the exact case it is needed for. This is a structural limit of the hook event, not
  a bug in the hook.

### R2 — `session_start.py` fires once
- **Evidence:** `plugin/hooks/session_start.py` runs at session start only.
- **Effect:** no re-arm across the run; reinforces R1.

### R3 — No phase-boundary signal exists to hook onto
- **Evidence:** the plugin exposes `session_start` + `user_prompt_submit` only; there
  is no "phase boundary" / "subtask start" event in `plugin/hooks/hooks.json`.
- **Effect:** Router Inject v2's phase-level freshness cannot (today) be enforced
  purely at runtime; it must be carried as a **standing instruction in the
  always-loaded `AGENTS.md`** that the model self-applies, with the hook as the
  turn-boundary backstop. **This is the key architecture constraint for RI2.**

## Docs-gap vs runtime-gap split (summary)

| ID | Gap | Class | Fix owner |
| --- | --- | --- | --- |
| D1 | `suggest` absent from `AGENTS.md` | docs | RI2 AGENTS block |
| D2 | one-shot passive framing | docs | RI2 AGENTS block |
| D3 | no phase-boundary freshness rule | docs | RI2 AGENTS block |
| D4 | SKILL.md "do not search again" run-wide reading | docs | RI2 SKILL.md edit (scope to phase) |
| D5 | no inventory/domain snapshot | docs | RI2 AGENTS block |
| R1 | ambient inject is turn-scoped | runtime | out of RI2 doc-scope; note as backstop limit |
| R2 | session hook fires once | runtime | out of RI2 doc-scope |
| R3 | no phase-boundary event to hook | runtime/arch | RI2 relies on model self-application; hook stays turn-backstop |

## Conclusion for RI2

The fix is **doc-led**: because no runtime phase-boundary event exists (R3), Router
Inject v2 must put a **self-applied phase-level freshness rule + `suggest` command +
inventory/domain snapshot** into the always-loaded `AGENTS.md`, rescope the SKILL.md
"don't search again" to a single phase (D4), and keep `user_prompt_submit.py` as the
turn-boundary backstop. The acceptance rubric (ORI2-PRE-02) encodes the pass/fail
checks for each of D1–D5; R1–R3 are recorded here as the architecture boundary so RI2
is not over-scoped into building a new runtime event it cannot yet hook.
