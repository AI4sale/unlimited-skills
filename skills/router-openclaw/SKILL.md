---
name: unlimited-skills
description: Primary gateway to the external Unlimited Skills library for OpenClaw. Use before substantive work whenever a relevant skill is not already active, including writing, coding, review, debugging, research, docs, operations, planning, design, or tasks that may need an ECC, Superpowers, or OpenClaw skill not already loaded.
version: 0.1.0
source: https://github.com/AI4sale/unlimited-skills
---

# Unlimited Skills Router for OpenClaw

Unlimited Skills is an external skill memory and retrieval layer. It keeps large packs out of OpenClaw's always-loaded context and retrieves only the relevant `SKILL.md` when needed.

## When to Use

Use this router before doing substantive work unless an already-loaded skill is clearly relevant and already being used for the current task.

Use this router first when:

- the user asks what skills, abilities, workflows, procedures, agents, or checklists are available;
- the user names a skill that is not currently loaded;
- the task is content writing, editing, coding, review, debugging, research, documentation, operations, planning, or design and no clearly relevant loaded skill is already active;
- the task may benefit from specialized domain knowledge, a review checklist, a workflow, a tool procedure, or a regression-test recipe;
- the task is security, testing, debugging, frontend, backend, infrastructure, documentation, research, data, agent, or workflow related.

Do not conclude that a skill is missing just because it is absent from OpenClaw's visible skill list. Query Unlimited Skills first and report what the library returns.
Do not skip this router just because the task looks simple; skip it only when a relevant skill is already active in context and the reason for using that skill is clear.

## Installed Paths

Library root:

```text
{{UNLIMITED_SKILLS_LIBRARY_ROOT}}
```

OpenClaw launcher:

```bash
"{{OPENCLAW_SH_LAUNCHER}}" search "<query>" --mode hybrid --limit 8
"{{OPENCLAW_SH_LAUNCHER}}" view <skill-name>
```

## Workflow

1. If the user asks what skills are available, run `list --limit 80` and summarize the relevant collections or names.
2. If the user names a specific skill, run `where <skill-name>` or `view <skill-name>` before saying it is unavailable.
3. Otherwise, build a short search query from the user's request, project stack, error text, framework names, and domain terms.
4. Run `search "<query>" --mode hybrid --limit 8` with the launcher above.
5. Pick a skill only when the result is concrete enough to change the work.
6. Run `view <skill-name>` and follow only the relevant instructions.
7. Record usage with `use <skill-name> --query "<query>" --task "<short task>"`.
8. If the selected skill was wrong or especially useful, record feedback with the `feedback` command.

Do not paste every result or every skill body into the conversation. Treat the library as a retrieval layer, not as context that should always be loaded.

## Common Commands

```bash
"{{OPENCLAW_SH_LAUNCHER}}" list --limit 40
"{{OPENCLAW_SH_LAUNCHER}}" list --filter "security review" --limit 20
"{{OPENCLAW_SH_LAUNCHER}}" search "React component rerender performance" --mode hybrid --limit 8
"{{OPENCLAW_SH_LAUNCHER}}" where security-review
"{{OPENCLAW_SH_LAUNCHER}}" view security-review
"{{OPENCLAW_SH_LAUNCHER}}" use security-review --query "security review" --task "Review code for security issues"
"{{OPENCLAW_SH_LAUNCHER}}" feedback security-review --query "security review" --verdict accepted --notes "Matched the task"
```
