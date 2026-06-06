<div align="center">

# Lord of the Skills

<pre>
+--------------------------------------------------------------+
|                 One skill to rule them all.                  |
+--------------------------------------------------------------+
</pre>

**Unlimited Skills** is a local skill memory and retrieval layer for coding agents.

Keep thousands of `SKILL.md` files out of the always-loaded context. Ask one tiny router skill what the task needs. Load only the selected skill.

</div>

## What it is

Unlimited Skills turns a folder full of skills into an action library for agents.

It is built around one practical rule: the agent should not know every skill all the time. It should know how to ask for the right skill when work starts.

The current version is built for Codex first, with migration scripts for Claude Code, OpenClaw, Hermes, and Vellum AI.

> **Sorry, yes, we patch `AGENTS.md`.**
>
> Agents often look only at `.agents/skills`, `.codex/skills`, or the visible skill list before saying a skill is missing. The installer patches `AGENTS.md` by default with a managed instruction block that tells the agent to query Unlimited Skills first. Pass the opt-out flag if you do not want that.

## Why this exists

Large skill packs are useful, but loading every skill into the model context is wasteful and eventually self-defeating:

- the context gets noisy;
- unrelated instructions compete with the task;
- the agent spends tokens carrying procedures it will not use;
- adding more skills makes the agent slower instead of smarter.

Unlimited Skills treats skills as a local library:

1. keep only a tiny router skill in the agent context;
2. store all real skills on disk;
3. search by task intent;
4. load only the selected `SKILL.md`;
5. record which skills were searched, viewed, used, accepted, or rejected;
6. use that feedback to improve retrieval and draft new skills.

## Status

Working now:

- recursive `SKILL.md` discovery;
- JSON lexical index;
- ChromaDB vector index;
- hybrid lexical + vector search;
- full skill view by name;
- Codex router skill;
- agent-driven one-skill adaptation workflow;
- usage and feedback logs;
- draft generation for new skills;
- migration scripts for Codex, Claude Code, OpenClaw, Hermes, and Vellum AI.

In development:

- persistent warm daemon as the default agent retrieval path;
- richer learning loop for accepted/rejected matches;
- automatic skill drafting from repeated task patterns;
- stronger per-agent installers and config adapters.

## Install

Clone the repo:

```powershell
git clone https://github.com/AI4sale/unlimited-skills.git
cd unlimited-skills
```

Install the CLI:

```powershell
python -m pip install -e ".[all]"
```

For minimal lexical-only usage:

```powershell
python -m pip install -e .
```

## Install for Codex

Install the router skill into `~/.codex/skills/unlimited-skills`.

Choose one path:

| Mode | What happens | Use when |
| --- | --- | --- |
| `default` | Install the router, migrate already installed local skills, index them. | You already have skills installed locally. |
| `bundled` | Install the router, add bundled ECC + Superpowers packs, then add local skills only when names do not duplicate. | You want a ready skill library immediately. |
| `adapt-installed` | Install the router, migrate local skills, structurally normalize them, and index them. | You want to prepare local skills for one-by-one agent adaptation. |

Windows PowerShell:

```powershell
.\scripts\install-codex.ps1
.\scripts\install-codex.ps1 -Mode bundled
.\scripts\install-codex.ps1 -AgentsFile C:\path\to\project\AGENTS.md
.\scripts\install-codex.ps1 -NoAgentsPatch
```

macOS/Linux:

```bash
./scripts/install-codex.sh
./scripts/install-codex.sh --mode bundled
./scripts/install-codex.sh --agents-file /path/to/project/AGENTS.md
./scripts/install-codex.sh --no-agents-patch
```

More install examples:

```powershell
.\scripts\install-codex.ps1 -Mode adapt-installed
```

```bash
./scripts/install-codex.sh --mode adapt-installed
```

Default mode installs the router, migrates already installed skills, and indexes them. Bundled mode installs the pre-adapted packs shipped in this repo, then adds local skills only when they do not duplicate existing skill names. Adapt-installed mode prepares installed local skills for the one-skill agent adaptation workflow.

For Codex projects, patching `AGENTS.md` is the default. If `AgentsFile` / `--agents-file` is not passed, the installer patches `./AGENTS.md` in the current directory. Run the installer from the target project root, or pass an explicit `AGENTS.md` path. Existing `AGENTS.md` content is preserved, and the managed block is replaced in place on repeat installs. Use `-NoAgentsPatch` or `--no-agents-patch` to skip it.

The installer creates an isolated venv under `~/.unlimited-skills/.venv` and writes a Codex-local launcher:

```text
~/.codex/skills/unlimited-skills/scripts/unlimited-skills.ps1
~/.codex/skills/unlimited-skills/scripts/unlimited-skills.sh
```

Restart Codex after installing the router skill.

## Migrate skills

All migration scripts run as dry runs unless you pass `-Apply` on Windows or `--apply` on macOS/Linux.

Codex:

```powershell
.\scripts\migrate-codex.ps1
.\scripts\migrate-codex.ps1 -Apply
```

```bash
./scripts/migrate-codex.sh
./scripts/migrate-codex.sh --apply
```

Claude Code:

```powershell
.\scripts\migrate-claude-code.ps1 -SourceRoot "$env:USERPROFILE\.claude\skills"
.\scripts\migrate-claude-code.ps1 -SourceRoot "$env:USERPROFILE\.claude\skills" -Apply
```

```bash
./scripts/migrate-claude-code.sh --source-root "$HOME/.claude/skills"
./scripts/migrate-claude-code.sh --source-root "$HOME/.claude/skills" --apply
```

OpenClaw:

```powershell
.\scripts\migrate-openclaw.ps1 -SourceRoot "$env:USERPROFILE\.openclaw\skills" -Apply
```

```bash
./scripts/migrate-openclaw.sh --source-root "$HOME/.openclaw/skills" --apply
```

Hermes:

```powershell
.\scripts\migrate-hermes.ps1 -SourceRoot "$env:USERPROFILE\.hermes\skills" -Apply
```

```bash
./scripts/migrate-hermes.sh --source-root "$HOME/.hermes/skills" --apply
```

Vellum AI:

```powershell
.\scripts\migrate-vellum-ai.ps1 -SourceRoot "$env:USERPROFILE\.vellum-ai\skills" -Apply
```

```bash
./scripts/migrate-vellum-ai.sh --source-root "$HOME/.vellum-ai/skills" --apply
```

You can point every migration script at any custom source root that contains recursive `SKILL.md` files.

## Index and search

Rebuild the lexical index:

```powershell
unlimited-skills reindex
```

Rebuild the vector index:

```powershell
unlimited-skills vector-reindex --verbose
```

Search:

```powershell
unlimited-skills search "React component rerender performance" --mode hybrid --limit 8
unlimited-skills search "OAuth token security n8n credentials" --mode hybrid --limit 8
unlimited-skills search "PostgreSQL migration lock timeout" --mode lexical --limit 8
```

Load a skill:

```powershell
unlimited-skills view react-performance
```

Record that the agent used a skill:

```powershell
unlimited-skills use react-performance --query "React component rerender performance" --task "Review slow React page"
```

Record feedback:

```powershell
unlimited-skills feedback react-performance --query "React component rerender performance" --verdict accepted --notes "Matched the task"
unlimited-skills feedback benchmark --query "React component rerender performance" --verdict rejected --notes "False positive"
```

Summarize learning feedback:

```powershell
unlimited-skills learning-summary
```

Draft a new skill:

```powershell
unlimited-skills draft-skill "postgres-online-migration" --description "Online PostgreSQL migration workflow" --evidence "Repeated production migration tasks with lock timeout checks." --write
```

## Warm daemon mode

CLI vector search has a cold start because the embedding model is loaded for each process. The daemon keeps the process alive and warms the model once.

Run:

```powershell
unlimited-skills serve --host 127.0.0.1 --port 8765
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

Search:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/search -Method Post -ContentType "application/json" -Body (@{
  query = "React component rerender performance"
  mode = "hybrid"
  limit = 8
} | ConvertTo-Json)
```

This is the intended path for very large libraries because it avoids repeated model startup cost.

## How it works

The system has four layers:

1. **Router skill**: a tiny `SKILL.md` that is always visible to the agent.
2. **Disk library**: many real skills stored under a root such as `~/.unlimited-skills/library/<collection>/skills/<name>/SKILL.md`.
3. **Retrieval**: lexical scoring, Chroma vector search, and hybrid reranking.
4. **Learning loop**: logs searches, views, selected skills, accepted matches, rejected matches, and new skill drafts.

The important design decision is that retrieval results are evidence, not authority. The agent still has to inspect the selected skill and decide whether it applies.

## Agent adaptation

Skill adaptation is an instruction workflow for the current agent, not a separate service. Codex or Claude Code prepares one source skill, rewrites it into the action-memory schema, and applies it with the CLI.

See [docs/agent-skill-adaptation.md](docs/agent-skill-adaptation.md).

## Repository layout

```text
unlimited_skills/        Python CLI and daemon
skills/skill-router/     Codex-compatible router skill
scripts/                 installers and migration scripts
docs/                    architecture and roadmap
examples/                example libraries and commands
```

## Safety model

- Migration scripts default to dry-run mode.
- Vector dependencies are optional.
- The daemon binds to `127.0.0.1` by default.
- Usage and feedback logs are local files under `.learning/`.
- Skills are not executed automatically. They are retrieved and then inspected by the agent.

## License

MIT
