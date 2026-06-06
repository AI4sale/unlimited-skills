---
name: requesting-code-review
description: "Request focused code review after meaningful work, providing requirements, diff range, and verification context."
version: 1.0.0
category: code-review
tags: "[review, subagent, quality, requirements, diff]"
status: published
confidence: 0.8
source: imported
source_pack: superpowers
source_repo: "https://github.com/obra/superpowers"
source_path: skills\requesting-code-review\SKILL.md
source_sha256: 5a3a44a3667800e2dc836829c6b92fada51e6dc58ac144ec05fe59f47d6bcd84
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:15:16Z"
unlimited_skills_agent_adapter: action-schema-agent-v1
---

## When to Use

Use after completing a task, major feature, or merge-ready change when independent review should verify correctness, requirements compliance, and code quality.

## When Not to Use

Do not use before the work is in a coherent reviewable state, for tiny changes where the user asked for direct completion, or when no reviewer/subagent capability exists and a self-review is more appropriate.

## Required Context

Task requirements or plan, base SHA, head SHA, changed files, verification already run, and specific review focus areas.

## Procedure

1. Ensure the work compiles/tests enough to be reviewable.
2. Identify the base and head revisions or diff range.
3. Prepare a concise review brief with what changed, why, requirements, and known risk areas.
4. Dispatch a reviewer/subagent if available, or perform a structured self-review if not.
5. Classify returned issues by severity and fix important correctness/security/test gaps before continuing.
6. Re-run relevant verification after fixes and record the review outcome.

## Tools

1. Git CLI for base/head/diff
2. Subagent/reviewer capability when available
3. Test/lint/typecheck commands

## Expected Output

A focused review result with strengths, issues, severity, fixes applied, and verification after addressing accepted findings.

## Known Traps

1. Requesting review without requirements or diff range.
2. Ignoring important review findings.
3. Treating review as a substitute for running tests.
4. Continuing to the next task before resolving correctness issues.

## Examples of Successful Execution

1. After implementing a plan task, the agent computes BASE_SHA and HEAD_SHA, dispatches a reviewer with requirements and changed files, fixes an important issue, then proceeds to the next task.

## Regression Tests

1. Review request includes requirements and diff range.
2. Important/high findings are addressed or explicitly rejected with evidence.
3. Relevant verification was rerun after fixes.
4. The final summary includes review outcome.

## Original Skill Body

## Requesting Code Review

Dispatch a code reviewer subagent to catch issues before they cascade. The reviewer gets precisely crafted context for evaluation — never your session's history. This keeps the reviewer focused on the work product, not your thought process, and preserves your own context for continued work.

**Core principle:** Review early, review often.

## When to Request Review

**Mandatory:**
- After each task in subagent-driven development
- After completing major feature
- Before merge to main

**Optional but valuable:**
- When stuck (fresh perspective)
- Before refactoring (baseline check)
- After fixing complex bug

## How to Request

**1. Get git SHAs:**
```bash
BASE_SHA=$(git rev-parse HEAD~1)  # or origin/main
HEAD_SHA=$(git rev-parse HEAD)
```

**2. Dispatch code reviewer subagent:**

Use Task tool with `general-purpose` type, fill template at `code-reviewer.md`

**Placeholders:**
- `{DESCRIPTION}` - Brief summary of what you built
- `{PLAN_OR_REQUIREMENTS}` - What it should do
- `{BASE_SHA}` - Starting commit
- `{HEAD_SHA}` - Ending commit

**3. Act on feedback:**
- Fix Critical issues immediately
- Fix Important issues before proceeding
- Note Minor issues for later
- Push back if reviewer is wrong (with reasoning)

## Integration with Workflows

**Subagent-Driven Development:**
- Review after EACH task
- Catch issues before they compound
- Fix before moving to next task

**Executing Plans:**
- Review after each task or at natural checkpoints
- Get feedback, apply, continue

**Ad-Hoc Development:**
- Review before merge
- Review when stuck

## Red Flags

**Never:**
- Skip review because "it's simple"
- Ignore Critical issues
- Proceed with unfixed Important issues
- Argue with valid technical feedback

**If reviewer wrong:**
- Push back with technical reasoning
- Show code/tests that prove it works
- Request clarification

See template at: requesting-code-review/code-reviewer.md
