---
name: unlimited-skills
description: Primary gateway to the external Unlimited Skills library for Claude Code. Ask this router first before substantive work whenever a relevant skill is not already active, including writing, coding, review, debugging, research, docs, operations, planning, or when the user asks what skills are available.
---

# Unlimited Skills Router (plugin)

Unlimited Skills is Claude Code's external skill memory. Treat it as the place where all task-specific skills may exist, including skills that are not visible in Claude Code's current skill listing.

Use this router before doing substantive work unless a relevant skill is already active in context and it is clear why that skill applies.

Use this router first when:

- the user asks what skills, abilities, workflows, procedures, or checklists are available;
- the user names a skill that is not currently loaded;
- the task is content writing, editing, coding, review, debugging, research, documentation, operations, planning, or design;
- the task may benefit from specialized domain knowledge, a review checklist, a workflow, a tool procedure, or a regression-test recipe.

Do not conclude that a skill is missing just because it is absent from `~/.claude/skills`, `.claude/skills`, or the visible skill list. Query Unlimited Skills first and report what the library returns.

## Requirements

This plugin drives the `unlimited-skills` CLI, installed separately:

```bash
pip install unlimited-skills
```

If the `unlimited-skills` command is not found, tell the user to install the CLI (or activate the environment where it is installed) instead of silently skipping the library.

## Workflow

1. Build a short search query from the user's request, project stack, error text, framework names, and domain terms.
2. Run `unlimited-skills search "<query>" --mode hybrid --limit 8`.
3. Pick a skill only when the result is concrete enough to change the work.
4. Run `unlimited-skills view <skill-name>` and follow only the relevant instructions.
5. Record usage with `unlimited-skills use <skill-name> --query "<query>" --task "<short task>"`.
6. If the selected skill was wrong or especially useful, record feedback with the `feedback` command.

## Commands

```bash
unlimited-skills search "<query>" --mode hybrid --limit 8
unlimited-skills where <skill-name>
unlimited-skills view <skill-name>
unlimited-skills use <skill-name> --query "<query>" --task "<short task>"
unlimited-skills list --limit 80
```

The library root defaults to `~/.unlimited-skills/library`. Pass `--root <path>` only when the user has a non-default library location.

For inventory-style questions such as "what skills do you have?", run `unlimited-skills list` first, then summarize the matching library skills. Do not paste every result or every skill body into the conversation. Treat the library as a retrieval layer, not as context that should always be loaded.
