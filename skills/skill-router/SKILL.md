---
name: unlimited-skills
description: Primary gateway to the external Unlimited Skills library. Ask this router first whenever the task may need a skill, workflow, checklist, domain procedure, or when the user asks what skills are available.
---

# Unlimited Skills Router

Unlimited Skills is the gateway to the agent's external skill memory. Treat it as the place where all task-specific skills may exist, including skills that are not listed in the current context.

Use this router first when:

- the user asks what skills, abilities, agents, workflows, procedures, or checklists are available;
- the user names a skill that is not currently loaded, including names mentioned in `AGENTS.md`;
- the task may benefit from specialized domain knowledge, a review checklist, a workflow, a tool procedure, or a regression-test recipe;
- the task is security, testing, debugging, frontend, backend, infrastructure, documentation, research, data, agent, or workflow related.

Do not conclude that a skill is missing just because it is absent from `.agents/skills`, `.codex/skills`, or the always-loaded skill list. Query Unlimited Skills first and report what the library returns.

## Workflow

1. If the user asks what skills are available, run `list` and summarize the relevant collections or names.
2. If the user names a specific skill, run `where <skill-name>` or `view <skill-name>` before saying it is unavailable.
3. Otherwise, build a short search query from the user's request, project stack, error text, framework names, and domain terms.
4. Run the installed launcher: `$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 search "<query>" --mode hybrid --limit 8`.
5. Pick a skill only when the result is concrete enough to change the work.
6. Run `$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 view <skill-name>` and follow only the relevant instructions.
7. Record usage with `$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 use <skill-name> --query "<query>" --task "<short task>"`.
8. If the selected skill was wrong or especially useful, record feedback with the same launcher and the `feedback` command.

## Commands

```powershell
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 list --limit 40
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 list --filter "security review" --limit 20
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 search "React component rerender performance" --mode hybrid --limit 8
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 where security-review
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 view react-performance
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 use react-performance --query "React component rerender performance" --task "Review slow React page"
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 feedback react-performance --query "React component rerender performance" --verdict accepted --notes "Matched the task"
```

For inventory-style questions such as "what skills do you have?", search broad task terms first, then summarize the matching library skills. Do not paste every result or every skill body into the conversation. Treat the library as a retrieval layer, not as context that should always be loaded.
