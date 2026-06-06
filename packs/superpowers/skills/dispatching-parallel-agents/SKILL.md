---
name: dispatching-parallel-agents
description: Dispatch independent investigations or implementation tasks to separate agents and synthesize their results.
version: 1.0.0
category: orchestration
tags: "[subagents, parallelism, debugging, task-dispatch, coordination]"
status: published
confidence: 0.8
source: imported
source_pack: superpowers
source_repo: "https://github.com/obra/superpowers"
source_path: skills\dispatching-parallel-agents\SKILL.md
source_sha256: 76806091c7f923ba2596546b19cccd98a08e57a68745df77c3a7b998fe838e2b
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:15:16Z"
unlimited_skills_agent_adapter: action-schema-agent-v1
---

## When to Use

Use when there are multiple independent failures, subsystems, or tasks that can be investigated without shared state or sequential dependencies. Best when each agent can receive a narrow problem statement, relevant files/errors, and produce a bounded result.

## When Not to Use

Do not use when failures likely share one root cause, when a single fix may resolve several symptoms, when agents would edit the same files/resources, or when the problem is still too exploratory to divide safely.

## Required Context

List the independent problem domains, relevant errors/files for each, known shared state, and whether subagent/task-dispatch tooling is available in the current harness.

## Procedure

1. Confirm the work items are truly independent and can run without stepping on shared state.
2. Create one narrow brief per agent with exact files, errors, commands, and expected deliverable.
3. Dispatch agents in parallel only when the harness supports it; otherwise run them sequentially with isolated context.
4. Collect each result and verify whether it includes evidence, not just conclusions.
5. Synthesize findings into a single plan or set of fixes, resolving conflicts before editing shared code.
6. Run final verification across the whole system after integrating results.

## Tools

1. Subagent or task-dispatch capability when available
2. File and test inspection tools
3. Shell/test commands for final verification

## Expected Output

A set of scoped agent findings or patches plus a synthesized conclusion that identifies which fixes to apply and how final verification was performed.

## Known Traps

1. Dispatching broad tasks such as "fix all tests" instead of narrow scopes.
2. Parallel agents editing the same files or using the same mutable resource.
3. Assuming independence before checking whether failures share one root cause.
4. Accepting agent conclusions without evidence or final integrated verification.

## Examples of Successful Execution

1. Three unrelated test files fail in separate modules; one agent investigates each file with its exact failure output, then the main agent merges the findings and runs the full test suite.

## Regression Tests

1. Each dispatched task has a narrow scope and includes relevant evidence.
2. No two agents were assigned conflicting writes to the same files.
3. The final answer synthesizes all agent outputs instead of pasting them blindly.
4. A full-system verification command was run after integration.

## Original Skill Body

## Overview

You delegate tasks to specialized agents with isolated context. By precisely crafting their instructions and context, you ensure they stay focused and succeed at their task. They should never inherit your session's context or history — you construct exactly what they need. This also preserves your own context for coordination work.

When you have multiple unrelated failures (different test files, different subsystems, different bugs), investigating them sequentially wastes time. Each investigation is independent and can happen in parallel.

**Core principle:** Dispatch one agent per independent problem domain. Let them work concurrently.

## 1. Identify Independent Domains

Group failures by what's broken:
- File A tests: Tool approval flow
- File B tests: Batch completion behavior
- File C tests: Abort functionality

Each domain is independent - fixing tool approval doesn't affect abort tests.

## 2. Create Focused Agent Tasks

Each agent gets:
- **Specific scope:** One test file or subsystem
- **Clear goal:** Make these tests pass
- **Constraints:** Don't change other code
- **Expected output:** Summary of what you found and fixed

## 3. Dispatch in Parallel

```typescript
// In Claude Code / AI environment
Task("Fix agent-tool-abort.test.ts failures")
Task("Fix batch-completion-behavior.test.ts failures")
Task("Fix tool-approval-race-conditions.test.ts failures")
// All three run concurrently
```

## 4. Review and Integrate

When agents return:
- Read each summary
- Verify fixes don't conflict
- Run full test suite
- Integrate all changes

## Agent Prompt Structure

Good agent prompts are:
1. **Focused** - One clear problem domain
2. **Self-contained** - All context needed to understand the problem
3. **Specific about output** - What should the agent return?

```markdown
Fix the 3 failing tests in src/agents/agent-tool-abort.test.ts:

1. "should abort tool with partial output capture" - expects 'interrupted at' in message
2. "should handle mixed completed and aborted tools" - fast tool aborted instead of completed
3. "should properly track pendingToolCount" - expects 3 results but gets 0

These are timing/race condition issues. Your task:

1. Read the test file and understand what each test verifies
2. Identify root cause - timing issues or actual bugs?
3. Fix by:
   - Replacing arbitrary timeouts with event-based waiting
   - Fixing bugs in abort implementation if found
   - Adjusting test expectations if testing changed behavior

Do NOT just increase timeouts - find the real issue.

Return: Summary of what you found and what you fixed.
```

## Real Example from Session

**Scenario:** 6 test failures across 3 files after major refactoring

**Failures:**
- agent-tool-abort.test.ts: 3 failures (timing issues)
- batch-completion-behavior.test.ts: 2 failures (tools not executing)
- tool-approval-race-conditions.test.ts: 1 failure (execution count = 0)

**Decision:** Independent domains - abort logic separate from batch completion separate from race conditions

**Dispatch:**
```
Agent 1 → Fix agent-tool-abort.test.ts
Agent 2 → Fix batch-completion-behavior.test.ts
Agent 3 → Fix tool-approval-race-conditions.test.ts
```

**Results:**
- Agent 1: Replaced timeouts with event-based waiting
- Agent 2: Fixed event structure bug (threadId in wrong place)
- Agent 3: Added wait for async tool execution to complete

**Integration:** All fixes independent, no conflicts, full suite green

**Time saved:** 3 problems solved in parallel vs sequentially

## Key Benefits

1. **Parallelization** - Multiple investigations happen simultaneously
2. **Focus** - Each agent has narrow scope, less context to track
3. **Independence** - Agents don't interfere with each other
4. **Speed** - 3 problems solved in time of 1

## Real-World Impact

From debugging session (2025-10-03):
- 6 failures across 3 files
- 3 agents dispatched in parallel
- All investigations completed concurrently
- All fixes integrated successfully
- Zero conflicts between agent changes
