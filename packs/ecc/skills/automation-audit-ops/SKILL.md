---
name: automation-audit-ops
description: "Evidence-first automation inventory and overlap audit workflow for ECC. Use when the user wants to know which jobs, hooks, connectors, MCP servers, or wrappers are live, broken, redundant, or missing before fixing anything."
version: 1.0.0
category: ecc
tags: "[automation-audit-ops, evidence-first, automation, inventory, overlap, audit, workflow, ecc.]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\automation-audit-ops\SKILL.md
source_sha256: cb4f49604a9dd0eaebe2104e94aa160477f9af81071f7f8726c46128a4b0ecb7
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:54Z"
---

## When to Use

- user asks "what automations do I have", "what is live", "what is broken", or "what overlaps"
- the task spans cron jobs, GitHub Actions, local hooks, MCP servers, connectors, wrappers, or app integrations
- the user wants to know what was ported from another agent system and what still needs to be rebuilt inside ECC
- the workspace has accumulated multiple ways to do the same thing and the user wants one canonical lane

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

- do not answer from memory when the live inventory can be read
- do not treat "present in config" as "working"
- do not fix lower-value redundancy before naming the broken high-signal path
- do not widen the task into a repo rewrite if the user asked for inventory first

## Examples of Successful Execution

Not specified by the source skill.

## Regression Tests

- important claims cite a live proof path
- each surfaced automation is labeled with a clear live-state category
- the final recommendation distinguishes keep / merge / cut / fix-next

## Original Skill Body

## Automation Audit Ops

Use this when the user asks what automations are live, which jobs are broken, where overlap exists, or what tooling and connectors are actually doing useful work right now.

This is an audit-first operator skill. The job is to produce an evidence-backed inventory and a keep / merge / cut / fix-next recommendation set before rewriting anything.

## Skill Stack

Pull these ECC-native skills into the workflow when relevant:

- `workspace-surface-audit` for connector, MCP, hook, and app inventory
- `knowledge-ops` when the audit needs to reconcile live repo truth with durable context
- `github-ops` when the answer depends on CI, scheduled workflows, issues, or PR automation
- `ecc-tools-cost-audit` when the real problem is webhook fanout, queued jobs, or billing burn in the sibling app repo
- `research-ops` when local inventory must be compared against current platform support or public docs
- `verification-loop` for proving post-fix state instead of relying on assumed recovery

## Guardrails

- start read-only unless the user explicitly asked for fixes
- separate:
  - configured
  - authenticated
  - recently verified
  - stale or broken
  - missing entirely
- do not claim a tool is live just because a skill or config references it
- do not merge or delete overlapping surfaces until the evidence table exists

## 1. Inventory the real surface

Read the current live surface before theorizing:

- repo hooks and local hook scripts
- GitHub Actions and scheduled workflows
- MCP configs and enabled servers
- connector- or app-backed integrations
- wrapper scripts and repo-specific automation entrypoints

Group them by surface:

- local runtime
- repo CI / automation
- connected external systems
- messaging / notifications
- billing / customer operations
- research / monitoring

## 2. Classify each item by live state

For every surfaced automation, mark:

- configured
- authenticated
- recently verified
- stale or broken
- missing

Then classify the problem type:

- active breakage
- auth outage
- stale status
- overlap or redundancy
- missing capability

## 3. Trace the proof path

Back every important claim with a concrete source:

- file path
- workflow run
- hook log
- config entry
- recent command output
- exact failure signature

If the current state is ambiguous, say so directly instead of pretending the audit is complete.

## 4. End with keep / merge / cut / fix-next

For each overlapping or suspect surface, return one call:

- keep
- merge
- cut
- fix next

The value is in collapsing noisy automation into one canonical ECC lane, not in preserving every historical path.

## Output Format

```text
CURRENT SURFACE
- automation
- source
- live state
- proof

FINDINGS
- active breakage
- overlap
- stale status
- missing capability

RECOMMENDATION
- keep
- merge
- cut
- fix next

NEXT ECC MOVE
- exact skill / hook / workflow / app lane to strengthen
```
