---
name: unified-notifications-ops
description: "Operate notifications as one ECC-native workflow across GitHub, Linear, desktop alerts, hooks, and connected communication surfaces. Use when the real problem is alert routing, deduplication, escalation, or inbox collapse."
version: 1.0.0
category: ecc
tags: "[unified-notifications-ops, operate, notifications, one, ecc-native, workflow, across, github]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\unified-notifications-ops\SKILL.md
source_sha256: d9c2d607662189c87934e563d62a21e77e39ea54cbdcd9117e2c726fbff65ce1
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:15:00Z"
---

## When to Use

- the user wants a unified notification lane across GitHub, Linear, local hooks, desktop alerts, chat, or email
- CI failures, review requests, issue updates, and operator events are arriving in disconnected places
- the current setup creates noise instead of action
- the user wants to consolidate overlapping notification branches or backlog proposals into one ECC-native lane
- the workspace already has hooks, MCPs, or connected tools, but no coherent notification policy

## When Not to Use

Not specified by the source skill.

## Required Context

Not specified by the source skill.

## Procedure

1. Read the preserved source skill body below.
2. Apply only the parts relevant to the current task.
3. Verify the result using the regression tests or project-specific checks.

## Tools

Not specified by the source skill.

## Expected Output

Not specified by the source skill.

## Known Traps

Not specified by the source skill.

## Examples of Successful Execution

Not specified by the source skill.

## Regression Tests

Not specified by the source skill.

## Original Skill Body

## Unified Notifications Ops

Use this skill when the real problem is not a missing ping. The real problem is a fragmented notification system.

The job is to turn scattered events into one operator surface with:
- clear severity
- clear ownership
- clear routing
- clear follow-up action

## Preferred Surface

Start from what already exists:
- GitHub issues, PRs, reviews, comments, and CI
- Linear issue/project movement
- local hook events and session lifecycle signals
- desktop notification primitives
- connected email/chat surfaces when they actually exist

Prefer ECC-native orchestration over telling the user to adopt a separate notification product.

## Non-Negotiable Rules

- never expose tokens, secrets, webhook secrets, or internal identifiers
- separate:
  - event source
  - severity
  - routing channel
  - operator action
- default to digest-first when interruption cost is unclear
- do not fan out every event to every channel
- if the real fix is better issue triage, hook policy, or project flow, say so explicitly

## Event Pipeline

Treat the lane as:

1. **Capture** the event
2. **Classify** urgency and owner
3. **Route** to the correct channel
4. **Collapse** duplicates and low-signal churn
5. **Attach** the next operator action

The goal is fewer, better notifications.

## Default Severity Model

| Class | Examples | Default handling |
| --- | --- | --- |
| Critical | broken default-branch CI, security issue, blocked release, failed deploy | interrupt now |
| High | review requested, failing PR, owner-blocking handoff | same-day alert |
| Medium | issue state changes, notable comments, backlog movement | digest or queue |
| Low | repeat successes, routine churn, redundant lifecycle markers | suppress or fold |

If the workspace has no severity model, build one before proposing automation.

## 1. Inventory the current surface

List:
- event sources
- current channels
- existing hooks/scripts that emit alerts
- duplicate paths for the same event
- silent failure cases where important things are not being surfaced

Call out what ECC already owns.

## 2. Decide what deserves interruption

For each event family, answer:
- who needs to know?
- how fast do they need to know?
- should this interrupt, batch, or just log?

Use these defaults:
- interrupt for release, CI, security, and owner-blocking events
- digest for medium-signal updates
- log-only for telemetry and low-signal lifecycle markers

## 3. Collapse duplicates before adding channels

Look for:
- the same PR event appearing in GitHub, Linear, and local logs
- repeated hook notifications for the same failure
- comments or status churn that should be summarized instead of forwarded raw
- channels that duplicate each other without adding a better action path

Prefer:
- one canonical summary
- one owner
- one primary channel
- one fallback path

## 4. Design the ECC-native workflow

For each real notification need, define:
- **source**
- **gate**
- **shape**: immediate alert, digest, queue, or dashboard-only
- **channel**
- **action**

If ECC already has the primitive, prefer:
- a skill for operator triage
- a hook for automatic emission/enforcement
- an agent for delegated classification
- an MCP/connector only when a real bridge is missing

## 5. Return an action-biased design

End with:
- what to keep
- what to suppress
- what to merge
- what ECC should wrap next

## Output Format

```text
CURRENT SURFACE
- sources
- channels
- duplicates
- gaps

EVENT MODEL
- critical
- high
- medium
- low

ROUTING PLAN
- source -> channel
- why
- operator owner

CONSOLIDATION
- suppress
- merge
- canonical summaries

NEXT ECC MOVE
- skill / hook / agent / MCP
- exact workflow to build next
```

## Recommendation Rules

- prefer one strong lane over many weak ones
- prefer digests for medium and low-signal updates
- prefer hooks when the signal should emit automatically
- prefer operator skills when the work is triage, routing, and review-first decision-making
- prefer `project-flow-ops` when the root cause is backlog / PR coordination rather than alerts
- prefer `workspace-surface-audit` when the user first needs a source inventory
- if desktop notifications are enough, do not invent an unnecessary external bridge

## Good Use Cases

- "We have GitHub, Linear, and local hook alerts, but no single operator flow"
- "Our CI failures are noisy and people ignore them"
- "I want one notification policy across Claude, OpenCode, and Codex surfaces"
- "Figure out what should interrupt versus land in a digest"
- "Collapse overlapping notification PR ideas into one canonical ECC lane"

## Related Skills

- `workspace-surface-audit`
- `project-flow-ops`
- `github-ops`
- `knowledge-ops`
- `customer-billing-ops` when the notification pain is billing/customer operations rather than engineering
