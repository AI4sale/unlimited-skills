---
name: git-workflow
description: "Git workflow patterns including branching strategies, commit conventions, merge vs rebase, conflict resolution, and collaborative development best practices for teams of all sizes."
version: 1.0.0
category: ecc
tags: "[git-workflow, git, workflow, patterns, including, branching, strategies, commit]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\git-workflow\SKILL.md
source_sha256: a67d04fc9f1dde4a249bf19a1ecb064f048410083d7dd232e7c2b733db43407a
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:56Z"
---

## When to Use

- Setting up Git workflow for a new project
- Deciding on branching strategy (GitFlow, trunk-based, GitHub flow)
- Writing commit messages and PR descriptions
- Resolving merge conflicts
- Managing releases and version tags
- Onboarding new team members to Git practices

## When Not to Use

```

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

- [ ] Code follows project style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex logic
- [ ] Documentation updated
- [ ] No new warnings introduced
- [ ] Tests pass locally
- [ ] Related issues linked

Closes #123
```

## Original Skill Body

## Git Workflow Patterns

Best practices for Git version control, branching strategies, and collaborative development.

## GitHub Flow (Simple, Recommended for Most)

Best for continuous deployment and small-to-medium teams.

```
main (protected, always deployable)
  │
  ├── feature/user-auth      → PR → merge to main
  ├── feature/payment-flow   → PR → merge to main
  └── fix/login-bug          → PR → merge to main
```

**Rules:**
- `main` is always deployable
- Create feature branches from `main`
- Open Pull Request when ready for review
- After approval and CI passes, merge to `main`
- Deploy immediately after merge

## Trunk-Based Development (High-Velocity Teams)

Best for teams with strong CI/CD and feature flags.

```
main (trunk)
  │
  ├── short-lived feature (1-2 days max)
  ├── short-lived feature
  └── short-lived feature
```

**Rules:**
- Everyone commits to `main` or very short-lived branches
- Feature flags hide incomplete work
- CI must pass before merge
- Deploy multiple times per day

## GitFlow (Complex, Release-Cycle Driven)

Best for scheduled releases and enterprise projects.

```
main (production releases)
  │
  └── develop (integration branch)
        │
        ├── feature/user-auth
        ├── feature/payment
        │
        ├── release/1.0.0    → merge to main and develop
        │
        └── hotfix/critical  → merge to main and develop
```

**Rules:**
- `main` contains production-ready code only
- `develop` is the integration branch
- Feature branches from `develop`, merge back to `develop`
- Release branches from `develop`, merge to `main` and `develop`
- Hotfix branches from `main`, merge to both `main` and `develop`

## When to Use Which

| Strategy | Team Size | Release Cadence | Best For |
|----------|-----------|-----------------|----------|
| GitHub Flow | Any | Continuous | SaaS, web apps, startups |
| Trunk-Based | 5+ experienced | Multiple/day | High-velocity teams, feature flags |
| GitFlow | 10+ | Scheduled | Enterprise, regulated industries |

## Conventional Commits Format

```
<type>(<scope>): <subject>

[optional body]

[optional footer(s)]
```

## Types

| Type | Use For | Example |
|------|---------|---------|
| `feat` | New feature | `feat(auth): add OAuth2 login` |
| `fix` | Bug fix | `fix(api): handle null response in user endpoint` |
| `docs` | Documentation | `docs(readme): update installation instructions` |
| `style` | Formatting, no code change | `style: fix indentation in login component` |
| `refactor` | Code refactoring | `refactor(db): extract connection pool to module` |
| `test` | Adding/updating tests | `test(auth): add unit tests for token validation` |
| `chore` | Maintenance tasks | `chore(deps): update dependencies` |
| `perf` | Performance improvement | `perf(query): add index to users table` |
| `ci` | CI/CD changes | `ci: add PostgreSQL service to test workflow` |
| `revert` | Revert previous commit | `revert: revert "feat(auth): add OAuth2 login"` |

## Good vs Bad Examples

```

## BAD: Vague, no context

git commit -m "fixed stuff"
git commit -m "updates"
git commit -m "WIP"

## GOOD: Clear, specific, explains why

git commit -m "fix(api): retry requests on 503 Service Unavailable

The external API occasionally returns 503 errors during peak hours.
Added exponential backoff retry logic with max 3 attempts.

Closes #123"
```

## Commit Message Template

Create `.gitmessage` in repo root:

```

## Subject: imperative mood, no period, max 50 chars

#

## [optional footer] - Breaking changes, closes #issue

```

Enable with: `git config commit.template .gitmessage`

## Merge (Preserves History)

```bash

## Creates a merge commit

git checkout main
git merge feature/user-auth

## * main commits

```

**Use when:**
- Merging feature branches into `main`
- You want to preserve exact history
- Multiple people worked on the branch
- The branch has been pushed and others may have based work on it

## Rebase (Linear History)

```bash

## Rewrites feature commits onto target branch

git checkout feature/user-auth
git rebase main

## * main commits

```

**Use when:**
- Updating your local feature branch with latest `main`
- You want a linear, clean history
- The branch is local-only (not pushed)
- You're the only one working on the branch

## Rebase Workflow

```bash

## Update feature branch with latest main (before PR)

git checkout feature/user-auth
git fetch origin
git rebase origin/main

## Force push (only if you're the only contributor)

git push --force-with-lease origin feature/user-auth
```

## When NOT to Rebase

```

## NEVER rebase branches that:

- Have been pushed to a shared repository
- Other people have based work on
- Are protected branches (main, develop)
- Are already merged

## Why: Rebase rewrites history, breaking others' work

```

## PR Title Format

```
<type>(<scope>): <description>

Examples:
feat(auth): add SSO support for enterprise users
fix(api): resolve race condition in order processing
docs(api): add OpenAPI specification for v2 endpoints
```

## PR Description Template

```markdown

## What

Brief description of what this PR does.

## Why

Explain the motivation and context.

## How

Key implementation details worth highlighting.

## Testing

- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing performed

## Screenshots (if applicable)

Before/after screenshots for UI changes.

## Code Review Checklist

**For Reviewers:**

- [ ] Does the code solve the stated problem?
- [ ] Are there any edge cases not handled?
- [ ] Is the code readable and maintainable?
- [ ] Are there sufficient tests?
- [ ] Are there security concerns?
- [ ] Is the commit history clean (squashed if needed)?

**For Authors:**

- [ ] Self-review completed before requesting review
- [ ] CI passes (tests, lint, typecheck)
- [ ] PR size is reasonable (<500 lines ideal)
- [ ] Related to a single feature/fix
- [ ] Description clearly explains the change

## Identify Conflicts

```bash

## Check for conflicts before merge

git checkout main
git merge feature/user-auth --no-commit --no-ff

## Automatic merge failed; fix conflicts and then commit the result.

```

## Resolve Conflicts

```bash

## See conflicted files

git status

## Option 2: Use merge tool

git mergetool

## Option 3: Accept one side

git checkout --ours src/auth/login.ts    # Keep main version
git checkout --theirs src/auth/login.ts  # Keep feature version

## After resolving, stage and commit

git add src/auth/login.ts
git commit
```

## Conflict Prevention Strategies

```bash

## 2. Rebase frequently onto main

git checkout feature/user-auth
git fetch origin
git rebase origin/main

## 5. Review and merge PRs promptly

```

## Naming Conventions

```

## Feature branches

feature/user-authentication
feature/JIRA-123-payment-integration

## Bug fixes

fix/login-redirect-loop
fix/456-null-pointer-exception

## Hotfixes (production issues)

hotfix/critical-security-patch
hotfix/database-connection-leak

## Releases

release/1.2.0
release/2024-01-hotfix

## Experiments/POCs

experiment/new-caching-strategy
poc/graphql-migration
```

## Branch Cleanup

```bash

## Delete local branches that are merged

git branch --merged main | grep -v "^\*\|main" | xargs -n 1 git branch -d

## Delete remote-tracking references for deleted remote branches

git fetch -p

## Delete local branch

git branch -d feature/user-auth  # Safe delete (only if merged)
git branch -D feature/user-auth  # Force delete

## Delete remote branch

git push origin --delete feature/user-auth
```

## Stash Workflow

```bash

## Save work in progress

git stash push -m "WIP: user authentication"

## List stashes

git stash list

## Apply most recent stash

git stash pop

## Apply specific stash

git stash apply stash@{2}

## Drop stash

git stash drop stash@{0}
```

## Semantic Versioning

```
MAJOR.MINOR.PATCH

MAJOR: Breaking changes
MINOR: New features, backward compatible
PATCH: Bug fixes, backward compatible

Examples:
1.0.0 → 1.0.1 (patch: bug fix)
1.0.1 → 1.1.0 (minor: new feature)
1.1.0 → 2.0.0 (major: breaking change)
```

## Creating Releases

```bash

## Create annotated tag

git tag -a v1.2.0 -m "Release v1.2.0

Features:
- Add user authentication
- Implement password reset

Fixes:
- Resolve login redirect issue

Breaking Changes:
- None"

## Push tag to remote

git push origin v1.2.0

## List tags

git tag -l

## Delete tag

git tag -d v1.2.0
git push origin --delete v1.2.0
```

## Changelog Generation

```bash

## Generate changelog from commits

git log v1.1.0..v1.2.0 --oneline --no-merges

## Or use conventional-changelog

npx conventional-changelog -i CHANGELOG.md -s
```

## Essential Configs

```bash

## User identity

git config --global user.name "Your Name"
git config --global user.email "your@email.com"

## Default branch name

git config --global init.defaultBranch main

## Pull behavior (rebase instead of merge)

git config --global pull.rebase true

## Push behavior (push current branch only)

git config --global push.default current

## Auto-correct typos

git config --global help.autocorrect 1

## Better diff algorithm

git config --global diff.algorithm histogram

## Color output

git config --global color.ui auto
```

## Useful Aliases

```bash

## Add to ~/.gitconfig

[alias]
    co = checkout
    br = branch
    ci = commit
    st = status
    unstage = reset HEAD --
    last = log -1 HEAD
    visual = log --oneline --graph --all
    amend = commit --amend --no-edit
    wip = commit -m "WIP"
    undo = reset --soft HEAD~1
    contributors = shortlog -sn
```

## Gitignore Patterns

```gitignore

## Dependencies

node_modules/
vendor/

## Build outputs

dist/
build/
*.o
*.exe

## Environment files

.env
.env.local
.env.*.local

## IDE

.idea/
.vscode/
*.swp
*.swo

## OS files

.DS_Store
Thumbs.db

## Logs

*.log
logs/

## Test coverage

coverage/

## Cache

.cache/
*.tsbuildinfo
```

## Starting a New Feature

```bash

## 1. Update main branch

git checkout main
git pull origin main

## 2. Create feature branch

git checkout -b feature/user-auth

## 3. Make changes and commit

git add .
git commit -m "feat(auth): implement OAuth2 login"

## 4. Push to remote

git push -u origin feature/user-auth

## 5. Create Pull Request on GitHub/GitLab

```

## Updating a PR with New Changes

```bash

## 1. Make additional changes

git add .
git commit -m "feat(auth): add error handling"

## 2. Push updates

git push origin feature/user-auth
```

## Syncing Fork with Upstream

```bash

## 1. Add upstream remote (once)

git remote add upstream https://github.com/original/repo.git

## 2. Fetch upstream

git fetch upstream

## 3. Merge upstream/main into your main

git checkout main
git merge upstream/main

## 4. Push to your fork

git push origin main
```

## Undoing Mistakes

```bash

## Undo last commit (keep changes)

git reset --soft HEAD~1

## Undo last commit (discard changes)

git reset --hard HEAD~1

## Undo last commit pushed to remote

git revert HEAD
git push origin main

## Undo specific file changes

git checkout HEAD -- path/to/file

## Fix last commit message

git commit --amend -m "New message"

## Add forgotten file to last commit

git add forgotten-file
git commit --amend --no-edit
```

## Pre-Commit Hook

```bash
#!/bin/bash

## Run linting

npm run lint || exit 1

## Run tests

npm test || exit 1

## Check for secrets

if git diff --cached | grep -E '(password|api_key|secret)'; then
    echo "Possible secret detected. Commit aborted."
    exit 1
fi
```

## Pre-Push Hook

```bash
#!/bin/bash

## Run full test suite

npm run test:all || exit 1

## Check for console.log statements

if git diff origin/main | grep -E 'console\.log'; then
    echo "Remove console.log statements before pushing."
    exit 1
fi
```

## BAD: Committing directly to main

git checkout main
git commit -m "fix bug"

## BAD: Committing secrets

git add .env  # Contains API keys

## BAD: "Update" commit messages

git commit -m "update"
git commit -m "fix"

## GOOD: Descriptive messages

git commit -m "fix(auth): resolve redirect loop after login"

## BAD: Rewriting public history

git push --force origin main

## GOOD: Use revert for public branches

git revert HEAD

## BAD: Committing generated files

git add dist/
git add node_modules/

## GOOD: Add to .gitignore

```

## Quick Reference

| Task | Command |
|------|---------|
| Create branch | `git checkout -b feature/name` |
| Switch branch | `git checkout branch-name` |
| Delete branch | `git branch -d branch-name` |
| Merge branch | `git merge branch-name` |
| Rebase branch | `git rebase main` |
| View history | `git log --oneline --graph` |
| View changes | `git diff` |
| Stage changes | `git add .` or `git add -p` |
| Commit | `git commit -m "message"` |
| Push | `git push origin branch-name` |
| Pull | `git pull origin branch-name` |
| Stash | `git stash push -m "message"` |
| Undo last commit | `git reset --soft HEAD~1` |
| Revert commit | `git revert HEAD` |
