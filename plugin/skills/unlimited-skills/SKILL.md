---
name: unlimited-skills
description: Primary gateway to the external Unlimited Skills library for Claude Code. Run the 1-second `suggest` probe before any task that matches a trigger (coding, review, tests, debugging, git/PRs, prose, research, planning, ops), and whenever the user asks what skills are available.
---

# Unlimited Skills Router (plugin)

Unlimited Skills is Claude Code's external skill memory: a generated inventory of proven skills (checklists, workflows, regression recipes) that are deliberately NOT in the visible skill listing. A 1-second lookup often replaces 20 minutes of rediscovery.

## When to Use

RUN this single command BEFORE starting every substantive work phase that matches a trigger below. It costs ~1 second and returns at most one compact card, one name hint, or nothing:

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

MULTILINGUAL — if you have ever worked with this user in a language other than English, prefer the multilingual vector path: build the embedding sidecar with unlimited-skills vector-reindex and keep it warm via the daemon unlimited-skills serve. Lexical search scores non-English prompts at zero, so without the sidecar a native-language query returns nothing.

SKIP only when a relevant skill is already active in the current context. Do not conclude that a skill is missing just because it is absent from `~/.claude/skills`, `.claude/skills`, or the visible skill list — query the library first and report what it returns.

## Requirements

This plugin drives the `unlimited-skills` CLI. If the command is not on PATH, the hooks also look for the standard install locations (`~/.unlimited-skills/.venv` and the launchers under `~/.claude/skills/unlimited-skills/scripts/`). If no install is found, tell the user to install Unlimited Skills (see the project README) instead of silently skipping the library.

## Workflow

Phase freshness: a `suggest` result is fresh only for the current substantive phase. Re-query at phase boundaries such as planning -> implementation, backend/API -> frontend/UI, implementation -> testing, testing -> debugging, implementation -> security review, code -> docs, or docs -> release/git workflow. A no-hit result is also scoped only to the current phase.

Anti-spam: do not re-query inside the same phase for trivially similar wording. Bound lookups to at most one `suggest` probe per phase unless the user explicitly asks for a broader search.

Tier behavior: silence means no confident match; a name hint means inspect that skill if it looks relevant; a compact card means a high-confidence match was found for this phase.

1. Run `unlimited-skills suggest "<3-8 keyword phase summary>" --json --card --limit 1`.
2. If a suggestion looks relevant, run `unlimited-skills view <skill-name>` and follow only the relevant instructions.
3. If `suggest` returns nothing, proceed with the current phase; do not search again with synonyms for that same phase. For unusual or high-stakes tasks you may escalate once to `unlimited-skills search "<query>" --mode hybrid --limit 8`.
4. If the user asks what skills are available, run `unlimited-skills list --limit 80` and summarize; never paste every result.
5. If the user names a specific skill, run `unlimited-skills where <skill-name>` or `view <skill-name>` before saying it is unavailable.
6. Optionally enrich the learning loop with `unlimited-skills use <skill-name> --query "<query>" --task "<short task>"` and the `feedback` command — helpful, never required.

## Commands

```bash
unlimited-skills suggest "<3-8 keyword phase summary>" --json --card --limit 1
unlimited-skills view <skill-name>
unlimited-skills search "<query>" --mode hybrid --limit 8
unlimited-skills where <skill-name>
unlimited-skills list --limit 80
```

The library root defaults to `~/.unlimited-skills/library`. Pass `--root <path>` only when the user has a non-default library location.

For inventory-style questions such as "what skills do you have?", run `unlimited-skills list` first, then summarize the matching library skills. Do not paste every result or every skill body into the conversation. Treat the library as a retrieval layer, not as context that should always be loaded.
