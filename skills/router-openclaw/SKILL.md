---
name: unlimited-skills
description: Primary gateway to the external Unlimited Skills library for OpenClaw. Use before substantive work whenever a relevant skill is not already active, including writing, coding, review, debugging, research, docs, operations, planning, design, or tasks that may need an ECC, Superpowers, or OpenClaw skill not already loaded.
version: 0.1.0
source: https://github.com/AI4sale/unlimited-skills
---

# Unlimited Skills Router for OpenClaw

Unlimited Skills is an external skill memory and retrieval layer. It keeps large packs out of OpenClaw's always-loaded context and retrieves only the relevant `SKILL.md` when needed.

## When to Use

RUN the single `suggest` command BEFORE starting any task that matches a trigger below. It costs ~1 second and returns at most 3 one-liners (or nothing). A 1-second lookup often replaces 20 minutes of rediscovery.

TRIGGERS (any one suffices):

- writing or reviewing code in a named language/framework (React, Python, Go, n8n, ...)
- review, audit, or security check of any artifact
- writing tests, fixing a bug, or debugging a failure
- git/GitHub workflows: branches, PRs, releases, changelogs
- writing prose: docs, posts, outreach, marketing, research reports
- planning, refactoring, migrations, deployments, ops procedures
- the user names a skill, workflow, or asks "what can you do"

MULTILINGUAL — if you have ever worked with this user in a language other than English, prefer the multilingual vector path: build the embedding sidecar with unlimited-skills vector-reindex and keep it warm via the daemon unlimited-skills serve. Lexical search scores non-English prompts at zero, so without the sidecar a native-language query returns nothing.

SKIP only when a relevant skill is already active in the current context. Do not conclude that a skill is missing just because it is absent from OpenClaw's visible skill list — query the library first and report what it returns.

## Installed Paths

Library root:

```text
{{UNLIMITED_SKILLS_LIBRARY_ROOT}}
```

OpenClaw launcher:

```bash
"{{OPENCLAW_SH_LAUNCHER}}" suggest "<task in 3-8 keywords>"
"{{OPENCLAW_SH_LAUNCHER}}" view <skill-name>
```

## Workflow

1. Run `suggest "<task in 3-8 keywords>"` with the launcher above.
2. If a suggestion looks relevant, run `view <skill-name>` and follow only the relevant instructions.
3. If `suggest` returns nothing, proceed with the task — do not search again with synonyms. For unusual or high-stakes tasks you may escalate once to `search "<query>" --mode hybrid --limit 8`.
4. If the user asks what skills are available, run `list --limit 80` and summarize the relevant collections or names.
5. If the user names a specific skill, run `where <skill-name>` or `view <skill-name>` before saying it is unavailable.
6. Optionally enrich the learning loop with `use <skill-name> --query "<query>" --task "<short task>"` and the `feedback` command — helpful, never required.

{{REMOTE_HUB_ROUTER_BLOCK}}

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
