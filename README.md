<div align="center">

# Stop flooding your agent's context with skills and tool schemas

**Search first. Load one skill, tool, or procedure only when needed.**

<pre>
+--------------------------------------------------------------+
|                 One skill to rule them all.                  |
+--------------------------------------------------------------+
</pre>

**Unlimited Skills** is a local-first capability router for coding agents. It keeps skills, procedures, and tool schemas out of standing context, searches by task intent, and loads only the one capability needed for the current job.

**v0.5.0-alpha / public alpha of a local-first tool.** The MIT core runs offline today. There is nothing for sale on this page; gated alpha surfaces are described under [Enterprise & trust layer](#enterprise--trust-layer).

[Donate to Unlimited Skills](https://opportunity.ai4.sale/donate/unlimited-skills) · [Donation terms](DONATE.md)

</div>

## The problem

Every visible `SKILL.md` competes for attention on every turn. Every MCP server your agent host connects to can also dump its full tool list — names, descriptions, and complete JSON input schemas — into the context window at session start. The agent pays that tax before it has read a single line of your task, whether or not those skills or tools are ever called. Adding more capability this way makes the agent slower instead of smarter: the context gets noisy, unrelated instructions compete with the task, and tokens are spent carrying procedures that will not run.

## The fix: search first, load one

Unlimited Skills keeps capabilities out of standing context and retrieves them on demand:

1. keep only a tiny router skill in the agent context;
2. store real skills on disk;
3. for MCP, keep full tool schemas behind the 3-meta-tool gateway;
4. search by task intent;
5. load only the selected `SKILL.md`, procedure, or `inputSchema` of exactly one tool;
6. record which skills were searched, viewed, used, accepted, or rejected;
7. use that feedback to improve retrieval and draft new skills.

## Measured, not promised

These numbers are measured and reproducible — and they are deliberately not a promise about your machine. Skill pre-load savings depend on how your agent discovers visible `SKILL.md` files; MCP savings depend on how many servers and schemas your host loads. Measure your own setup before and after install.

| What | Measured on our setup | Reproduce |
| --- | --- | --- |
| Skill pre-load context cost (agent-visible `SKILL.md` files) | Hermes context-reduction install report: 184 visible `SKILL.md` files before install -> 1 visible router skill after install | Measure before and after install: `./scripts/install-hermes.sh --mode evacuate-visible-skills`, then `./scripts/install-hermes.sh --mode evacuate-visible-skills --apply` |
| MCP standing context cost (lab benchmark: 40 realistic upstream tools with ~2 KB schemas) | 90,420 bytes full schema dump → 1,268 bytes for the gateway's 3 meta-tools (1.4%) | `pytest -s tests/test_mcp_context_budget.py` |
| MCP savings on your machine | your numbers — measured locally from your real Claude Code MCP config; nothing is uploaded | `unlimited-skills mcp savings` |
| Invocation probe latency | under 1 second cold on the bundled 267-skill library (p90 ~450 ms direct spawn, ~790 ms through the PowerShell launcher) | `unlimited-skills suggest "<task>"` |
| Retrieval quality | top-3 hit rate 0.967 (29/30) and top-1 0.933 on the frozen 30-scenario eval set, with 0 false positives across 12 negative scenarios | `python scripts/check-skill-effectiveness.py` |

Methodology and caveats: [docs/context-reduction-model.md](docs/context-reduction-model.md), [docs/unlimited-tools.md](docs/unlimited-tools.md), [docs/mcp-performance.md](docs/mcp-performance.md), [docs/adoption/skill-effectiveness-standard.md](docs/adoption/skill-effectiveness-standard.md).

## Start here

```bash
pip install unlimited-skills
unlimited-skills quickstart
unlimited-skills mcp install --claude-code --dry-run
unlimited-skills setup --local-only
```

What each step gives you:

1. **Install** — the local core from PyPI. The v0.5 wheel includes the bundled ECC + Superpowers packs used by `quickstart`; for vector/hybrid search, install with the `[all]` extras — see [Install](#install) below.
2. **`unlimited-skills quickstart`** — the one-command golden path: it imports the bundled skill packs when your library is empty, runs a first search to prove retrieval works, and measures your real MCP context savings — how many tokens of MCP tool schemas your Claude Code config loads into every session versus the 3 meta-tools of the Unlimited Tools gateway. Everything runs locally and the command is idempotent.
3. **`unlimited-skills mcp install --claude-code`** — the safe Claude Code MCP gateway installer. Start with `--dry-run`: it shows a redacted diff, creates backups before writes, preserves existing MCP servers, and never prints env values.
4. **`unlimited-skills setup --local-only`** — the guided first-run wizard for the local-only path.

Read next, in this order:

1. [docs/quickstart.md](docs/quickstart.md) — what quickstart does and how the first search proves retrieval works;
2. [docs/context-reduction-model.md](docs/context-reduction-model.md) — how to measure visible-skill context reduction before and after install;
3. [docs/unlimited-tools.md](docs/unlimited-tools.md) — the 3-meta-tool MCP gateway model and the measured context budget;
4. [docs/adoption/skill-effectiveness-standard.md](docs/adoption/skill-effectiveness-standard.md) — how retrieval quality is measured and gated.

## What it is

Unlimited Skills turns a folder full of skills into an action library for agents.

It is built around one practical rule: the agent should not know every skill all the time. It should know how to ask for the right skill when work starts.

The current version is built for Codex first, with full installers for Codex, Claude Code, OpenClaw, and Hermes, plus migration scripts for Codex, Claude Code, OpenClaw, Hermes, and Vellum AI.

> **Sorry, yes, we patch `AGENTS.md`.**
>
> Agents often look only at `.agents/skills`, `.codex/skills`, or the visible skill list before saying a skill is missing. The installer patches `AGENTS.md` by default with a managed instruction block that tells the agent to query Unlimited Skills first. Pass the opt-out flag if you do not want that.

## Status

Working now in the local core:

- recursive `SKILL.md` discovery;
- JSON lexical index;
- local vector sidecar index with ChromaDB compatibility storage;
- hybrid lexical + vector search;
- privacy-safe `suggest` probe and deterministic skill effectiveness gate for A0/v0.5 adoption readiness;
- full skill view by name;
- Codex router skill;
- agent-driven one-skill adaptation workflow;
- usage and feedback logs;
- draft generation for new skills;
- migration scripts for Codex, Claude Code, OpenClaw, Hermes, and Vellum AI;
- OpenClaw installer for workspace/plugin/built-in skills;
- Claude Code installer for personal/project skills and `CLAUDE.md` patching;
- Hermes router-only context-reduction installer and rollback scripts;
- the Unlimited Tools MCP layer: `unlimited-skills mcp serve`, `unlimited-skills mcp gateway`, the local `unlimited-skills mcp savings` measurement, and `unlimited-skills mcp install --claude-code` for safe Claude Code MCP registration;
- native skill sync for Codex, Claude Code, Hermes, and OpenClaw roots;
- public repo self-update checks and applies latest releases/tags;
- guided first-run setup wizard for local-only, registered, Local Skill Hub, and Enterprise onboarding paths;
- redacted support diagnostic bundle for support handoff without skill bodies, prompts, search queries, env values, tokens, private keys, or local paths by default.

Registered, hosted, signed-distribution, and governance surfaces — and the integration gates that verify them — are listed under [Enterprise & trust layer](#enterprise--trust-layer).

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

The v0.5 wheel includes the bundled ECC + Superpowers packs needed for `quickstart`. Repo-only installer scripts and full docs still live in the GitHub checkout.

Run the first-run wizard:

```powershell
unlimited-skills setup --local-only --dry-run
unlimited-skills setup --local-only
```

For registered, hub, and Enterprise paths, see [docs/first-run-setup.md](docs/first-run-setup.md).

Create a redacted support bundle:

```powershell
unlimited-skills support bundle --dry-run
unlimited-skills support bundle --out support-bundle.zip
```

See [docs/support-bundle.md](docs/support-bundle.md) for the privacy boundary.

For release scope and known limitations, see [CHANGELOG.md](CHANGELOG.md), [docs/packaging.md](docs/packaging.md), [docs/install-upgrade-uninstall.md](docs/install-upgrade-uninstall.md), and [SECURITY.md](SECURITY.md). Per-release milestone docs are listed under [Release milestone docs](#release-milestone-docs).

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
.\scripts\install-codex.ps1 -AgentsFile <project>\AGENTS.md
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

For Codex, patching `AGENTS.md` is the default. If `AgentsFile` / `--agents-file` is not passed, the installer patches `~/.codex/AGENTS.md` so the router is available at the Codex system level. Pass an explicit project `AGENTS.md` path only when you intentionally want project-local instructions. Existing `AGENTS.md` content is backed up as `Agents_md_YYYYMMDD_HHMMSS.back`, ECC managed blocks are replaced, and the Unlimited Skills managed block is replaced in place on repeat installs. Use `-NoAgentsPatch` or `--no-agents-patch` to skip it.

The installer creates an isolated venv under `~/.codex/.unlimited-skills/.venv`, stores the Codex library under `~/.codex/.unlimited-skills/library`, and writes a Codex-local launcher:

```text
~/.codex/skills/unlimited-skills/scripts/unlimited-skills.ps1
~/.codex/skills/unlimited-skills/scripts/unlimited-skills.sh
```

Restart Codex after installing the router skill.

## Install for Claude Code

### Option A: Claude Code plugin (recommended)

Since v0.3.12 the router ships as a native Claude Code plugin with a `SessionStart` hook, so the router contract is injected into every session deterministically instead of relying on `CLAUDE.md` or skill-list visibility. Install the CLI (see [Start here](#start-here) for the install command), then add the plugin inside Claude Code:

```text
/plugin marketplace add AI4sale/unlimited-skills
/plugin install unlimited-skills@unlimited-skills
```

The PyPI install gives you the local core and bundled packs. For vector/hybrid search, install with the `[all]` extras instead — see [Install](#install) above.

See `docs/claude-code-plugin.md` for details, including how the plugin coexists with the script installer below.

### Claude Code MCP gateway

After `pip install unlimited-skills`, register the Unlimited Tools gateway in Claude Code without hand-editing `.mcp.json`:

```bash
unlimited-skills mcp install --claude-code --dry-run
unlimited-skills mcp install --claude-code
unlimited-skills mcp install status
```

Use `--project` for the current project's `.mcp.json` (default), or `--global` for the top-level `~/.claude.json` `mcpServers` section. The installer validates JSON before and after writes, backs up existing files, preserves other `mcpServers`, and redacts env values/local paths in dry-run output. It creates an empty gateway config on first install; add upstreams there using `env_allowlist` names, not literal env values. Remove the gateway entry with:

```bash
unlimited-skills mcp uninstall --claude-code
```

### Option B: script installer

Install the router skill into `~/.claude/skills/unlimited-skills`.

Claude Code's current skills documentation defines personal skills at `~/.claude/skills/<skill-name>/SKILL.md` and project skills at `.claude/skills/<skill-name>/SKILL.md`. The installer follows that layout: it installs one visible router skill, migrates existing personal and project skills into the Unlimited Skills library, patches `CLAUDE.md` by default, writes launchers that remember the selected project root, and rebuilds the index.

Choose one path:

| Mode | What happens | Use when |
| --- | --- | --- |
| `default` | Install the router, migrate already installed Claude Code personal/project skills, index them. | You already have Claude Code skills installed locally. |
| `bundled` | Install the router, add bundled ECC + Superpowers packs, then add local Claude Code skills only when names do not duplicate. | You want a ready skill library immediately. |
| `adapt-installed` | Install the router, migrate local Claude Code skills, structurally normalize them, and index them. | You want to prepare local skills for one-by-one agent adaptation. |

Windows PowerShell:

```powershell
.\scripts\install-claude-code.ps1
.\scripts\install-claude-code.ps1 -Mode bundled
.\scripts\install-claude-code.ps1 -ClaudeFile <project>\CLAUDE.md
.\scripts\install-claude-code.ps1 -NoClaudePatch
```

macOS/Linux/WSL:

```bash
./scripts/install-claude-code.sh
./scripts/install-claude-code.sh --mode bundled
./scripts/install-claude-code.sh --claude-file /path/to/project/CLAUDE.md
./scripts/install-claude-code.sh --no-claude-patch
```

Useful options:

```bash
./scripts/install-claude-code.sh --project-root "$PWD"
./scripts/install-claude-code.sh --no-project-skills
./scripts/install-claude-code.sh --vector-reindex
./scripts/install-claude-code.sh --json
```

Default Claude Code paths:

```text
personal skills:  ~/.claude/skills
project skills:   ./.claude/skills
router target:    ~/.claude/skills/unlimited-skills
shell launcher:   ~/.claude/skills/unlimited-skills/scripts/unlimited-skills.sh
PowerShell:       ~/.claude/skills/unlimited-skills/scripts/unlimited-skills.ps1
CLAUDE.md:        ./CLAUDE.md
library root:     ~/.unlimited-skills/library
```

If `~/.claude/skills` already existed, Claude Code should detect the new router skill in the current session. If the top-level skills directory did not exist before installation, restart Claude Code so the new directory is watched.

After installation, newly added Claude Code skills are mirrored into Unlimited Skills on the next router CLI call. Personal skills under `~/.claude/skills` sync into `local/claude-code/skills`; project skills under the installed project root's `.claude/skills` sync into `local/claude-code-project/skills`. This is not a background file watcher; it happens when the router runs `search`, `list`, `view`, `where`, `use`, `reindex`, or `vector-reindex`.

## Install for OpenClaw

OpenClaw needs a full installer, not just a migration script. The installer puts the router skill into the OpenClaw workspace, writes an OpenClaw launcher, imports OpenClaw workspace/plugin/built-in skills, patches the workspace `AGENTS.md`, and rebuilds the index.

The OpenClaw installer modifies the selected workspace. Run it only in the intended workspace, or pass `--no-agents-patch` if you do not want it to patch `AGENTS.md`.

Linux:

```bash
./scripts/install-openclaw.sh --mode bundled
```

Windows PowerShell:

```powershell
.\scripts\install-openclaw.ps1 -Mode bundled
```

Useful options:

```bash
./scripts/install-openclaw.sh --workspace-root "$HOME/.openclaw/workspace"
./scripts/install-openclaw.sh --no-builtin
./scripts/install-openclaw.sh --no-plugin-skills
./scripts/install-openclaw.sh --no-agents-patch
./scripts/install-openclaw.sh --vector-reindex
```

Default OpenClaw paths:

```text
workspace skills:  ~/.openclaw/workspace/skills
plugin skills:     ~/.openclaw/plugin-skills
built-in skills:   /usr/local/lib/node_modules/openclaw/skills
browser plugin:    /usr/local/lib/node_modules/openclaw/dist/extensions/browser/skills
router target:     ~/.openclaw/workspace/skills/unlimited-skills
launcher:          ~/.openclaw/workspace/skills/unlimited-skills/scripts/unlimited-skills.sh
AGENTS.md:         ~/.openclaw/workspace/AGENTS.md
```

## Install for Hermes

Hermes users should distinguish plain migration from context reduction:

- `migrate-hermes` copies skills into the Unlimited Skills library but leaves `~/.hermes/skills` untouched.
- `install-hermes --mode evacuate-visible-skills` copies skills into the library, moves originals into a rollback backup, and leaves only the `unlimited-skills` router visible to Hermes.

If Hermes loads all visible skills into startup context, use `install-hermes --mode evacuate-visible-skills`. Plain `router-only` installation mirrors native skills into the library but leaves existing visible skills in place, so it does not reduce Hermes startup context by itself.

Dry run first:

```powershell
.\scripts\install-hermes.ps1 -Mode evacuate-visible-skills
```

```bash
./scripts/install-hermes.sh --mode evacuate-visible-skills
```

Apply:

```powershell
.\scripts\install-hermes.ps1 -Mode evacuate-visible-skills -Apply
```

```bash
./scripts/install-hermes.sh --mode evacuate-visible-skills --apply
```

The install report shows the proof that context was reduced:

```text
Before:
  visible SKILL.md count: 184
After:
  visible SKILL.md count: 1
  visible skills:
    - unlimited-skills
```

Rollback with the manifest printed by the installer:

```powershell
.\scripts\rollback-hermes.ps1 -Manifest "$env:USERPROFILE\.unlimited-skills\backups\hermes-visible-skills-YYYYMMDD-HHMMSS\manifest.json" -Apply
```

```bash
./scripts/rollback-hermes.sh --manifest "$HOME/.unlimited-skills/backups/hermes-visible-skills-YYYYMMDD-HHMMSS/manifest.json" --apply
```

See `docs/integrations/hermes.md` and `docs/context-reduction-model.md` for the full model.

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
.\scripts\migrate-openclaw.ps1 -Apply
```

```bash
./scripts/migrate-openclaw.sh --apply
```

OpenClaw migration-only scripts use `~/.openclaw/workspace/skills` by default. Prefer `install-openclaw.*` for a full OpenClaw setup.

Hermes plain migration imports skills into the Unlimited Skills library. It does **not** reduce Hermes startup context if the original skills remain in `~/.hermes/skills`.

```powershell
.\scripts\migrate-hermes.ps1 -SourceRoot "$env:USERPROFILE\.hermes\skills" -Apply
```

```bash
./scripts/migrate-hermes.sh --source-root "$HOME/.hermes/skills" --apply
```

For context reduction, use `install-hermes --mode evacuate-visible-skills --apply` instead.

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

`vector-reindex` writes two local artifacts:

- `.unlimited-skills-vectors.json` for the normal query fast path;
- `.chroma-skills/` as a compatibility ChromaDB index.

If vector search says the vector index is not ready, run `unlimited-skills vector-reindex` again. After upgrading to `v0.2.0-alpha` or later, reindex once so the fast sidecar exists.

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

CLI vector search has a cold start because the embedding model is loaded for each process. The vector sidecar removes Chroma startup from normal queries, but the first query in a new process still has to load the embedding model. The daemon keeps the process alive and caches the model after warm start.

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

This is the intended path for very large libraries or repeated vector/hybrid searches because it avoids repeated model startup cost.

## Local diagnostics and library management

Run a local-only diagnostic without registration or hosted calls:

```bash
unlimited-skills doctor
unlimited-skills doctor --json
unlimited-skills doctor --agent hermes
```

Mirror native agent skill roots into the local library:

```bash
unlimited-skills sync-native --agent hermes
unlimited-skills search "security review" --native-agent hermes
```

`search`, `list`, `view`, `where`, `use`, `reindex`, and `vector-reindex` automatically sync known native skill roots before running. This means newly installed Codex, Claude Code, Hermes, and OpenClaw skills are mirrored under the active Unlimited Skills library and become searchable through the router without manual migration. Codex defaults to `~/.codex/.unlimited-skills/library`; other agents default to `~/.unlimited-skills/library` unless their installer overrides the root. Native sync is non-destructive: it overlays new or changed skill files and never clears the existing `local/` library. Pass `--no-native-sync` or set `UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC=1` to skip this behavior.

For Claude Code, native sync also discovers skills bundled with installed plugins. It reads `~/.claude/plugins/installed_plugins.json`, resolves each plugin's install path (falling back to the marketplace clone listed in `known_marketplaces.json` when the cache snapshot is pruned), and mirrors the skill roots declared in the plugin's `.claude-plugin/plugin.json` (plus the conventional `skills/` and `.claude/skills/` folders) into `local/claude-code-plugin-<marketplace>-<plugin>/skills/`. Declared paths cannot escape the plugin root. Skills whose names already exist elsewhere in the library are diverted to `duplicates/` instead of overwriting. Set `UNLIMITED_SKILLS_DISABLE_PLUGIN_SYNC=1` to opt out of plugin discovery only.

Import skills from a local directory or a GitHub repository into the library:

```bash
unlimited-skills import-dir ./my-skills --collection my-team
unlimited-skills import-github obra/superpowers --collection superpowers --ref main
unlimited-skills import-github org/repo --subdir skills --dry-run --json
```

Both commands deduplicate by content (sha256): a skill whose name already exists with identical content is skipped, a skill whose name collides with different content is diverted to the collection's `duplicates/` folder and reported as a conflict, and new skills are imported and structurally adapted. Use `--dry-run` to preview, `--json` for machine-readable reports, and `--skip-reindex` to defer index rebuilds.

Update the local Unlimited Skills core from the public repository:

```bash
unlimited-skills self-update check
unlimited-skills self-update apply
```

Self-update does not require hosted-service registration. It checks the latest public GitHub release for `AI4sale/unlimited-skills`, falls back to the latest tag when releases are not available yet, updates the local source checkout when possible, refreshes the installed Codex router `SKILL.md` without touching its launcher scripts, and rebuilds the local skill index unless `--skip-reindex` is passed.

## How it works

The system has four layers:

1. **Router skill**: a tiny `SKILL.md` that is always visible to the agent.
2. **Disk library**: many real skills stored under a root such as `~/.unlimited-skills/library/registry/<collection>/skills/<name>/SKILL.md` for registry packs and `~/.unlimited-skills/library/local/...` for native agent skills.
3. **Retrieval**: lexical scoring, vector sidecar search with Chroma compatibility storage, and hybrid reranking.
4. **Learning loop**: logs searches, views, selected skills, accepted matches, rejected matches, and new skill drafts.

The v0.2 layout keeps the library root clean:

```text
library/
  registry/<collection>/...   # hosted, community, team, or bundled registry packs
  local/skills/...            # Codex-local and local skill-library content
  local/<agent>/skills/...    # native agent mirrors such as Hermes, Claude Code, OpenClaw
```

Indexing deduplicates by skill name. If ECC, Superpowers, Hermes, or local mirrors contain the same skill name, the router indexes one semantic skill instead of counting every physical copy. The duplicate files may remain on disk, but they do not inflate search/list/vector counts.

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

## Enterprise & trust layer

Everything below is the governed and registered side of the project: signed artifacts, permission profiles, audit tooling, hosted catalogs, team distribution, and policy enforcement. None of it is required for the local core above.

**v0.5.0-alpha / developer preview.** The local-first MIT core is usable today. Hosted registry features are registration-gated early access, catalog browser discovery is signed metadata-only alpha, catalog feedback is explicit and registration-gated, catalog quality and skill improvement status are signed metadata-only diagnostics, Local Skill Hub is allowlist-only alpha, Enterprise Skill Lock is a local policy MVP with registered managed sync, private team packs plus org/team governance diagnostics are registered/entitled alpha paths, plan/billing diagnostics are sandbox-only with no live payment provider, and community catalog install is limited to signed approved/published items. The v0.5.0-alpha packaging milestone verifies wheel/sdist metadata, bundled-pack inclusion, and clean-install first value.

Map of the trust stack:

| Area | Docs |
| --- | --- |
| MCP upstream security model and enforcement | [docs/mcp-upstream-security-model.md](docs/mcp-upstream-security-model.md), [docs/mcp-gateway.md](docs/mcp-gateway.md) |
| Permissioned tool profiles (default-deny) | [docs/mcp-permissioned-tool-profiles.md](docs/mcp-permissioned-tool-profiles.md) |
| Signed profile bundles | [docs/mcp-signed-profile-bundles.md](docs/mcp-signed-profile-bundles.md) |
| Managed trust store | [docs/mcp-trust-store.md](docs/mcp-trust-store.md) |
| Audit inspector, replay, incident drills | [docs/mcp-audit-inspector.md](docs/mcp-audit-inspector.md), [docs/mcp-audit-replay.md](docs/mcp-audit-replay.md), [docs/mcp-incident-runbook.md](docs/mcp-incident-runbook.md) |
| Profile rollout simulator and policy doctor | [docs/mcp-profile-rollout.md](docs/mcp-profile-rollout.md) |
| Enterprise Skill Lock policy | [docs/enterprise-skill-lock.md](docs/enterprise-skill-lock.md), [docs/managed-enterprise-policy-sync.md](docs/managed-enterprise-policy-sync.md) |
| Product editions | [docs/product-editions.md](docs/product-editions.md) |
| Registration, licensing, and privacy boundary | [docs/registration-and-licensing.md](docs/registration-and-licensing.md), [docs/privacy-and-telemetry.md](docs/privacy-and-telemetry.md), [docs/public-core-boundary.md](docs/public-core-boundary.md) |
| Hosted catalog and registry contract | [docs/hosted-registry-api.md](docs/hosted-registry-api.md), [docs/hosted-catalog-model.md](docs/hosted-catalog-model.md), [docs/catalog-browser.md](docs/catalog-browser.md) |
| Community skills | [docs/community-skills.md](docs/community-skills.md), [docs/community-submission-review.md](docs/community-submission-review.md) |
| Teams and private packs | [docs/team-free.md](docs/team-free.md), [docs/team-skill-sync.md](docs/team-skill-sync.md), [docs/private-team-packs.md](docs/private-team-packs.md) |
| Local Skill Hub | [docs/local-skill-hub.md](docs/local-skill-hub.md), [docs/local-skill-hub-security.md](docs/local-skill-hub-security.md) |
| Release channels and rollback | [docs/release-channels.md](docs/release-channels.md), [docs/update-channels-and-rollback.md](docs/update-channels-and-rollback.md) |

### Product editions

See [docs/product-editions.md](docs/product-editions.md) for the full edition table.

- **Community Core**: MIT, local-first, no registration. Local search, list, view, where, use, feedback, reindex, vector-reindex, adapt, serve, installers, migration scripts, native sync, and public self-update stay available offline.
- **Registered Community**: free registration for hosted adapted catalog access, early-access collection updates, registered local enhancer downloads, future official community catalog/submissions, and the Registered Local Skill Hub contract up to 100 active client instances.
- **Team Free**: registered team sync MVP with master approval and up to 10 instances when enforced server-side.
- **Team collaboration roadmap**: hosted collaboration, dashboard, private packs, collection assignment, longer auto-approval windows, and support remain future gated work. The public client includes registered private-pack install/sync commands; registry-side access requires explicit private-pack entitlement.
- **Enterprise**: local Enterprise Skill Lock policy MVP and registered managed policy sync now; private registry enforcement, SSO/on-prem/VPC options later.

Local Skill Hub is separate from the free local daemon: `unlimited-skills serve` remains unregistered, while `unlimited-skills hub serve` is registration-gated and allowlist-only. See [docs/local-skill-hub.md](docs/local-skill-hub.md).

Local Skill Hub is an MVP alpha surface. It defaults to `127.0.0.1`; binding to a LAN address requires explicit `--allow-lan` and at least one active hub client token. For serious LAN deployment, use a reverse proxy or network control with TLS, authentication, access logging, and IP allowlisting. `remote search`, `remote resolve`, and `remote view` call the configured Local Skill Hub over HTTP with hub-token authentication and explicit fallback policy.

Local Skill Hub client setup:

```bash
unlimited-skills hub init --allowlist examples/hub/allowlist-fixture.v1.json
# or, for registered hosted allowlist metadata:
unlimited-skills hub sync
unlimited-skills hub token create --label "codex-laptop"
export ULS_HUB_TOKEN="<hub_client_token>"
unlimited-skills hub serve
unlimited-skills remote configure --url http://127.0.0.1:8766 --token-env ULS_HUB_TOKEN --fallback local_allowed
unlimited-skills remote status
unlimited-skills remote search "security review"
unlimited-skills remote resolve "security review" --agent codex
unlimited-skills remote view security-review
```

Use `--fallback hub_required` when an agent must fail instead of using local fallback. Use `--token <hub_client_token>` only for quick local tests; it stores the raw token in `~/.unlimited-skills/remote.json` with private file permissions where supported.

Remote-first agent install examples:

```bash
./scripts/install-codex.sh --remote-first --remote-hub-url http://127.0.0.1:8766 --hub-token-env ULS_HUB_TOKEN --remote-fallback local_allowed
./scripts/install-claude-code.sh --remote-first --remote-hub-url http://127.0.0.1:8766 --hub-token-env ULS_HUB_TOKEN --remote-fallback local_allowed
./scripts/install-hermes.sh --mode evacuate-visible-skills --remote-first --remote-hub-url http://127.0.0.1:8766 --hub-token-env ULS_HUB_TOKEN --remote-fallback hub_required --apply
./scripts/install-openclaw.sh --remote-first --remote-hub-url http://127.0.0.1:8766 --hub-token-env ULS_HUB_TOKEN --remote-fallback local_allowed
```

The installers write remote hub config under the selected install root and render remote-first router instructions. They prefer `--hub-token-env`; if `--hub-token` is used, the raw token is stored only in private `remote.json` and is not written into visible router files.

Capability-aware install plans:

```bash
unlimited-skills remote capabilities --agent codex --json
unlimited-skills remote install-plan browser-automation --dry-run
```

Retrieval can be centralized, but dependencies and capabilities remain local. The hub never executes skills or installs packages. Install plans are dry-run metadata in this release, and secrets stay client-side.

### Registration and hosted updates

The local core stays free and offline-first. Registration is not required for local search, local migration, local adaptation, bundled base packs, or the router skill.

Registration is required only for AI4sale-hosted services:

- hosted adapted-skill catalog;
- hosted `community-skills` catalog and submissions;
- adapted collection update stream;
- registered local skill enhancement script;
- signed hosted manifests for official hosted delivery metadata;
- SHA256-verified hosted collection archives;
- future dashboard, cloud sync, marketplace, team skill sync, and enterprise features.

Register an installation:

```powershell
unlimited-skills register --agent codex
```

```bash
unlimited-skills register --agent codex
```

Use `--agent claude-code`, `--agent hermes`, or `--agent openclaw` from those surfaces. The registration flow is the same for every agent: the client creates a local installation id and Ed25519 device key, sends only the public key and client metadata to the registry, and stores the returned hosted-service token locally. Hosted API calls must present both the token and a signed device proof.

Check hosted access:

```bash
unlimited-skills license status
```

Configure and diagnose the registered service endpoint:

```bash
unlimited-skills service configure --url https://unlimited.ai4.sale
unlimited-skills service status
unlimited-skills service doctor
unlimited-skills service verify-trust
unlimited-skills service test-registration --dry-run --agent codex
unlimited-skills service test-proof
```

`service status` is local-only unless `--refresh` is passed. `service doctor` contacts only `/health`, optional `/ready`, and `/v1/public-keys`, and prints the exact endpoint list. Service diagnostics do not upload skill bodies, skill names, prompts, search queries, local paths, repository paths, environment values, tokens, or private keys. See [docs/production-registry-onboarding.md](docs/production-registry-onboarding.md) and [docs/service-diagnostics.md](docs/service-diagnostics.md).

Check and apply hosted adapted collection updates:

```bash
unlimited-skills catalog list
unlimited-skills updates check
unlimited-skills updates apply
```

Hosted catalog/update access is registration-gated early access. A clean registered install should receive starter catalog metadata and updates for `ecc` and `superpowers`; additional hosted catalog contents are delivered through registered catalog/update commands as they become available.

Browse signed reviewed catalog metadata:

```bash
unlimited-skills catalog browse --source community --compatible-agent codex
unlimited-skills catalog search "browser qa" --source community
unlimited-skills catalog filters
unlimited-skills catalog preview <catalog-item-id>
unlimited-skills catalog install <catalog-item-id> --dry-run
```

Catalog browser responses must be signed, metadata-only, and approved or published before install can proceed. Community-source installs delegate to the Community Skills install flow after the signed browser metadata check. Official and private-visible browser items are metadata/dry-run only until dedicated install-plan capability checks are implemented. The v0.3.6 release gate verifies public fixture mode without a private checkout and local registry mode when `<private-registry-checkout>` is available. See [docs/catalog-browser.md](docs/catalog-browser.md) and [docs/releases/v0.3.6-alpha.md](docs/releases/v0.3.6-alpha.md).

Catalog feedback is explicit only. `catalog feedback` requires registration and confirmation, `--dry-run` sends nothing, and feedback payloads are redacted before submit. See [docs/catalog-feedback.md](docs/catalog-feedback.md).

Browse, preview, install, and submit registered community skills:

```bash
unlimited-skills community list
unlimited-skills community search "browser qa"
unlimited-skills community preview <catalog-item-id>
unlimited-skills community install <catalog-item-id> --dry-run
unlimited-skills community install <catalog-item-id> --yes
unlimited-skills community submit ./my-skill --dry-run
unlimited-skills community submit ./my-skill --yes
unlimited-skills community submission-status
unlimited-skills community installed
unlimited-skills community remove community --dry-run
```

`catalog` is the official registered hosted catalog and collection metadata. `community` is the user-facing community discovery, submission, install, and local management flow. Community list/search/preview/install/status calls do not upload local skill bodies. `community submit` is the explicit exception: it uploads only the selected skill or pack after local validation, preview generation, and confirmation. Community preview and install require signed hosted metadata, and install is allowed only for signed items whose review status is `approved` or `published`.

Download and run the registered local enhancer:

```bash
unlimited-skills enhance download
unlimited-skills enhance run
unlimited-skills enhance run --apply
```

`enhance run` is a dry run unless `--apply` is passed. The enhancer script is downloaded from the official registry, checksum-verified, cached locally, and then runs on your machine. It does not send skill bodies or prompts to the registry.

The registration file is stored at:

```text
~/.unlimited-skills/registration.json
```

The registry client sends only install id, public device key, key thumbprint, client version, collection versions, source labels, and skill-count buckets. It does not send skill bodies, prompts, source code, skill names, full local paths, repository paths, customer names, environment variables, device private keys, tokens, or secrets. See [docs/privacy-and-telemetry.md](docs/privacy-and-telemetry.md).

For the public client-facing hosted registry contract, see [docs/hosted-registry-api.md](docs/hosted-registry-api.md), [docs/hosted-catalog-model.md](docs/hosted-catalog-model.md), and [docs/registry-contract-tests.md](docs/registry-contract-tests.md).

Using the hosted `community-skills` catalog or pushing skills into it also requires registration. Submitting to `community-skills` is an explicit upload of the selected skill or pack, not background telemetry. See [docs/community-skills.md](docs/community-skills.md) and [docs/community-submission-review.md](docs/community-submission-review.md).

Team Free: registered teams can create a team, join instances, approve or reject pending instances, revoke old instances, list members and assigned collections, dry-run sync, and synchronize assigned catalog collections across approved team nodes. The first node that runs `team create` becomes the master. A join code alone does not grant sync access. Default team mode is manual approval. The master may enable auto-approval for up to 24 hours on community plans; longer windows require business or enterprise access. Team Free supports up to 10 approved instances when enforced server-side. See [docs/team-free.md](docs/team-free.md), [docs/team-sync.md](docs/team-sync.md), and [docs/team-skill-sync.md](docs/team-skill-sync.md).

```bash
unlimited-skills team create --name "My Team"
unlimited-skills team join <join-code> --display-name "Hermes laptop"
unlimited-skills team status --json
unlimited-skills team members
unlimited-skills team pending
unlimited-skills team approve <install-id>
unlimited-skills team reject <install-id> --reason "not recognized"
unlimited-skills team revoke <install-id> --reason "old machine" --yes
unlimited-skills team mode manual
unlimited-skills team mode auto --duration 6h
unlimited-skills team collections
unlimited-skills team sync --dry-run
unlimited-skills team sync --yes
unlimited-skills team leave --yes
```

Private team packs: registered installations can list, preview, install, sync, and remove team-scoped private packs. Installs verify signed `private-team-pack` manifests, use proofed POST downloads, check SHA256, safely extract zip archives, and write only under `registry/private/<pack_id>`. See [docs/private-team-packs.md](docs/private-team-packs.md).

```bash
unlimited-skills private-packs list
unlimited-skills private-packs preview <pack_id>
unlimited-skills private-packs install <pack_id> --yes
unlimited-skills private-packs sync --dry-run
unlimited-skills private-packs sync --yes
unlimited-skills private-packs installed
unlimited-skills private-packs remove <pack_id> --yes
```

Enterprise Skill Lock MVP lets managed instances audit or refuse unmanaged skill delivery and direct operators to a corporate administrator or approved enterprise update channel. No policy means Community Core behavior is unchanged.

```bash
unlimited-skills policy status
unlimited-skills policy verify enterprise-policy.json
unlimited-skills policy install enterprise-policy.json
unlimited-skills policy explain
unlimited-skills policy remove --yes
```

See [docs/enterprise-skill-lock.md](docs/enterprise-skill-lock.md).

Business and enterprise access starts with a company registration request at [https://unlimited.ai4.sale/enterprise](https://unlimited.ai4.sale/enterprise). That page collects basic company, rollout, pricing, and deployment-model context; it is separate from the community CLI self-registration flow.

### Verified registered and governance surfaces

Working now:

- registered-installation state for hosted catalog and adapted collection updates;
- hosted update client with SHA256-verified collection archives;
- registered hosted catalog client;
- registered signed catalog browser for reviewed metadata search, filters, preview, and dry-run install verification;
- explicit registered catalog feedback for redacted catalog quality signals;
- registered community skills client for list/search/preview/install/submit/status/local remove with signed approved/published install enforcement;
- registered Team Free create/join/members/pending/approve/reject/revoke/collections/sync/leave client;
- registered private team pack client for list/preview/install/sync/installed/remove under `registry/private/<pack_id>`;
- registered private pack access diagnostics with redacted `private-packs access-check <pack_id>` output;
- local/cache org and team governance diagnostics with `org status`;
- local/cache plan diagnostics with `plan status`, `plan explain`, and `plan doctor`;
- registered plan refresh through `/v1/hub/entitlements`;
- local/cache billing lifecycle diagnostics with `billing status` and `billing doctor`;
- registered sandbox billing refresh through `/v1/hub/billing-status`;
- registered signed skill improvement status, known issues, deprecated/retired warnings, and preview-only update recommendations;
- v0.3.9-alpha cross-repo skill improvement integration gate proving feedback/evals -> improvement backlog -> maintainer triage -> catalog quality report -> public signed recommendations;
- v0.4 policy-aware recommendation runtime preview with `catalog recommendation-preview`, combining signed catalog metadata with quality, improvement, entitlement, and policy signals without applying changes;
- v0.4.0-alpha E01-E04 integration gate for policy-aware recommendation preview, eval release operator workflow, maintainer queue runtime/status, and governance dashboard signed summaries without production rollout;
- v0.4.1-alpha Reliability publication gate for transactional installs, rollback manifests, `VectorModelMismatch`, modular CLI command routing, and `skillops usage-snapshot` compatibility after the CLI split;
- v0.4.2-alpha MCP integration gate for `unlimited-skills mcp serve`, `unlimited-skills mcp gateway`, compact `tools_search`, single-tool `tools_schema`, fixture `tools_call`, lazy upstream spawn/reuse, audit redaction, and the E07 upstream security model contract;
- v0.4.3-alpha MCP upstream enforcement gate for disabled upstream refusal, future remote refusal, command allowlists, names-only `env_allowlist`, size/timeouts, audit rotation, audit redaction, no OAuth, no remote upstreams, no resources, no prompts, no hosted gateway, and no shell execution;
- v0.4.4-alpha MCP permissioned tool profile enforcement integration gate for default-deny profiles, visible-only search, non-callable call refusals, restriction-only inheritance, fail-closed missing/invalid profiles, `profile_loaded` audit rows, profile SHA-256 evidence, no OAuth, no remote upstreams, no resources, no prompts, no hosted gateway, and no production hosted calls;
- v0.4.5-alpha MCP audit inspector integration gate for read-only `mcp audit-report`, JSON schema-validated reports, rotated audit log discovery, safe recent refusal summaries with no argument values and no error text, profile audit evidence, redaction self-checks, and clear missing-log exits;
- v0.4.7-alpha signed MCP profile bundle integration gate for local verification before gateway profile loading. It proves raw local profile compatibility, valid signed bundle loading, fail-closed refusals for bad signatures, unknown keys, expiry, revocation, wrong audience, and namespace violations, plus audit provenance with no hosted trust fetch, no registry sync, and no production signing keys. This alpha may break before v0.6; the local MIT core may still allow unsigned profiles by policy, and registered/business signed-required behavior is future-gated unless explicitly implemented in a later gate;
- v0.4.8-alpha managed MCP profile trust store integration gate for `unlimited-skills mcp trust status|list|import|revoke|doctor`. It proves local/offline public-key import, key listing with abbreviated fingerprints, append-only local CRL revocation, doctor checks for corrupt trust store files, managed trusted-key verification, revoked key refusal, missing trust store refusal, explicit trusted-keys override behavior, unreadable CRL fail-closed behavior, and audit provenance with no hosted trust fetch, no registry sync, no production signing keys, no private key storage, no OAuth, no resources, and no prompts;
- v0.4.9-alpha MCP profile rollout simulator final publication gate for `unlimited-skills mcp profiles rollout-plan|doctor`. It proves raw profile rollout plan, signed bundle rollout plan, trust-store-backed rollout plan, missing trust store, corrupt trust store, expired key, revoked key, wrong audience, namespace violation, hide-all-tools, shadowed tool, signed-required unsigned-source, and no upstream spawn / no network / no mutation boundaries;
- private team pack setup, service diagnostics, doctor, and redacted support bundle summaries;
- production service onboarding diagnostics for configured service URL, health, trust, redacted registration dry run, and local proof generation;
- service diagnostics v2 shared by setup and support workflows, with explicit network checks and redacted output;
- Enterprise Skill Lock policy MVP for governed registries, channels, signing keys, local roots, community install/submit, hub allowlists, and remote fallback;
- managed Enterprise Skill Lock policy sync from a registered registry with signed `enterprise-policy` assignment verification and dry-run support;
- allowlist-backed Local Skill Hub runtime MVP for local/controlled LAN testing when `server` extras are installed;
- Local Skill Hub allowlist bootstrap/sync with validated cached allowlist metadata;
- required signed hosted manifest verification for hub allowlists, collection updates, enhancement manifests, and team sync manifests;
- production-shaped registry contract E2E coverage for device proof, retries, offline metadata cache, hub heartbeat, entitlements, and team sync;
- release channel UX for registered catalog/update checks: signed channel status, local stable/beta/canary pinning, one-off channel overrides, and local collection rollback snapshots;
- bundled/local/env trusted manifest keys with scope enforcement, registry-origin pinning, and local revocation;
- remote Local Skill Hub client commands: `remote configure`, `remote status`, `remote search`, `remote resolve`, and `remote view`.

In development:

- v0.4 readiness audit and SkillOps architecture RFC for governed delivery, eval-driven release gates, maintainer improvement queues, governance dashboards, optional self-hosted registry mode, and future human-reviewed automatic improvement proposals;
- v0.4 cross-repo readiness suite that verifies public client and private registry readiness contracts in fixture mode or against a local private registry checkout without production hosted calls, production signing keys, live billing, PyPI publication, full catalog distribution, automatic install/update/remove, automatic skill rewriting, or auto-publish;
- v0.4 go/no-go decision package that recommends GO for the first four implementation epics after review and merge while keeping production rollout behind per-epic review gates;
- v0.4.9-alpha MCP profile rollout simulator is the active release gate for the MCP profile distribution milestone;
- persistent warm daemon as the default agent retrieval path;
- richer learning loop for accepted/rejected matches;
- automatic skill drafting from repeated task patterns;
- stronger per-agent installers and config adapters;
- hosted registry service hardening and broader early-access onboarding.

### Release milestone docs

For the v0.4.9-alpha MCP profile rollout simulator milestone,
see [docs/releases/v0.4.9-alpha.md](docs/releases/v0.4.9-alpha.md),
[docs/releases/v0.4.9-alpha-checklist.md](docs/releases/v0.4.9-alpha-checklist.md),
[docs/releases/v0.4.9-alpha-upgrade-notes.md](docs/releases/v0.4.9-alpha-upgrade-notes.md),
and [docs/releases/v0.4.9-alpha-known-issues.md](docs/releases/v0.4.9-alpha-known-issues.md).
For the v0.4.8-alpha managed MCP profile trust store integration milestone,
see [docs/releases/v0.4.8-alpha.md](docs/releases/v0.4.8-alpha.md),
[docs/releases/v0.4.8-alpha-checklist.md](docs/releases/v0.4.8-alpha-checklist.md),
and [docs/releases/v0.4.8-alpha-known-issues.md](docs/releases/v0.4.8-alpha-known-issues.md).
For the v0.4.7-alpha signed MCP profile bundle integration milestone, see
[docs/releases/v0.4.7-alpha.md](docs/releases/v0.4.7-alpha.md),
[docs/releases/v0.4.7-alpha-checklist.md](docs/releases/v0.4.7-alpha-checklist.md),
and [docs/releases/v0.4.7-alpha-known-issues.md](docs/releases/v0.4.7-alpha-known-issues.md).

For the v0.4.5-alpha MCP audit inspector milestone, see [docs/releases/v0.4.5-alpha.md](docs/releases/v0.4.5-alpha.md), [docs/releases/v0.4.5-alpha-checklist.md](docs/releases/v0.4.5-alpha-checklist.md), [docs/releases/v0.4.5-alpha-upgrade-notes.md](docs/releases/v0.4.5-alpha-upgrade-notes.md), and [docs/releases/v0.4.5-alpha-known-issues.md](docs/releases/v0.4.5-alpha-known-issues.md). For the v0.4.4-alpha MCP permissioned tool profile integration milestone, see [docs/releases/v0.4.4-alpha.md](docs/releases/v0.4.4-alpha.md), [docs/releases/v0.4.4-alpha-checklist.md](docs/releases/v0.4.4-alpha-checklist.md), [docs/releases/v0.4.4-alpha-upgrade-notes.md](docs/releases/v0.4.4-alpha-upgrade-notes.md), and [docs/releases/v0.4.4-alpha-known-issues.md](docs/releases/v0.4.4-alpha-known-issues.md). For the v0.4.3-alpha MCP enforcement milestone, see [docs/releases/v0.4.3-alpha.md](docs/releases/v0.4.3-alpha.md), [docs/releases/v0.4.3-alpha-checklist.md](docs/releases/v0.4.3-alpha-checklist.md), [docs/releases/v0.4.3-alpha-upgrade-notes.md](docs/releases/v0.4.3-alpha-upgrade-notes.md), and [docs/releases/v0.4.3-alpha-known-issues.md](docs/releases/v0.4.3-alpha-known-issues.md). For the v0.4.2-alpha MCP milestone, see [docs/releases/v0.4.2-alpha.md](docs/releases/v0.4.2-alpha.md), [docs/releases/v0.4.2-alpha-checklist.md](docs/releases/v0.4.2-alpha-checklist.md), [docs/releases/v0.4.2-alpha-upgrade-notes.md](docs/releases/v0.4.2-alpha-upgrade-notes.md), and [docs/releases/v0.4.2-alpha-known-issues.md](docs/releases/v0.4.2-alpha-known-issues.md). For the v0.4.1-alpha reliability candidate, see [docs/releases/v0.4.1-alpha.md](docs/releases/v0.4.1-alpha.md), [docs/releases/v0.4.1-alpha-checklist.md](docs/releases/v0.4.1-alpha-checklist.md), [docs/releases/v0.4.1-alpha-upgrade-notes.md](docs/releases/v0.4.1-alpha-upgrade-notes.md), and [docs/releases/v0.4.1-alpha-known-issues.md](docs/releases/v0.4.1-alpha-known-issues.md). For the v0.4.0-alpha foundation tag, see [docs/releases/v0.4.0-alpha.md](docs/releases/v0.4.0-alpha.md). For v0.4 planning, see [docs/releases/v0.4-readiness-audit.md](docs/releases/v0.4-readiness-audit.md), [docs/rfcs/v0.4-skillops-platform-rfc.md](docs/rfcs/v0.4-skillops-platform-rfc.md), [docs/rfcs/v0.4-risk-register.md](docs/rfcs/v0.4-risk-register.md), and [docs/rfcs/v0.4-implementation-epics.md](docs/rfcs/v0.4-implementation-epics.md).

## Support

Unlimited Skills is open source under the MIT license. Voluntary donations help fund adapters, migration scripts, indexing work, hosted registry maintenance, and the learning-loop roadmap.

Donate at [https://opportunity.ai4.sale/donate/unlimited-skills](https://opportunity.ai4.sale/donate/unlimited-skills), use GitHub's Sponsor button generated from [.github/FUNDING.yml](.github/FUNDING.yml), or see [DONATE.md](DONATE.md).

Donations are voluntary support payments. They are non-refundable unless a separate written agreement says otherwise, and they are not investments, securities, loans, equity, revenue share, voting rights, ownership interests, subscriptions, pre-orders, or purchases of hosted-service access. See [SERVICE-TERMS.md](SERVICE-TERMS.md).

## License

The repository source code is MIT licensed. See [LICENSE](LICENSE).

The MIT license covers the local Community Core: router, installers, migrations, local search, local daemon, local learning logs, and bundled repository contents.

AI4sale-hosted catalog access, `community-skills` catalog/submissions, adapted collection update streams, registered local enhancement scripts, SHA256-verified hosted archives, dashboard features, support, cloud sync, marketplace, team skill sync, Enterprise Skill Lock, and enterprise private registries require a registered installation and are governed separately. See [docs/registration-and-licensing.md](docs/registration-and-licensing.md) and [SERVICE-TERMS.md](SERVICE-TERMS.md).
