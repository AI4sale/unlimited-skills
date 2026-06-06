---
name: unlimited-skills
description: Search and load external skills through Unlimited Skills without keeping the whole skill library in the agent context.
---

# Unlimited Skills Router

Use this skill when a task may benefit from a specialized skill that is stored outside the agent's always-loaded context.

## Workflow

1. Build a short search query from the user's request, project stack, error text, framework names, and domain terms.
2. Run the installed launcher: `$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 search "<query>" --mode hybrid --limit 8`.
3. Pick a skill only when the result is concrete enough to change the work.
4. Run `$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 view <skill-name>` and follow only the relevant instructions.
5. Record usage with `$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 use <skill-name> --query "<query>" --task "<short task>"`.
6. If the selected skill was wrong or especially useful, record feedback with the same launcher and the `feedback` command.

## Commands

```powershell
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 search "React component rerender performance" --mode hybrid --limit 8
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 view react-performance
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 use react-performance --query "React component rerender performance" --task "Review slow React page"
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 feedback react-performance --query "React component rerender performance" --verdict accepted --notes "Matched the task"
```

Do not paste every result or every skill body into the conversation. Treat the library as a retrieval layer, not as context that should always be loaded.
