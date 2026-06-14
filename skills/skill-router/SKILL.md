---
name: unlimited-skills
description: Primary gateway to the external Unlimited Skills library. Run the 1-second `suggest` probe before any task that matches a trigger (coding, review, tests, debugging, git/PRs, prose, research, planning, ops), and whenever the user asks what skills are available.
---

# Unlimited Skills Router

Unlimited Skills is the gateway to the agent's external skill memory: a local library of 250+ proven skills (checklists, workflows, regression recipes) that are deliberately NOT listed in the current context. A 1-second lookup often replaces 20 minutes of rediscovery.

## When to Use

RUN the single `suggest` command BEFORE starting any task that matches a trigger below. It costs ~1 second and returns at most 3 one-liners (or nothing).

TRIGGERS (any one suffices):

- writing or reviewing code in a named language/framework (React, Python, Go, n8n, ...)
- review, audit, or security check of any artifact
- writing tests, fixing a bug, or debugging a failure
- git/GitHub workflows: branches, PRs, releases, changelogs
- writing prose: docs, posts, outreach, marketing, research reports
- planning, refactoring, migrations, deployments, ops procedures
- the user names a skill, workflow, or asks "what can you do"

MULTILINGUAL — if you have ever worked with this user in a language other than English, prefer the multilingual vector path: build the embedding sidecar with unlimited-skills vector-reindex and keep it warm via the daemon unlimited-skills serve. Lexical search scores non-English prompts at zero, so without the sidecar a native-language query returns nothing.

SKIP only when a relevant skill is already active in the current context. Do not conclude that a skill is missing just because it is absent from `.agents/skills`, `.codex/skills`, or the always-loaded skill list — query the library first and report what it returns.

## Workflow

1. Run the installed launcher: `$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 suggest "<task in 3-8 keywords>"`.
2. If a suggestion looks relevant, run `view <skill-name>` with the same launcher and follow only the relevant instructions.
3. If `suggest` returns nothing, proceed with the task — do not search again with synonyms. For unusual or high-stakes tasks you may escalate once to `search "<query>" --mode hybrid --limit 8`.
4. If the user asks what skills are available, run `list --limit 80` and summarize; never paste every result.
5. If the user names a specific skill, run `where <skill-name>` or `view <skill-name>` before saying it is unavailable.
6. Optionally enrich the learning loop with `use <skill-name> --query "<query>" --task "<short task>"` and the `feedback` command — helpful, never required.

{{REMOTE_HUB_ROUTER_BLOCK}}

## Commands

```powershell
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 suggest "<task in 3-8 keywords>"
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 view react-performance
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 search "React component rerender performance" --mode hybrid --limit 8
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 where security-review
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 list --limit 40
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 list --filter "security review" --limit 20
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 use react-performance --query "React component rerender performance" --task "Review slow React page"
$env:USERPROFILE\.codex\skills\unlimited-skills\scripts\unlimited-skills.ps1 feedback react-performance --query "React component rerender performance" --verdict accepted --notes "Matched the task"
```

For inventory-style questions such as "what skills do you have?", run `list` first, then summarize the matching library skills. Do not paste every result or every skill body into the conversation. Treat the library as a retrieval layer, not as context that should always be loaded.
