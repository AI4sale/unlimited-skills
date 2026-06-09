<div align="center">

# Lord of the Skills

<pre>
+--------------------------------------------------------------+
|                 One skill to rule them all.                  |
+--------------------------------------------------------------+
</pre>

**Unlimited Skills** is a local skill memory and retrieval layer for coding agents.

Keep thousands of `SKILL.md` files out of the always-loaded context. Ask one tiny router skill what the task needs. Load only the selected skill.

**v0.3.0 alpha / developer preview.** The local-first MIT core is usable today. Hosted registry features are registration-gated early access, Local Skill Hub is allowlist-only alpha, and Enterprise Skill Lock is a local policy MVP with registered managed sync.

[Donate to Unlimited Skills](https://opportunity.ai4.sale/donate/unlimited-skills) · [Donation terms](DONATE.md)

</div>

## What it is

Unlimited Skills turns a folder full of skills into an action library for agents.

It is built around one practical rule: the agent should not know every skill all the time. It should know how to ask for the right skill when work starts.

The current version is built for Codex first, with full installers for Codex, Claude Code, OpenClaw, and Hermes, plus migration scripts for Codex, Claude Code, OpenClaw, Hermes, and Vellum AI.

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
- local vector sidecar index with ChromaDB compatibility storage;
- hybrid lexical + vector search;
- full skill view by name;
- Codex router skill;
- agent-driven one-skill adaptation workflow;
- usage and feedback logs;
- draft generation for new skills;
- migration scripts for Codex, Claude Code, OpenClaw, Hermes, and Vellum AI;
- OpenClaw installer for workspace/plugin/built-in skills;
- Claude Code installer for personal/project skills and `CLAUDE.md` patching;
- Hermes router-only context-reduction installer and rollback scripts;
- registered-installation state for hosted catalog and adapted collection updates;
- hosted update client with SHA256-verified collection archives;
- registered hosted catalog client;
- registered community skills client for list/search/preview/install/submit/status/local remove;
- registered Team Free create/join/members/pending/approve/reject/revoke/collections/sync/leave client;
- native skill sync for Codex, Claude Code, Hermes, and OpenClaw roots;
- public repo self-update checks and applies latest releases/tags;
- production service onboarding diagnostics for configured service URL, health, trust, redacted registration dry run, and local proof generation;
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

- persistent warm daemon as the default agent retrieval path;
- richer learning loop for accepted/rejected matches;
- automatic skill drafting from repeated task patterns;
- stronger per-agent installers and config adapters;
- hosted registry service hardening and broader early-access onboarding.

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

PyPI packaging is not the supported v0.3.0-alpha distribution path. Install from a GitHub clone for now, because the router skills, scripts, docs, and bundled packs are repo assets. A PyPI package should wait until wheel/sdist asset inclusion and installer behavior are tested in CI.

For release scope and known limitations, see [CHANGELOG.md](CHANGELOG.md), [docs/packaging.md](docs/packaging.md), [docs/install-upgrade-uninstall.md](docs/install-upgrade-uninstall.md), and [SECURITY.md](SECURITY.md). For the previous v0.2.2-alpha gate, see [docs/releases/v0.2.2-alpha.md](docs/releases/v0.2.2-alpha.md).

## Product Editions

See [docs/product-editions.md](docs/product-editions.md) for the full edition table.

- **Community Core**: MIT, local-first, no registration. Local search, list, view, where, use, feedback, reindex, vector-reindex, adapt, serve, installers, migration scripts, native sync, and public self-update stay available offline.
- **Registered Community**: free registration for hosted adapted catalog access, early-access collection updates, registered local enhancer downloads, future official community catalog/submissions, and the Registered Local Skill Hub contract up to 100 active client instances.
- **Team Free**: registered team sync MVP with master approval and up to 10 instances when enforced server-side.
- **Pro / Team**: planned paid hosted collaboration, dashboard, private packs, collection assignment, longer auto-approval windows, and support.
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

## Support

Unlimited Skills is open source under the MIT license. Voluntary donations help fund adapters, migration scripts, indexing work, hosted registry maintenance, and the learning-loop roadmap.

Donate at [https://opportunity.ai4.sale/donate/unlimited-skills](https://opportunity.ai4.sale/donate/unlimited-skills), use GitHub's Sponsor button generated from [.github/FUNDING.yml](.github/FUNDING.yml), or see [DONATE.md](DONATE.md).

Donations are voluntary support payments. They are non-refundable unless a separate written agreement says otherwise, and they are not investments, securities, loans, equity, revenue share, voting rights, ownership interests, subscriptions, pre-orders, or purchases of hosted-service access. See [SERVICE-TERMS.md](SERVICE-TERMS.md).

## Registration and Hosted Updates

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

`catalog` is the official registered hosted catalog and collection metadata. `community` is the user-facing community discovery, submission, install, and local management flow. Community list/search/preview/install/status calls do not upload local skill bodies. `community submit` is the explicit exception: it uploads only the selected skill or pack after local validation, preview generation, and confirmation.

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

Download and run the registered local enhancer:

```bash
unlimited-skills enhance download
unlimited-skills enhance run
unlimited-skills enhance run --apply
```

`enhance run` is a dry run unless `--apply` is passed. The enhancer script is downloaded from the official registry, checksum-verified, cached locally, and then runs on your machine. It does not send skill bodies or prompts to the registry.

Update the local Unlimited Skills core from the public repository:

```bash
unlimited-skills self-update check
unlimited-skills self-update apply
```

Self-update does not require hosted-service registration. It checks the latest public GitHub release for `AI4sale/unlimited-skills`, falls back to the latest tag when releases are not available yet, updates the local source checkout when possible, refreshes the installed Codex router `SKILL.md` without touching its launcher scripts, and rebuilds the local skill index unless `--skip-reindex` is passed.

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

For Codex, patching `AGENTS.md` is the default. If `AgentsFile` / `--agents-file` is not passed, the installer patches `~/.codex/AGENTS.md` so the router is available at the Codex system level. Pass an explicit project `AGENTS.md` path only when you intentionally want project-local instructions. Existing `AGENTS.md` content is backed up as `Agents_md_YYYYMMDD_HHMMSS.back`, ECC managed blocks are replaced, and the Unlimited Skills managed block is replaced in place on repeat installs. Use `-NoAgentsPatch` or `--no-agents-patch` to skip it.

The installer creates an isolated venv under `~/.codex/.unlimited-skills/.venv`, stores the Codex library under `~/.codex/.unlimited-skills/library`, and writes a Codex-local launcher:

```text
~/.codex/skills/unlimited-skills/scripts/unlimited-skills.ps1
~/.codex/skills/unlimited-skills/scripts/unlimited-skills.sh
```

Restart Codex after installing the router skill.

## Install for Claude Code

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
.\scripts\install-claude-code.ps1 -ClaudeFile C:\path\to\project\CLAUDE.md
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

## License

The repository source code is MIT licensed. See [LICENSE](LICENSE).

The MIT license covers the local Community Core: router, installers, migrations, local search, local daemon, local learning logs, and bundled repository contents.

AI4sale-hosted catalog access, `community-skills` catalog/submissions, adapted collection update streams, registered local enhancement scripts, SHA256-verified hosted archives, dashboard features, support, cloud sync, marketplace, team skill sync, Enterprise Skill Lock, and enterprise private registries require a registered installation and are governed separately. See [docs/registration-and-licensing.md](docs/registration-and-licensing.md) and [SERVICE-TERMS.md](SERVICE-TERMS.md).
