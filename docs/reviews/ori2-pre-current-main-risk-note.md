# ORI2-PRE-09 — Current-Main Risk Note: Weakened Router Inject

**Task:** ORI2-PRE-09 (Opus preflight, unblocked). **Status:** user-facing risk note,
no source/runtime change. **Audience:** anyone running `unlimited-skills` from current
`main` (`d20d099`) before Router Inject v2 lands. **Source:** findings in
`ori2-pre-current-main-inject-gap-audit.md`.

## The risk in one line

On a long autonomous run, an agent on current `main` is told to check the skill
library **once, passively, up front** — and is even told **not to search again** — so
it silently stops consulting the library exactly when later phases enter new domains
where a skill would help.

## Who is affected

- **Most affected:** long autonomous / multi-phase runs (an agent working many steps
  without fresh user prompts between phases). This is the headline gap.
- **Partly protected:** ordinary interactive use, because the `user_prompt_submit.py`
  ambient hook re-runs `suggest` on **each user prompt** — so a human who keeps typing
  gets fresh hints. The protection disappears between prompts, i.e. inside a long
  autonomous stretch.
- **Not affected:** one-shot single-task use where the up-front check is enough.

## Concrete symptoms

- The agent uses a skill for the first phase (or not at all) and then never re-queries,
  even after pivoting from, say, backend code to a security review or a release
  workflow — each a domain the library likely covers.
- `AGENTS.md` points users at the slower `search` path and never names the fast
  `suggest` probe, so even a motivated agent reaches for the wrong command.
- An agent cannot tell what the library covers (no inventory/domain snapshot), so it
  under-uses it out of uncertainty.

## Severity

**Medium.** Nothing breaks, errors, or leaks — it is a *missed-value* risk (the
library is under-consulted), not a correctness or security risk. But for the exact
workload Unlimited Skills exists to serve (long agent runs), the value leak is large.

## Interim mitigations (until Router Inject v2 ships)

- Operators of long runs: instruct the agent to **re-run `unlimited-skills suggest
  "<phase summary>"` at each new phase**, not just at the start.
- Prefer `suggest` over `search` for the fast path.
- Keep the ambient hook enabled (do not set `UNLIMITED_SKILLS_NO_INJECT`) so at least
  each user-prompt boundary re-injects.

## Permanent fix

Router Inject v2 (US-064-000): a self-applied phase-freshness rule + `suggest` command
+ inventory/domain snapshot in the always-loaded `AGENTS.md`, with the SKILL.md
"don't search again" rule re-scoped to a single phase. Acceptance criteria:
`ori2-pre-router-inject-v2-acceptance-rubric.md`.

## Honesty note

This note states a missed-value risk only; it does not claim any data loss, security
exposure, or runtime failure in current `main`. The ambient hook genuinely works at
turn boundaries — the gap is strictly the mid-run, between-prompt case.
