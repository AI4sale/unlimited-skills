---
name: continuous-agent-loop
description: "Patterns for continuous autonomous agent loops with quality gates, evals, and recovery controls."
version: 1.0.0
category: ecc
tags: "[continuous-agent-loop, patterns, continuous, autonomous, agent, loops, quality, gates]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\continuous-agent-loop\SKILL.md
source_sha256: b557889be2db327a966a30410825f6a461b5583a29eb009b9123e6ca3f766c12
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:54Z"
---

## When to Use

Patterns for continuous autonomous agent loops with quality gates, evals, and recovery controls.

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

- loop churn without measurable progress
- repeated retries with same root cause
- merge queue stalls
- cost drift from unbounded escalation

## Examples of Successful Execution

Not specified by the source skill.

## Regression Tests

Not specified by the source skill.

## Original Skill Body

## Continuous Agent Loop

This is the v1.8+ canonical loop skill name. It supersedes `autonomous-loops` while keeping compatibility for one release.

## Loop Selection Flow

```text
Start
  |
  +-- Need strict CI/PR control? -- yes --> continuous-pr
  |
  +-- Need RFC decomposition? -- yes --> rfc-dag
  |
  +-- Need exploratory parallel generation? -- yes --> infinite
  |
  +-- default --> sequential
```

## Combined Pattern

Recommended production stack:
1. RFC decomposition (`ralphinho-rfc-pipeline`)
2. quality gates (`plankton-code-quality` + `/quality-gate`)
3. eval loop (`eval-harness`)
4. session persistence (`nanoclaw-repl`)

## Recovery

- freeze loop
- run `/harness-audit`
- reduce scope to failing unit
- replay with explicit acceptance criteria
