# Skill Delivery Success Funnel

Status: W1 audit companion. This document describes the current local funnel
model and the first implementation target for a future success report.

## Funnel Model

The product question is:

```text
Did Unlimited Skills suggest a useful skill, did the agent/user load it, did it
get used, and did that use improve future retrieval?
```

The current local funnel is:

1. `suggestion generated`
2. `suggestion shown to user/model`
3. `skill card injected`
4. `skill viewed`
5. `skill used`
6. `use accepted / useful`
7. `use rejected / wrong skill`
8. `missed feedback`
9. `wrong feedback`
10. `feedback converted to eval case`
11. `eval/ranking/router/docs updated`
12. `release gate proves improvement`

## Current Local Commands

Available now:

```bash
unlimited-skills suggest "<task>" --json
unlimited-skills suggest "<task>" --json --card
unlimited-skills view <skill-name>
unlimited-skills use <skill-name>
unlimited-skills feedback record <skill-name> --verdict accepted
unlimited-skills feedback record <skill-name> --verdict rejected
unlimited-skills feedback prepare --json
unlimited-skills learning-summary --events --json
unlimited-skills roi receipt --format json
```

These commands are local. They do not upload local events, skill bodies,
prompts, tool IO, MCP schemas, env values, tokens, or keys.

## Ready, Partial, Missing

| area | status | evidence | limitation |
| --- | --- | --- | --- |
| Suggest count | ready | `suggest` event rows and `learning-summary --events` | No explicit user-visible acknowledgement. |
| Card delivery proxy | partial | `delivery_tier`, `injected`, tier counts | Host render success depends on W0 wow-path proof. |
| View count | ready | `view` and `daemon_view` rows | View usefulness is not captured. |
| Use count | ready | `skill_used` and `daemon_skill_used` rows | Solved-task status is not captured. |
| Suggest-to-view/use rates | ready | salted local session correlation in event payloads | Sessions without correlation fall back to aggregate counts. |
| Accepted/rejected verdicts | partial | `feedback.jsonl` summarized by `learning-summary` | Verdicts are not joined to exact use/session yet. |
| Missed/wrong feedback | ready | `feedback record --verdict missed`, `feedback record --verdict wrong`, issue templates, support response pack | Optional sub-reason taxonomy is not part of the shipped public verdict contract. |
| Feedback-to-eval conversion | missing | documented maintainer workflow | No local command converts feedback into eval candidate. |
| Improvement proof | partial | effectiveness checker and release gates | No ledger maps feedback -> eval -> fix -> release. |

## W1.1 Candidate Command

Do not implement this in W1. The candidate implementation after this audit is:

```bash
unlimited-skills skills success-report --json
```

Minimum JSON shape:

```json
{
  "schema_version": 1,
  "report_type": "skill_delivery_success_report",
  "local_only": true,
  "telemetry": false,
  "funnel": {
    "suggest_count": 0,
    "delivered_hint_count": 0,
    "delivered_card_count": 0,
    "view_count": 0,
    "use_count": 0,
    "accepted_count": 0,
    "rejected_count": 0,
    "suggest_to_view_rate": null,
    "suggest_to_use_rate": null
  },
  "gaps": [
    {
      "name": "accepted_verdict_not_joined_to_use",
      "owner": "Codex",
      "action": "attach local session correlation to verdict rows",
      "fallback": "report aggregate accepted/rejected counts only"
    }
  ],
  "privacy": {
    "aggregate_only": true,
    "raw_prompts_included": false,
    "raw_queries_included": false,
    "raw_tasks_included": false,
    "raw_notes_included": false,
    "skill_bodies_included": false,
    "tool_io_included": false,
    "mcp_schemas_included": false,
    "local_paths_included": false
  }
}
```

## Operator Interpretation

- A high `suggest_count` with low `view_count` means suggestions may be shown
  but ignored, hidden, confusing, or not loaded by the host.
- A high `view_count` with low `use_count` means the selected skill may not be
  actionable enough for the task.
- A high `rejected_count` means retrieval, ranking, docs, or skill quality need
  triage.
- Missing feedback does not mean success. It means unknown.
- A passing release gate proves the frozen eval and privacy boundaries, not
  user adoption by itself.

## Non-Goals

This funnel does not add telemetry, upload, hosted calls, hidden tracking,
marketplace submission, package publishing, v0.7 release gating, payment
handling, paid CTA, or hosted/team/enterprise readiness claims.
