---
name: executing-plans
description: Execute an approved written implementation plan task by task with verification checkpoints.
version: 1.0.0
category: implementation
tags: "[plan-execution, implementation, todo, verification, checkpoints]"
status: published
confidence: 0.8
source: imported
source_pack: superpowers
source_repo: "https://github.com/obra/superpowers"
source_path: skills\executing-plans\SKILL.md
source_sha256: e2102f11631433939f162d383d769f8257d859d6639e0e14969cda3ef0a95eca
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:15:16Z"
unlimited_skills_agent_adapter: action-schema-agent-v1
---

## When to Use

Use when a written plan already exists and the user wants it executed. Use for multi-step implementation work where tasks can be tracked, verified, and reported as completed.

## When Not to Use

Do not use before a plan exists, when the plan is unapproved or technically questionable, or when tasks are mostly independent and the harness supports subagent-driven development better.

## Required Context

Plan file/path, repository state, test commands, any open questions or risks in the plan, and whether subagents are available.

## Procedure

1. Read the complete plan before editing code.
2. Review the plan critically and raise concerns before starting if steps are unclear, unsafe, or inconsistent.
3. Create a task list from the plan and mark only the current task in progress.
4. Execute each task exactly enough to satisfy the plan without unrelated refactors.
5. Run the verification specified for each task before marking it complete.
6. After all tasks pass, run final plan-level verification and summarize completed work with evidence.

## Tools

1. Task/todo tracking
2. File editing tools
3. Shell/test commands
4. Git status/diff inspection

## Expected Output

Implemented plan tasks, passing verification evidence, and a concise completion report tied back to the original plan.

## Known Traps

1. Skipping critical review of a flawed plan.
2. Marking tasks complete before their verification passes.
3. Drifting into unrelated improvements not requested by the plan.
4. Continuing when the plan has unresolved ambiguity that needs user input.

## Examples of Successful Execution

1. The agent reads docs/superpowers/plans/foo.md, raises one concern, receives clarification, executes tasks one by one, runs each test command, and reports final evidence.

## Regression Tests

1. Every completed task has corresponding verification output.
2. No unplanned files were changed without justification.
3. The final summary maps changes back to plan items.
4. Git diff/status was inspected before completion.

## Original Skill Body

## Overview

Load plan, review critically, execute all tasks, report when complete.

**Announce at start:** "I'm using the executing-plans skill to implement this plan."

**Note:** Tell your human partner that Superpowers works much better with access to subagents. The quality of its work will be significantly higher if run on a platform with subagent support (such as Claude Code or Codex). If subagents are available, use superpowers:subagent-driven-development instead of this skill.

## Step 1: Load and Review Plan

1. Read plan file
2. Review critically - identify any questions or concerns about the plan
3. If concerns: Raise them with your human partner before starting
4. If no concerns: Create TodoWrite and proceed

## Step 2: Execute Tasks

For each task:
1. Mark as in_progress
2. Follow each step exactly (plan has bite-sized steps)
3. Run verifications as specified
4. Mark as completed

## Step 3: Complete Development

After all tasks complete and verified:
- Announce: "I'm using the finishing-a-development-branch skill to complete this work."
- **REQUIRED SUB-SKILL:** Use superpowers:finishing-a-development-branch
- Follow that skill to verify tests, present options, execute choice

## When to Stop and Ask for Help

**STOP executing immediately when:**
- Hit a blocker (missing dependency, test fails, instruction unclear)
- Plan has critical gaps preventing starting
- You don't understand an instruction
- Verification fails repeatedly

**Ask for clarification rather than guessing.**

## When to Revisit Earlier Steps

**Return to Review (Step 1) when:**
- Partner updates the plan based on your feedback
- Fundamental approach needs rethinking

**Don't force through blockers** - stop and ask.

## Remember

- Review plan critically first
- Follow plan steps exactly
- Don't skip verifications
- Reference skills when plan says to
- Stop when blocked, don't guess
- Never start implementation on main/master branch without explicit user consent

## Integration

**Required workflow skills:**
- **superpowers:using-git-worktrees** - Ensures isolated workspace (creates one or verifies existing)
- **superpowers:writing-plans** - Creates the plan this skill executes
- **superpowers:finishing-a-development-branch** - Complete development after all tasks
