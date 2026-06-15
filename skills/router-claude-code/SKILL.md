---
name: unlimited-skills
description: Primary gateway to the external Unlimited Skills library for Claude Code, Codex, Cursor, and other agents. Use after installing the `unlimited-skills` CLI with PyPI and running `unlimited-skills quickstart`; then run the 1-second `suggest` probe before coding, review, tests, debugging, git/PRs, prose, research, planning, ops, or skill-inventory tasks.
---

# Unlimited Skills Router

Unlimited Skills is an external skill memory for coding agents: a local library
of proven skills, checklists, workflows, and regression recipes that are
deliberately not all loaded into visible context. A 1-second lookup often
replaces 20 minutes of rediscovery.

## Install the CLI First

This skill is a router. It does not vendor the full Unlimited Skills CLI or
bundled packs by itself.

On a fresh machine, install and initialize the CLI before relying on the router:

```bash
pip install --upgrade "unlimited-skills>=0.6.1"
unlimited-skills quickstart
```

For hybrid/vector search:

```bash
pip install "unlimited-skills[vector]>=0.6.1"
unlimited-skills vector-reindex
```

If this skill was installed from Awesome Skills with
`npx skills add AI4sale/unlimited-skills`, treat the npm command as the visible
router install only. The Python CLI still comes from PyPI.

## When to Use

RUN this single command BEFORE starting every substantive work phase that
matches a trigger below. It costs about 1 second and returns at most one
compact card, one name hint, or nothing:

```bash
unlimited-skills suggest "<3-8 keyword phase summary>" --json --card --limit 1
```

TRIGGERS (any one suffices):

- writing or reviewing code in a named language/framework (React, Python, Go, n8n, ...)
- review, audit, or security check of any artifact
- writing tests, fixing a bug, or debugging a failure
- git/GitHub workflows: branches, PRs, releases, changelogs
- writing prose: docs, posts, outreach, marketing, research reports
- planning, refactoring, migrations, deployments, ops procedures
- the user names a skill, workflow, or asks "what can you do"

SKIP only when a relevant skill is already active in the current context. Do
not conclude that a skill is missing just because it is absent from
`~/.claude/skills`, `.claude/skills`, `.agents/skills`, `.codex/skills`, or the
visible skill list. Query the library first and report what it returns.

## Phase Freshness

A `suggest` result is fresh only for the current substantive phase. Re-query at
phase boundaries: planning -> implementation, backend/API -> frontend/UI,
implementation -> testing, testing -> debugging, implementation -> security
review, code -> docs, or docs -> release/git workflow. A no-hit result is also
scoped only to the current phase.

Anti-spam: do not re-query inside the same phase for trivially similar wording.
Bound lookups to at most one `suggest` probe per phase unless the user
explicitly asks for a broader search.

Tier behavior: silence means no confident match; a name hint means inspect that
skill if it looks relevant; a compact card means a high-confidence match was
found for this phase.

## Workflow

1. Run `unlimited-skills suggest "<3-8 keyword phase summary>" --json --card --limit 1`.
2. If a suggestion looks relevant, run `unlimited-skills view <skill-name>` and
   follow only the relevant instructions.
3. If `suggest` returns nothing, proceed with the current phase; do not search
   again with synonyms for that same phase.
   For unusual or high-stakes tasks, escalate once to
   `unlimited-skills search "<query>" --mode hybrid --limit 8`.
4. If the user asks what skills are available, run
   `unlimited-skills list --limit 80` and summarize. Never paste every result.
5. If the user names a specific skill, run `unlimited-skills where <skill-name>`
   or `unlimited-skills view <skill-name>` before saying it is unavailable.
6. Optionally enrich the learning loop with
   `unlimited-skills use <skill-name> --query "<query>" --task "<short task>"`
   and the `feedback` command. This is helpful, never required.

## Commands

```bash
unlimited-skills suggest "<3-8 keyword phase summary>" --json --card --limit 1
unlimited-skills view <skill-name>
unlimited-skills search "<query>" --mode hybrid --limit 8
unlimited-skills where <skill-name>
unlimited-skills list --limit 80
unlimited-skills quickstart
unlimited-skills doctor
```

Library root:

```text
~/.unlimited-skills/library
```

Pass `--root <path>` only when the user has a non-default library location.

For inventory-style questions such as "what skills do you have?", run
`unlimited-skills list` first, then summarize the matching library skills. Do
not paste every result or every skill body into the conversation. Treat the
library as a retrieval layer, not as context that should always be loaded.

## Agent-Specific Full Installs

For a deeper integration that patches agent guidance files, migrates existing
local skills, writes launchers, or registers hooks, use the repository
installers after cloning the repo. The Awesome Skills / `skills add` path is a
lightweight router card.
