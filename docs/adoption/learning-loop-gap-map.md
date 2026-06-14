# Learning Loop Gap Map

Status: W1 handoff map for W2. This document records what must exist before
Unlimited Skills can claim a complete local learning loop.

## Target Loop

```text
local usage signal
  -> explicit feedback or validated miss
  -> eval candidate
  -> ranking/router/docs/skill fix
  -> release gate proves improvement
  -> success report shows better funnel
```

## Current Evidence

| loop_stage | current_state | gap | owner | action | fallback | next_task |
| --- | --- | --- | --- | --- | --- | --- |
| Local usage signal | `suggest`, `view`, `skill_used`, quickstart, MCP savings, ROI receipt aggregates exist | No single success-report command | Codex | Implement local aggregate success report after W1 | Use `learning-summary --events` and ROI receipt manually | W1.1 |
| Explicit feedback | `feedback record` accepts `accepted`, `rejected`, `neutral`; support docs route manual reports | Verdict not joined to exact use/session | Codex | Add session correlation to feedback rows or explicit correlation fallback | Keep per-skill aggregate counts only | W1.1 |
| Missed/wrong-skill report | Issue templates and support response pack exist | Local CLI lacks structured missed/wrong reason categories | Retrieval owner | Add reason taxonomy and redacted local report field | Use public/manual issue labels | W2 |
| Eval candidate | Frozen eval set and checker exist | No command converts accepted report into eval fixture draft | Retrieval owner | Add maintainer-reviewed feedback-to-eval candidate builder | Manual eval PR with redacted evidence | W2 |
| Fix implementation | Ranking/router/docs/skill PRs can update behavior | No ledger links feedback item to fix commit | Codex / Retrieval owner | Add improvement ledger row in PR docs | Changelog and PR body evidence | W2 |
| Release gate | Frozen effectiveness and v0.6 contract gates exist | Gate does not summarize per-feedback before/after outcome | Release owner | Add improvement summary to release evidence | Keep gate metrics and PR references | W2 |

## W2 Acceptance Handoff

W2 should not start by adding telemetry. It should start by making the manual
learning loop reproducible from local/redacted evidence.

W2 should require:

- a redacted feedback-to-eval candidate format;
- a maintainer acceptance rule for eval candidates;
- a way to link a feedback candidate to a fix PR;
- a release-gate evidence row that proves the fix did not regress the frozen
  eval set or privacy boundaries;
- no automatic skill rewriting;
- no automatic publication;
- no prompt upload;
- no task text upload;
- no user telemetry;
- no hosted query forwarding.

## Open Product Questions

| question | owner | decision_needed | fallback |
| --- | --- | --- | --- |
| Should accepted/rejected verdicts be joined by salted session id or by explicit operator-provided run id? | Product/runtime | Choose the least surprising local-only correlation model | Report aggregate verdicts only |
| Should wrong-skill and missed-skill reasons be separate local verdict categories or issue-template labels only? | Retrieval owner | Choose taxonomy before implementation | Keep rejected/neutral only |
| Should success-report be a top-level command or under `skills`? | CLI owner | Decide command location for v0.6.x/v0.7 compatibility | Use `unlimited-skills skills success-report --json` as draft |
| Should W0 wow-path proof be required before W1.1 ships? | Release owner | Decide if first-value proof must land before counters implementation | Keep W1.1 draft but do not release-gate it |

## Boundaries

The learning loop must stay local-first and privacy-safe:

- no telemetry;
- no auto-upload;
- no hosted calls;
- no analytics SDK;
- no tracking pixel;
- no prompt collection;
- no tool input or output collection;
- no skill body upload;
- no MCP schema upload;
- no local absolute paths in paste-safe output;
- no paid, hosted, team, or enterprise readiness claim.
