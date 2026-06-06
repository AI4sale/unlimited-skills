---
name: nanoclaw-repl
description: "Operate and extend NanoClaw v2, ECC's zero-dependency session-aware REPL built on claude -p."
version: 1.0.0
category: ecc
tags: "[nanoclaw-repl, operate, extend, nanoclaw, ecc, zero-dependency, session-aware, repl]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\nanoclaw-repl\SKILL.md
source_sha256: a917d56baef854638fd6a33c9d9ce4f819d3dd128286514ed28807d911935d27
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:58Z"
---

## When to Use

Operate and extend NanoClaw v2, ECC's zero-dependency session-aware REPL built on claude -p.

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

## NanoClaw REPL

Use this skill when running or extending `scripts/claw.js`.

## Capabilities

- persistent markdown-backed sessions
- model switching with `/model`
- dynamic skill loading with `/load`
- session branching with `/branch`
- cross-session search with `/search`
- history compaction with `/compact`
- export to md/json/txt with `/export`
- session metrics with `/metrics`

## Operating Guidance

1. Keep sessions task-focused.
2. Branch before high-risk changes.
3. Compact after major milestones.
4. Export before sharing or archival.

## Extension Rules

- keep zero external runtime dependencies
- preserve markdown-as-database compatibility
- keep command handlers deterministic and local
