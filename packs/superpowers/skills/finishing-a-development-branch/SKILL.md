---
name: finishing-a-development-branch
description: "Finish completed branch work by verifying status and presenting safe integration, PR, cleanup, or discard options."
version: 1.0.0
category: git-workflow
tags: "[git, branch, merge, pull-request, cleanup, completion]"
status: published
confidence: 0.8
source: imported
source_pack: superpowers
source_repo: "https://github.com/obra/superpowers"
source_path: skills\finishing-a-development-branch\SKILL.md
source_sha256: 5c8d4b59aedb14c94e2f5d787a3265e858e8f53d4ceffe7ff1c15878a52b0e91
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:15:16Z"
unlimited_skills_agent_adapter: action-schema-agent-v1
---

## When to Use

Use when implementation work is complete, tests pass, and the agent needs to decide with the user how to integrate or clean up the branch/worktree.

## When Not to Use

Do not use while implementation or tests are still failing, when there is no branch/worktree decision to make, or when the user has already specified the exact integration action.

## Required Context

Current branch, worktree location, git status, test evidence, remote/PR state if relevant, and whether the worktree is harness-owned or user-owned.

## Procedure

1. Run or confirm fresh verification before offering completion options.
2. Inspect git status, current branch, remotes, and whether this is a worktree.
3. Summarize what is complete and what evidence proves it.
4. Present structured options such as merge locally, create/update PR, keep branch for later, or discard with explicit confirmation.
5. For cleanup, move to the main repo root before removing worktrees and never delete user work without clear confirmation.
6. Perform only the option the user chooses and verify the resulting git state.

## Tools

1. Git CLI
2. Test/verification commands
3. GitHub/PR tooling when available

## Expected Output

A user-approved integration or cleanup action with final git/test evidence, or a clear set of options awaiting user choice.

## Known Traps

1. Offering options before tests pass.
2. Asking open-ended "what next" instead of presenting structured choices.
3. Removing a worktree from inside itself.
4. Deleting a branch before removing its worktree.
5. Cleaning up harness-owned worktrees or discarding work without explicit confirmation.

## Examples of Successful Execution

1. After all tests pass, the agent presents four options: merge and cleanup, create PR and keep worktree, keep branch, or discard. The user chooses PR, so the agent pushes and reports the PR URL without deleting the worktree.

## Regression Tests

1. Fresh verification evidence exists before completion options.
2. Git status is clean or known changes are explained.
3. Discard actions require explicit typed confirmation.
4. Final state matches the selected option.

## Original Skill Body

## Overview

Guide completion of development work by presenting clear options and handling chosen workflow.

**Core principle:** Verify tests → Detect environment → Present options → Execute choice → Clean up.

**Announce at start:** "I'm using the finishing-a-development-branch skill to complete this work."

## Step 1: Verify Tests

**Before presenting options, verify tests pass:**

```bash

## Run project's test suite

npm test / cargo test / pytest / go test ./...
```

**If tests fail:**
```
Tests failing (<N> failures). Must fix before completing:

[Show failures]

Cannot proceed with merge/PR until tests pass.
```

Stop. Don't proceed to Step 2.

**If tests pass:** Continue to Step 2.

## Step 2: Detect Environment

**Determine workspace state before presenting options:**

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
```

This determines which menu to show and how cleanup works:

| State | Menu | Cleanup |
|-------|------|---------|
| `GIT_DIR == GIT_COMMON` (normal repo) | Standard 4 options | No worktree to clean up |
| `GIT_DIR != GIT_COMMON`, named branch | Standard 4 options | Provenance-based (see Step 6) |
| `GIT_DIR != GIT_COMMON`, detached HEAD | Reduced 3 options (no merge) | No cleanup (externally managed) |

## Step 3: Determine Base Branch

```bash

## Try common base branches

git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null
```

Or ask: "This branch split from main - is that correct?"

## Step 4: Present Options

**Normal repo and named-branch worktree — present exactly these 4 options:**

```
Implementation complete. What would you like to do?

1. Merge back to <base-branch> locally
2. Push and create a Pull Request
3. Keep the branch as-is (I'll handle it later)
4. Discard this work

Which option?
```

**Detached HEAD — present exactly these 3 options:**

```
Implementation complete. You're on a detached HEAD (externally managed workspace).

1. Push as new branch and create a Pull Request
2. Keep as-is (I'll handle it later)
3. Discard this work

Which option?
```

**Don't add explanation** - keep options concise.

## Option 1: Merge Locally

```bash

## Get main repo root for CWD safety

MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"

## Merge first — verify success before removing anything

git checkout <base-branch>
git pull
git merge <feature-branch>

## Verify tests on merged result

<test command>

## Only after merge succeeds: cleanup worktree (Step 6), then delete branch

```

Then: Cleanup worktree (Step 6), then delete branch:

```bash
git branch -d <feature-branch>
```

## Option 2: Push and Create PR

```bash

## Push branch

git push -u origin <feature-branch>

## Create PR

gh pr create --title "<title>" --body "$(cat <<'EOF'

## Summary

<2-3 bullets of what changed>

## Test Plan

- [ ] <verification steps>
EOF
)"
```

**Do NOT clean up worktree** — user needs it alive to iterate on PR feedback.

## Option 3: Keep As-Is

Report: "Keeping branch <name>. Worktree preserved at <path>."

**Don't cleanup worktree.**

## Option 4: Discard

**Confirm first:**
```
This will permanently delete:
- Branch <name>
- All commits: <commit-list>
- Worktree at <path>

Type 'discard' to confirm.
```

Wait for exact confirmation.

If confirmed:
```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
```

Then: Cleanup worktree (Step 6), then force-delete branch:
```bash
git branch -D <feature-branch>
```

## Step 6: Cleanup Workspace

**Only runs for Options 1 and 4.** Options 2 and 3 always preserve the worktree.

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
WORKTREE_PATH=$(git rev-parse --show-toplevel)
```

**If `GIT_DIR == GIT_COMMON`:** Normal repo, no worktree to clean up. Done.

**If worktree path is under `.worktrees/`, `worktrees/`, or `~/.config/superpowers/worktrees/`:** Superpowers created this worktree — we own cleanup.

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
git worktree remove "$WORKTREE_PATH"
git worktree prune  # Self-healing: clean up any stale registrations
```

**Otherwise:** The host environment (harness) owns this workspace. Do NOT remove it. If your platform provides a workspace-exit tool, use it. Otherwise, leave the workspace in place.

## Quick Reference

| Option | Merge | Push | Keep Worktree | Cleanup Branch |
|--------|-------|------|---------------|----------------|
| 1. Merge locally | yes | - | - | yes |
| 2. Create PR | - | yes | yes | - |
| 3. Keep as-is | - | - | yes | - |
| 4. Discard | - | - | - | yes (force) |

## Red Flags

**Never:**
- Proceed with failing tests
- Merge without verifying tests on result
- Delete work without confirmation
- Force-push without explicit request
- Remove a worktree before confirming merge success
- Clean up worktrees you didn't create (provenance check)
- Run `git worktree remove` from inside the worktree

**Always:**
- Verify tests before offering options
- Detect environment before presenting menu
- Present exactly 4 options (or 3 for detached HEAD)
- Get typed confirmation for Option 4
- Clean up worktree for Options 1 & 4 only
- `cd` to main repo root before worktree removal
- Run `git worktree prune` after removal
