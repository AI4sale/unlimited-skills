---
name: unlimited-skills
description: Primary gateway to the external Unlimited Skills library for Claude Code. Run the 1-second `suggest` probe before any task that matches a trigger (coding, review, tests, debugging, git/PRs, prose, research, planning, ops), and whenever the user asks what skills are available.
---

# Unlimited Skills Router for Claude Code

Unlimited Skills is Claude Code's external skill memory: a local library of 250+ proven skills (checklists, workflows, regression recipes) that are deliberately NOT in the visible skill listing. A 1-second lookup often replaces 20 minutes of rediscovery.

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

SKIP only when a relevant skill is already active in the current context. Do not conclude that a skill is missing just because it is absent from `~/.claude/skills`, `.claude/skills`, or the visible skill list — query the library first and report what it returns.

## Workflow

1. Run `suggest "<task in 3-8 keywords>"` with the installed launcher.
2. If a suggestion looks relevant, run `view <skill-name>` and follow only the relevant instructions.
3. If `suggest` returns nothing, proceed with the task — do not search again with synonyms. For unusual or high-stakes tasks you may escalate once to `search "<query>" --mode hybrid --limit 8`.
4. If the user asks what skills are available, run `list --limit 80` and summarize; never paste every result.
5. If the user names a specific skill, run `where <skill-name>` or `view <skill-name>` before saying it is unavailable.
6. Optionally enrich the learning loop with `use <skill-name> --query "<query>" --task "<short task>"` and the `feedback` command — helpful, never required.

{{REMOTE_HUB_ROUTER_BLOCK}}

## Commands

Use the shell launcher on macOS, Linux, and WSL:

```bash
"{{CLAUDE_SH_LAUNCHER}}" suggest "<task in 3-8 keywords>"
"{{CLAUDE_SH_LAUNCHER}}" view <skill-name>
"{{CLAUDE_SH_LAUNCHER}}" search "<query>" --mode hybrid --limit 8
"{{CLAUDE_SH_LAUNCHER}}" where <skill-name>
"{{CLAUDE_SH_LAUNCHER}}" list --limit 80
```

Use the PowerShell launcher on Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "{{CLAUDE_PS_LAUNCHER}}" suggest "<task in 3-8 keywords>"
powershell -NoProfile -ExecutionPolicy Bypass -File "{{CLAUDE_PS_LAUNCHER}}" view <skill-name>
powershell -NoProfile -ExecutionPolicy Bypass -File "{{CLAUDE_PS_LAUNCHER}}" search "<query>" --mode hybrid --limit 8
powershell -NoProfile -ExecutionPolicy Bypass -File "{{CLAUDE_PS_LAUNCHER}}" where <skill-name>
powershell -NoProfile -ExecutionPolicy Bypass -File "{{CLAUDE_PS_LAUNCHER}}" list --limit 80
```

Library root:

```text
{{UNLIMITED_SKILLS_LIBRARY_ROOT}}
```

For inventory-style questions such as "what skills do you have?", run `list` first, then summarize the matching library skills. Do not paste every result or every skill body into the conversation. Treat the library as a retrieval layer, not as context that should always be loaded.
