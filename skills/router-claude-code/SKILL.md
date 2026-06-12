---
name: unlimited-skills
description: Primary gateway to the external Unlimited Skills library for Claude Code. Ask this router first before substantive work whenever a relevant skill is not already active, including writing, coding, review, debugging, research, docs, operations, planning, or when the user asks what skills are available.
---

# Unlimited Skills Router for Claude Code

Unlimited Skills is Claude Code's external skill memory. Treat it as the place where all task-specific skills may exist, including skills that are not visible in Claude Code's current skill listing.

Use this router before doing substantive work unless a relevant skill is already active in context and it is clear why that skill applies.

Core rule: search first, view one, then act.

Before solving unfamiliar or procedure-like tasks, check available skills. If a relevant skill is suggested, view it before creating a custom solution. If no relevant skill is suggested, continue normally.

Use this router first when:

- the user asks what skills, abilities, workflows, procedures, or checklists are available;
- the user names a skill that is not currently loaded;
- the task is content writing, editing, coding, review, debugging, research, documentation, operations, planning, or design;
- the task may benefit from specialized domain knowledge, a review checklist, a workflow, a tool procedure, or a regression-test recipe.

Do not conclude that a skill is missing just because it is absent from `~/.claude/skills`, `.claude/skills`, or the visible skill list. Query Unlimited Skills first and report what the library returns.

## Workflow

1. Build a short search query from the user's request, project stack, error text, framework names, and domain terms.
2. Run the cheap suggestion probe with `suggest "<query>" --limit 3`.
3. If no skill crosses the suggestion floor, continue normally.
4. If a relevant skill is suggested, run `view <skill-name>` and follow only the relevant instructions.
5. If the suggestion is inconclusive, run the broader fallback search with `search "<query>" --mode hybrid --limit 8`.
6. Pick a skill only when the result is concrete enough to change the work.
7. Record usage with `use <skill-name> --query "<query>" --task "<short task>"`.
8. If the selected skill was wrong or especially useful, record feedback with the `feedback` command.

{{REMOTE_HUB_ROUTER_BLOCK}}

## Commands

Use the shell launcher on macOS, Linux, and WSL:

```bash
"{{CLAUDE_SH_LAUNCHER}}" search "<query>" --mode hybrid --limit 8
"{{CLAUDE_SH_LAUNCHER}}" suggest "<query>" --limit 3
"{{CLAUDE_SH_LAUNCHER}}" where <skill-name>
"{{CLAUDE_SH_LAUNCHER}}" view <skill-name>
"{{CLAUDE_SH_LAUNCHER}}" use <skill-name> --query "<query>" --task "<short task>"
"{{CLAUDE_SH_LAUNCHER}}" list --limit 80
```

Use the PowerShell launcher on Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "{{CLAUDE_PS_LAUNCHER}}" search "<query>" --mode hybrid --limit 8
powershell -NoProfile -ExecutionPolicy Bypass -File "{{CLAUDE_PS_LAUNCHER}}" suggest "<query>" --limit 3
powershell -NoProfile -ExecutionPolicy Bypass -File "{{CLAUDE_PS_LAUNCHER}}" where <skill-name>
powershell -NoProfile -ExecutionPolicy Bypass -File "{{CLAUDE_PS_LAUNCHER}}" view <skill-name>
powershell -NoProfile -ExecutionPolicy Bypass -File "{{CLAUDE_PS_LAUNCHER}}" use <skill-name> --query "<query>" --task "<short task>"
powershell -NoProfile -ExecutionPolicy Bypass -File "{{CLAUDE_PS_LAUNCHER}}" list --limit 80
```

Library root:

```text
{{UNLIMITED_SKILLS_LIBRARY_ROOT}}
```

For inventory-style questions such as "what skills do you have?", search broad task terms first, then summarize the matching library skills. Do not paste every result or every skill body into the conversation. Treat the library as a retrieval layer, not as context that should always be loaded.
