# Changelog

## Unreleased

### Added

- E07 design (docs/schema only, no implementation): MCP upstream configuration and security model (`docs/mcp-upstream-security-model.md`) — per-upstream trust levels (`disabled` / `local-restricted` default / `local-trusted` / `future-remote-placeholder`), command allowlisting (no shell, absolute-path-or-known-binary), forward-nothing environment policy with a names-only `env_allowlist` (wildcards unrepresentable), bounded timeouts and schema/response size caps with refusal-not-truncation, audit levels and JSONL rotation/retention, extended refusal codes `-32005`…`-32010` (`upstream_disabled`, `command_not_allowed`, `env_forwarding_denied`, `schema_too_large`, `response_too_large`, `trust_level_violation`), a 9-vector threat model, and explicit future gates for OAuth/remote upstreams and MCP resources/prompts.
- `schemas/mcp-upstream-config.schema.json` (draft 2020-12) and validated annotated example `examples/mcp/upstreams.example.json`; `tests/test_mcp_upstream_config_schema.py` validates the example against the schema with a minimal self-contained validator (positive plus negative cases: unknown trust level, env wildcard, v1 `env` literal map, oversize/zero limits).
- E08: the gateway now ENFORCES the E07 upstream security model (`tests/test_mcp_upstream_enforcement.py`): trust levels (`disabled`/`enabled:false` upstreams are never spawned, never indexed, refused with `-32005`; `future-remote-placeholder` refuses all I/O with `-32010`), the command allowlist (absolute path required at `local-restricted`, frozen known-runner bare names — `node`, `npx`, `bunx`, `deno`, `python`, `python3`, `uv`, `uvx` — at `local-trusted`, shell binaries and relative paths refused everywhere with `-32006`), names-only env forwarding over a fixed minimal base set (`-32007` on violations), schema/response size caps with trust-level ceilings and refusal-not-truncation (`-32008`/`-32009`), timeout hard bounds (startup ≤ 120 s, request ≤ 300 s; out-of-range config rejected at load), per-upstream `audit_level` (`standard`/`minimal`, no `off`), and size-based audit JSONL rotation (`audit_max_bytes` default 10 MiB, `audit_max_files` default 5).

- Unlimited Tools MCP core (`unlimited_skills/mcp/`): a zero-dependency JSON-RPC 2.0 / MCP stdio implementation (no external MCP SDK) with auto-detected framing (newline-delimited JSON and LSP-style `Content-Length`), MCP lifecycle (`initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`), and a reusable `StdioServer` loop over a tool registry.
- `unlimited-skills mcp serve`: a skills MCP server exposing `skills_search` (metadata-only hits — never bodies or absolute paths), `skills_view` (one skill body capped at 16K chars with truncation marker), and `skills_use` (view plus a local learning event; reads SKILL.md text only, never executes scripts).
- `unlimited-skills mcp gateway --config ... [--audit-log ...]`: the Unlimited Tools gateway fronting upstream stdio MCP servers with 3 meta-tools — `tools_search` (names + descriptions only, never schemas), `tools_schema` (exactly one tool's `inputSchema`, lazily), `tools_call` (routed and relayed). Upstreams spawn lazily on first need, are reused, and are terminated on shutdown; the tool index is cached in-memory per process.
- Redacted append-only MCP audit log (`<library>/.learning/mcp-audit.jsonl` by default) recording `ts`, `tool`, `upstream`, `duration_ms`, `ok` for every meta-tool call.
- Schemas `mcp-server-config`, `mcp-gateway-config`, `mcp-tool-index` (draft-07); examples `examples/mcp/gateway-config.example.json` and `tools-call-request.example.json`; docs `docs/unlimited-tools.md`, `docs/mcp-server.md`, `docs/mcp-gateway.md`.
- Fixture-only MCP tests: protocol framing/lifecycle/error codes, skills server metadata boundaries and caps, gateway lazy spawn + routing against a fake subprocess upstream, audit redaction.

- Local-only `skillops usage-snapshot` command with JSON, `--out`, `--dry-run`, and `explain` modes for privacy-preserving SkillOps recommendation context.
- Usage snapshot schema, example payload, and documentation covering included counts, excluded sensitive data, and no-hosted-call behavior.
- Support bundle counts-only usage snapshot summary.
- v0.4.1-alpha Reliability publication package: release notes, checklist, upgrade notes, known issues, release manifest, reliability smoke runner, release smoke runner, and publication verifier.
- Post-tag `v0.4.0-alpha` release smoke compatibility: the v0.4.0 smoke can verify that the published tag points to the expected release-owner commit without letting Codex create or overwrite tags.

### Security

- MCP servers are stdio-only and local-only: no network listeners, no OAuth upstreams, no MCP resources/prompts in v1.
- BREAKING (pre-0.6, no shim): the v1 gateway upstream `env` literal map (`{"X": "%X%"}`) is rejected at config load with a pointer to `env_allowlist`. Upstreams now receive a from-scratch environment: a fixed minimal base set (`COMSPEC` excluded — no shell) plus only the variable names in `env_allowlist`, copied from the local environment and never logged. The gateway's own working directory is never inherited (per-upstream scratch dir or explicit absolute `cwd`); the superseded draft-07 `schemas/mcp-gateway-config.schema.json` was removed in favor of `schemas/mcp-upstream-config.schema.json`.
- MCP audit redaction: argument values for keys matching token/secret/key/password/proof/authorization are never written; env values, skill bodies, and tool results are never written (only shapes/counts); local paths are scrubbed from error strings; `redact()` is a pure tested function.
- Usage snapshots exclude prompts, task text, skill bodies, search queries, local paths, repo paths, customer data, environment values, tokens, proofs, private keys, private pack names, and private skill names by default.
- Usage snapshot tests block hosted calls and grep fixture secrets/private names/paths from CLI, file output, and support bundle summary.
- The v0.4.1-alpha publication gate keeps production hosted calls, live billing, PyPI publication, full catalog distribution, automatic telemetry, automatic rewriting, and auto-publish disabled.

## v0.4.1-alpha

### Added

- Transactional installs for all agents. The Claude Code, OpenClaw, and Hermes installers now record every destructive step (router replacement, CLAUDE.md/AGENTS.md patches, library skill copies, index rewrites, remote config) in a schema v2 rollback manifest under `<install-root>/backups/`, generalizing the manifest that previously existed only for Hermes (`installers/common.py`: `InstallTransaction`, `rollback_install`).
- If an install fails midway, the already-applied steps are rolled back automatically before the error propagates.
- `--rollback MANIFEST [--rollback-apply]` flags on the Claude Code and OpenClaw installers (dry-run by default); Hermes `rollback` keeps its existing subcommand and still understands old v1 manifests.
- `VectorModelMismatch`: searching with a different embedding model than the one the vector index was built with (`UNLIMITED_SKILLS_EMBED_MODEL` / `--model`) is now a clear error telling you to run `vector-reindex`, instead of silently ranking with incomparable stale embeddings. Hybrid search degrades to lexical with a stderr warning; `--require-vector` raises.
- Tests for generic rollback, mid-install failure rollback, reinstall router restore, and model-mismatch detection.

### Changed

- `cli.py` was split from ~3.4k lines down to ~1.6k: all command bodies moved into `unlimited_skills/commands/` (library, catalog, community, private-packs, accounts, team, policy, service, updates). `unlimited_skills.cli` re-exports every command, so existing imports and monkeypatch points keep working; CLI behavior, arguments, and output are unchanged.
- Shared `migrate_source`/`existing_skill_names`/`MigrationResult` now live in `installers/common.py` instead of being duplicated per installer.
- Backup directories are uniquified, so two installs in the same second can no longer clobber each other's rollback manifest.
- Package and plugin manifests are raised to `0.4.1` by the v0.4.1-alpha publication gate, matching how `0.4.0` was bumped by the v0.4.0-alpha publication PR.

## v0.4.0-alpha

### Added

- Final v0.4.0-alpha SkillOps foundation publication package: release notes, checklist, upgrade notes, known issues, release manifest, final release smoke runner, and publication verifier.
- Draft GitHub release notes and human tag command for release-owner publication after the final `main` SHA is verified.
- Publication verifier coverage for package/plugin version consistency, required public/private PR traceability, metadata-only SkillOps boundaries, release-owner tag approval, no production hosted calls, no live billing, no PyPI, no full catalog distribution, no automatic install/update/remove/rewrite/reindex, no auto-publish, and public-doc private material scanning.

### Changed

- Raised package version to `0.4.0` for the `v0.4.0-alpha` tag.
- Updated Claude Code plugin and marketplace metadata to version `0.4.0`.
- Updated v0.2x smoke isolation to override `CODEX_HOME`, `CLAUDE_HOME`, and `OPENCLAW_HOME` in addition to `HOME`, `USERPROFILE`, `UNLIMITED_SKILLS_HOME`, and `HERMES_HOME`.
- Promoted README, SECURITY, and known-limitations wording from the v0.3.9 developer preview to the v0.4.0-alpha SkillOps foundation milestone.

### Security

- Codex must not create or push the final `v0.4.0-alpha` tag. The release owner verifies the final `main` SHA and runs the human tag command.
- The milestone keeps the MIT local core registration-free and keeps hosted/registry behavior signed, metadata-only, and explicitly gated.
- The release does not authorize production rollout, live billing, PyPI publication, full catalog distribution, automatic install/update/remove, automatic rewriting, automatic reindexing, or auto-publish.

## v0.3.13

### Added

- `import-dir <path> --collection <name>` command: import skills from any local directory into the library with sha256-based dedup and a conflict report. Same name + identical content is skipped; same name + different content is diverted to the collection's `duplicates/` folder and reported; new names are imported and adapted.
- `import-github <org/name|url> [--ref] [--subdir] [--collection]` command: shallow-clone a repo and import its skills through the same dedup pipeline. Repo spec and subdir are validated against injection/path-escape.
- Both commands support `--dry-run` (report without writing), `--skip-reindex`, and `--json`.
- Shared `unlimited_skills/frontmatter.py` module backed by PyYAML, replacing three separate hand-rolled line parsers (`cli.py`, `adapters.py`, `community.py`). Correctly handles multi-line scalars, colons inside values, YAML lists, and nested maps; falls back to the legacy line parser when PyYAML is absent.
- `NativeSyncResult.duplicate_count` so `sync-native --json` reports how many skills were diverted as duplicates.
- Tests for import dedup/conflict/dry-run and the new frontmatter parser (`tests/test_import_and_frontmatter.py`).

### Changed

- Added `PyYAML>=6,<7` as a dependency (the frontmatter parser degrades gracefully if it is missing).
- Raised package version to `0.3.13`.

## v0.3.12

### Added

- Unlimited Skills now ships as a native Claude Code plugin: `.claude-plugin/marketplace.json` (marketplace manifest) plus `plugin/` (plugin root with `.claude-plugin/plugin.json`, router skill, and hooks). Install with `/plugin marketplace add AI4sale/unlimited-skills` then `/plugin install unlimited-skills@unlimited-skills`.
- `SessionStart` hook (`plugin/hooks/session_start.py`) injects a short router contract into every Claude Code session, making routing deterministic instead of dependent on `CLAUDE.md` state or skill-list visibility. If the `unlimited-skills` CLI is missing from `PATH`, the hook prints an install hint instead. The hook always exits 0 and emits no skill bodies, prompts, paths, or private data.
- Plugin router skill variant without machine-specific launcher paths (calls the `unlimited-skills` CLI from `PATH`).
- `docs/claude-code-plugin.md` covering install, plugin-vs-installer comparison, and privacy boundaries; README Claude Code section now lists the plugin as the recommended path.
- Package tests for the plugin manifests, version pinning to the package version, hook wiring, and hook output (`tests/test_claude_code_plugin_package.py`).

### Changed

- Raised package version to `0.3.12`.

## v0.3.11

### Fixed

- The Claude Code installer now also writes the Unlimited Skills router block into the global `<claude_home>/CLAUDE.md` memory file, not only the project `CLAUDE.md`. The project file is only loaded when Claude Code runs inside that project, so installs that never started a session from the project directory ended up with no router instructions in context at all.

### Added

- `ClaudeCodeInstallOptions.patch_global_claude` (default on) and the `--no-global-claude-patch` installer flag to opt out of global memory patching.
- Install report now shows project and global CLAUDE.md patch status separately.

### Changed

- Raised package version to `0.3.11`.

## v0.3.10

### Added

- Claude Code plugin skill discovery in native sync: `search`, `list`, `view`, `reindex`, and `sync-native --agent claude-code` now mirror skills bundled with installed Claude Code plugins. Discovery reads `~/.claude/plugins/installed_plugins.json`, resolves each plugin's cache `installPath`, and falls back to the marketplace clone (`known_marketplaces.json` + `.claude-plugin/marketplace.json`) when the cache snapshot is pruned or the plugin is disabled.
- Plugin skill roots are resolved from the plugin's `.claude-plugin/plugin.json` `skills` declarations plus the conventional `skills/` and `.claude/skills/` folders; mirrored collections are named `local/claude-code-plugin-<marketplace>-<plugin>`.
- New opt-out environment variable `UNLIMITED_SKILLS_DISABLE_PLUGIN_SYNC=1` (plugin discovery only; `UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC=1` still disables all native sync).
- Tests covering cache-path discovery, marketplace-clone fallback, the opt-out variable, and missing plugin state (`tests/test_claude_plugin_sync.py`).

### Security

- Plugin-declared skill paths are validated against the plugin root: declarations that resolve outside the plugin directory (path escape) are ignored.
- Plugin sync reuses the non-destructive overlay: existing library files are never deleted, and name collisions are diverted to `duplicates/` instead of overwriting.

### Changed

- Raised package version to `0.3.10`.

## v0.4-readiness-rfc (planning)

### Added

- v0.4 readiness audit covering public core, private registry, signed manifests, catalog browser, feedback, evals, improvement workflow, private packs, org/team governance, plan/entitlement/sandbox billing, support diagnostics, security/privacy boundaries, and PR hygiene/release train health.
- SkillOps architecture RFC defining the v0.4 VFP, non-goals, data/trust boundaries, permission model, migration plan, Mermaid architecture diagram, and candidate modules for policy-aware skill recommendation, eval-driven catalog release gates, maintainer improvement queues, agent/runtime usage summaries, governance dashboard, optional self-hosted registry mode, and future human-reviewed automatic improvement proposals.
- v0.4 risk register, first four implementation epics, docs verifier, and focused docs tests.
- v0.4 public blocker closure ledger and verifier for PR #69, B-02 closure, recommendation non-mutation, signed hosted metadata, registration-free MIT local core, and support-bundle redaction boundaries.
- v0.4 cross-repo readiness suite, verifier, and fixture report proving the public client plus private registry contracts satisfy signed SkillOps metadata, eval gate, maintainer queue, recommendation refusal, skill improvement, support redaction, and no-mutation boundaries before the final go/no-go decision.
- v0.4 go/no-go decision package with a GO recommendation to start the first four implementation epics after review and merge, plus verifier coverage for closed B-01..B-04 blockers, clean PR debt, cross-repo readiness evidence, and non-negotiable safety boundaries.
- v0.4 E01 policy-aware recommendation runtime preview module, CLI command, schema, example, and tests. The preview combines signed catalog metadata with quality, improvement, entitlement, and policy signals while keeping all write flags false.
- v0.4 E03 maintainer queue status client commands, schemas, examples, docs, and tests for signed queue status, queue summary, fixed-pending-eval evidence refs, and explicit `--include-queue` recommendation context.
- v0.4.0-alpha E01-E04 integration gate, release manifest draft, release docs, smoke runner, verifier, and cross-repo E2E test tying together policy-aware recommendation preview, eval release operator workflow, maintainer queue runtime/status, and governance dashboard signed summaries.
- Public docs for v0.4 eval release gates and governance dashboard boundaries without committing private registry implementation or private catalog content.

### Security

- Repeated that v0.4 planning does not authorize automatic skill rewriting, auto-publish, automatic telemetry, live billing, PyPI publication, full catalog distribution, or automatic hosted query forwarding.
- Repeated that v0.4 must preserve no-prompt/no-skill-body/no-private-data boundaries, signed hosted manifest requirements, and registration-free MIT local core behavior.
- Added v0.4 cross-repo readiness checks that require no production hosted calls, no production signing key, no live billing, no PyPI, no full catalog distribution, no automatic install/update/remove, no automatic skill rewriting, and no auto-publish.
- The v0.4 go/no-go package approves implementation planning only; production rollout remains blocked behind per-epic review, security/privacy gates, and release-owner approval.
- The v0.4 E01 runtime preview remains decision-only: no automatic install, update, remove, rewrite, reindex, telemetry, full catalog distribution, prompt upload, skill-body upload, token/proof exposure, or private-key exposure.
- The v0.4 E03 maintainer queue client is read-only and metadata-only: no automatic install, update, remove, rewrite, reindex, publish, prompt upload, task text exposure, skill-body exposure, maintainer private-note exposure, token/proof exposure, or private-key exposure.
- The v0.4.0-alpha E01-E04 integration gate does not create a tag, authorize production rollout, enable live billing, publish to PyPI, distribute the full catalog, upload prompts or skill bodies, forward hosted queries automatically, rewrite skills automatically, or auto-publish artifacts.

## v0.3.9-alpha (publication candidate)

### Added

- Registered signed skill improvement status commands: `catalog improvement-status`, `catalog known-issues`, `catalog update-recommendations`, `catalog update-preview`, and `catalog deprecation-status`.
- Preview-only update recommendation contracts, schemas, examples, docs, trust scopes, and fake-service tests for known issues, fix status, recommended channel/version, deprecation/retirement status, compatibility notes, and stale installed-version status.
- Support-bundle skill improvement summary counts, excluding item ids, issue details, recommendations, skill bodies, prompts, local paths, repo paths, customer data, tokens, proofs, and private keys.
- Cross-repo skill improvement E2E, v0.3.9-alpha smoke runner, release verifier, checklist, and manifest for feedback/evals -> improvement backlog -> maintainer triage -> catalog quality report -> public signed recommendations.
- v0.3.9-alpha final publication smoke, publication verifier, upgrade notes, and known issues for the skill improvement workflow milestone.

### Changed

- Raised package version to `0.3.9`.
- Documented the maintainer-controlled workflow boundary: no automatic skill rewriting, no auto-publish, no prompt upload, no user telemetry, no production hosted calls, and no private skill bodies in the public repo.
- Marked the final tag as pending release-owner approval; this branch does not create or push `v0.3.9-alpha`.

## v0.3.8-alpha (in development)

### Added

- Registered catalog quality and evaluation status commands: `catalog quality`, `catalog eval-status`, `catalog explain-risk`, plus browser/search `--show-quality`, signed metadata verification, install-risk warnings, blocked hosted install refusal, schemas, examples, docs, and support-bundle summary counts.
- Skill evaluation cross-repo E2E, v0.3.8-alpha smoke/verifier, and release integration docs for signed catalog quality scoring.
- v0.3.8-alpha release smoke, verifier, checklist, known limitations, and release manifest for skill evaluations and catalog quality scoring.

### Changed

- Raised package version to `0.3.8`.
- Documented the catalog quality and skill evaluation boundary: signed metadata-only diagnostics, no prompt upload, no customer-data inspection, no untrusted skill execution, no automatic rewriting, and no auto-publish.

## v0.3.7-alpha

### Added

- Explicit registered catalog feedback commands: `catalog feedback` and `catalog feedback-status`, with dry-run, confirmation, schemas, examples, docs, and support-bundle redaction.
- v0.3.7-alpha final publication gate, release smoke, publication verifier, upgrade notes, known issues, and draft release notes for the explicit catalog feedback milestone.

### Changed

- Raised package version to `0.3.7`.
- Documented the catalog feedback privacy boundary: explicit-only submission, no automatic telemetry, no production hosted calls in public tests, and redacted support bundle status.

## v0.3.6-alpha

### Added

- Catalog browser release integration for registered signed metadata discovery.
- Cross-repo catalog browser E2E runner with public fixture mode and local private-registry mode.
- v0.3.6-alpha catalog browser release smoke, verifier, checklist, release notes, and manifest.
- v0.3.6-alpha final publication upgrade notes, known issues, release smoke alias, and publication verifier.

### Changed

- Raised package version to `0.3.6`.
- Extended trusted manifest key scopes to include catalog browser response, item, preview, and filters manifests.
- Documented catalog browser registration, metadata-only preview, approved/published visibility, dry-run install, and support-bundle redaction boundaries.

## v0.3.5-alpha

### Added

- Community catalog integration gate for registry submission review, signed canary publication, public review-status client UX, and fixture-only cross-repo E2E.

### Changed

- Raised package version to `0.3.5`.

## v0.3.4-alpha

### Added

- Plan and entitlement status UX: `plan status`, `plan refresh`, `plan explain`, and `plan doctor`, with shared denial vocabulary, redacted support bundle plan summaries, schemas, examples, docs, and tests.
- Billing lifecycle diagnostics: `billing status`, `billing refresh`, and `billing doctor`, with sandbox-only status refresh, redacted support bundle billing summaries, schema, examples, docs, and tests.
- Billing lifecycle cross-repo E2E runner for sandbox `subscription_active`, `payment_failed`, and `subscription_canceled` reconciliation against the private registry checkout without production hosted calls.
- Community catalog client v2: channel-filtered list, signed approved-only preview/install, local unregistered submit dry-run, and submission `withdraw` / `review-notes` commands.
- Registered catalog browser client commands: `catalog browse`, `catalog search`, `catalog filters`, `catalog preview`, and signed metadata-verified `catalog install --dry-run`.
- Explicit registered catalog feedback commands: `catalog feedback` and `catalog feedback-status`, with dry-run, confirmation, schemas, examples, docs, and support-bundle redaction.
- v0.3.7-alpha final publication gate, release smoke, publication verifier, upgrade notes, known issues, and draft release notes for the explicit catalog feedback milestone.
- Catalog browser schemas, sanitized examples, docs, support-bundle redaction, and tests for registration gating, signed response verification, approved-only visibility, metadata-only preview, and unapproved install refusal.

### Changed

- Raised package version to `0.3.4`.
- Extended plan/private-pack denial vocabulary with billing lifecycle reasons: `past_due`, `suspended`, and `expired`.
- Documented that billing lifecycle diagnostics are `sandbox_only`, with no checkout sessions, live payment providers, card data, bank data, or payment collection in the public client.

## v0.3.3-alpha

### Added

- Cross-repo org/team governance integration gate for v0.3.3-alpha.
- Release verifier, release smoke, checklist, upgrade notes, and manifest for org/team governance plus private-pack diagnostics.
- Final publication verifier, release smoke wrapper, known-issues note, dependency status, and registry signing status for v0.3.3-alpha.
- Private pack entitlement diagnostics: `private-packs access-check <pack_id>` and `private-packs doctor` with stable redacted denial codes for no entitlement, team membership, agent/channel mismatch, revocation, policy denial, and service unavailability.
- Organization governance status: `org status` for local cached status and `org status --refresh` for registered hosted refresh.

### Changed

- Raised package version to `0.3.3`.
- Documented org/team status boundaries and private-pack access diagnostics in public core, service diagnostics, private-team-pack, and support bundle docs.

## v0.3.2-alpha

### Added

- Private team pack setup, service diagnostics, doctor, and support bundle summaries with strict redaction of private pack names, private skill names, skill bodies, archive URLs, tokens, proofs, private keys, and local paths.
- Registered private team pack client commands: `private-packs list`, `preview`, `install`, `sync`, `installed`, and `remove`.
- Private pack install safety: signed `private-team-pack` manifest verification, proofed POST downloads, SHA256 checks, safe zip extraction, `registry/private/<pack_id>` layout, and owned-path removal guard.
- Private pack alpha release integration gate, release manifest, smoke runner, and verifier for v0.3.2.
- Managed Enterprise Skill Lock policy sync: `policy sync`, `policy sync --dry-run`, and `policy managed-status`.
- Signed `enterprise-policy` manifest scope for registered policy assignments from `/v1/policy/sync`.
- Managed policy removal guard: registry sync can remove only policies previously installed by managed sync with matching `policy_id` and `policy_sha256`; unmanaged local policies are refused and preserved.
- Managed Enterprise Skill Lock policy sync E2E runner covering signed install/update/remove, unmanaged removal refusal, policy enforcement refusals, tampered/unknown-key rejection, device proof rejection, and redaction.

### Changed

- Raised package version to `0.3.2`.
- Documented that private team pack hosted access requires registry-side entitlement or a Business/Enterprise plan.

## v0.3.1-alpha (in development)

### Added

- Post-release stabilization docs for the published `v0.3.0-alpha` baseline, including release health, known issues, upgrade notes, and a v0.3.1 stabilization verifier.
- v0.3.1 post-release smoke runner covering published-release traceability, fresh install, synthetic upgrade, packaging smoke, and managed policy release smoke.
- Guided first-run setup wizard with local-only, registered, Local Skill Hub, Enterprise, dry-run, and JSON reporting modes.
- Public setup report schema, sanitized setup examples, and first-run onboarding documentation.
- Redacted support diagnostic bundle with zip output, dry-run, JSON manifest, optional path inclusion, public schema, sanitized example, and privacy documentation.
- v0.3.1-alpha publication manifest and verifier covering public PR #34-#38, private registry PR #9/#10/#11/#12/#18, the canonical 315-skill reconciliation counts, production registry signing status, and release-owner tag approval.
- Shared service diagnostics v2 snapshot across setup reports and support bundles, preserving local-only defaults and redacted support output.
- Final v0.3.1-alpha release smoke that proves the publication verifier blocks by default without production-signed registry artifacts and passes only with explicit release-owner blocked-signing override.

### Changed

- Raised package version to `0.3.1` for the v0.3.1-alpha stabilization train.
- README, SECURITY, known limitations, install, upgrade, and release process docs now describe `v0.3.1-alpha` as the current stabilization train while preserving `v0.3.0-alpha` as the published baseline.

## v0.3.0-alpha

## v0.2.2-alpha

### Added

- Production service onboarding diagnostics: `service configure`, `service status`, `service doctor`, `service verify-trust`, `service test-registration --dry-run`, and `service test-proof`.
- Public service status schema, sanitized status example, production registry onboarding docs, and service diagnostics privacy docs.
- Enterprise Skill Lock policy MVP: `policy status`, `policy verify`, `policy install`, `policy remove --yes`, and `policy explain`.
- Enterprise policy schema/example plus local enforcement for approved registries, channels, manifest keys, community install/submit, unsigned hub allowlists, local fallback, and policy-approved local roots.
- Production-shaped registry contract E2E fixture covering registered device proof, signed catalog/update/enhancement/hub/team/release-channel manifests, hub heartbeat, entitlement refresh, safe retries, signed offline metadata cache, and proof replay rejection without calling production hosts.
- Release channel UX for registered clients: `release status`, `release pin`, `updates --channel`, signed `release-channels` verification, and `updates rollback`.
- Machine-readable `v0.2.2-alpha` release manifest, release verifier, fresh install smoke, and synthetic v0.2.0 upgrade smoke.

### Changed

- Raised package version to `0.2.2`.
- Hosted registry JSON clients now use a shared request path with bounded retries for safe/idempotent reads, redacted errors, and signed offline cache fallback for catalog/update metadata when the service is unreachable.
- Hosted update apply now preserves the replaced collection under `registry/.rollbacks/<collection>/` for explicit local rollback instead of discarding the previous version after a successful update.
- Official bundled trusted manifest key scope now includes `release-channels` so the registered client can verify signed release-channel status manifests from the production registry.
- Release documentation now traces the v0.2.2 stack through public PR #20 through PR #27 and private registry PR #3 through PR #6 before tag approval.

## v0.2.1-alpha

### Added

- Integrated Local Skill Hub token enforcement, remote hub client runtime, allowlist bootstrap, and v0.2.x release smoke coverage into one release-candidate branch.
- Local Skill Hub client token checks for protected `/v1/...` APIs; `/health` remains open for liveness.
- Remote Local Skill Hub client commands for `remote configure`, `remote status`, `remote search`, `remote resolve`, and `remote view` with explicit fallback policy.
- Allowlist bootstrap and cached `hub serve` wiring for local fixtures and registered hosted allowlist metadata.
- Release smoke suite scenarios that exercise hub tokens, remote client behavior, allowlist bootstrap, redaction, and production-hosted-call blocking without mutating real HOME.
- Remote-first router template rendering and installer flags for Codex, Claude Code, Hermes, and OpenClaw.
- Skill runtime manifest schema, client capability reporting, capability-aware hub resolve, and dry-run remote install plans.
- Required Ed25519 signed hosted manifest verification for hub allowlist sync, collection updates, enhancement manifests, and team sync manifests.
- Machine-readable `v0.2.1-alpha` release manifest, release verifier, fresh install smoke, and synthetic v0.2.0 upgrade smoke.

### Changed

- Raised package version to `0.2.1`.
- Updated alpha security and release documentation to describe the integrated Local Skill Hub runtime stack.
- Clarified that Local Skill Hub remains allowlist-only, full catalog distribution remains disabled, and hosted registry services do not receive local hub search queries by default.
- Clarified that hosted remote manifests require valid signatures, while archive installation still depends on SHA256 verification and safe extraction.
- Installer reports and generated router files redact raw hub tokens; token-env configuration is preferred.
- Tool/platform skill install plans remain metadata-only; the hub does not execute skills or install packages.
- Release documentation now traces private registry PR #2 and public PR #13 through PR #19 before the finalization PR and tag approval.

## v0.2.0-alpha

### Added

- Two-container library layout: `registry/` for hosted/community/team/bundled packs and `local/` for native agent mirrors and local skill-library content.
- Deduplicated indexing by skill name so search/list/vector counts represent semantic skills instead of every physical copy.
- Regression coverage that native sync overlays files without deleting existing local library content.
- Fast vector sidecar index for query-time vector search, with ChromaDB kept as compatibility storage.
- Local-only `unlimited-skills doctor` command with JSON output and agent-specific checks for Codex, Claude Code, Hermes, and OpenClaw.
- Product editions, public core boundary, support matrix, release process, and known limitations docs for public alpha review.
- Hosted registry API contract docs, catalog model docs, JSON schemas, sanitized examples, and registry contract tests.
- Registered `community` CLI namespace for community catalog list/search/preview/install, explicit submit preview/confirmation, submission status, local installed listing, and local remove.
- Community catalog schemas, sanitized examples, submission review docs, and privacy docs for explicit community submissions.
- Team Free member listing, pending/reject/revoke flows, collection listing, leave command, sync dry-run JSON output, local redacted team audit events, and Team Free schemas/examples.
- Local Skill Hub contract docs, public schemas, sanitized examples, and hub/remote CLI skeleton commands.
- Local Skill Hub token create/list/revoke commands with hash-only local token storage.
- Local Skill Hub token enforcement for protected `/v1/...` APIs, with `/health` left open for liveness checks.
- Local Skill Hub LAN bind safety: non-localhost hosts require `--allow-lan` and at least one active hub token.
- Redaction for Authorization bearer tokens, `X-ULS-Hub-Token`, hosted registration tokens, team/member tokens, and device private keys.
- Registration-gated `unlimited-skills hub serve` boundary while existing `unlimited-skills serve` remains unregistered.
- Registered Local Skill Hub free-tier limit of up to 100 active client instances.
- Allowlist-only Local Skill Hub distribution model based on private registry audit verdict `YES_WITH_ALLOWLIST`.
- Local Skill Hub MVP runtime endpoints for health, hub status, client registration, allowlist-only skill search/resolve, and skill view.
- Remote Local Skill Hub client runtime: `remote configure`, `remote status`, `remote search`, `remote resolve`, and `remote view`.
- Remote fallback modes: `local_allowed` uses local search/view/resolve when the hub is unavailable, while `hub_required` fails clearly.
- Remote client capability collection for resolve requests, including agent type, OS, architecture, Python/Node versions, available tool names, and environment variable names only.
- Local Skill Hub allowlist bootstrap: `hub init --allowlist <file>`, registered `hub sync`, cached `hub/allowlist.v1.json`, and allowlist sync request/response schemas.
- Allowlist validation for `YES_WITH_ALLOWLIST`: full catalog distribution disabled, registration required, free active client limit 100, no hub-side skill execution, no blocked/local-only/needs-review distributable skills, and no embedded skill bodies.
- v0.2.x release smoke suite with an isolated temp HOME runner, Community Core checks, registration-boundary checks, registry/local layout checks, vector sidecar smoke, Local Skill Hub allowlist smoke, redaction smoke, docs/security claim checks, and git-ref validation checks.

### Changed

- Raised package version to `0.2.0`.
- Codex installs now default to the Codex-scoped library root under `~/.codex/.unlimited-skills/library` and patch `~/.codex/AGENTS.md` by default.
- Native sync is non-destructive: it overlays changed skill files and never clears existing `local/` content.
- Hermes native skills now install/migrate under `local/hermes/skills` instead of being treated as registry collections.
- Community, team, update, and bundled collection installs now target `registry/<collection>/`.
- `SECURITY.md` now uses the `v0.2.0-alpha` support boundary and documents Local Skill Hub MVP security limitations.
- FastAPI app metadata now uses the package `__version__` instead of hardcoded app versions.
- README, known limitations, and release notes now state that Local Skill Hub LAN mode requires explicit opt-in and active hub client tokens.
- Vector search now uses the sidecar fast path before Chroma, and embedding models are cached inside long-lived processes so warm daemon mode actually avoids repeated model startup.
- Hardened public alpha documentation for the v0.1.2-alpha release boundary.
- Clarified that hosted catalog/update access is registration-gated early access and already populated without publishing private registered skill bodies in the MIT repo.
- Clarified that hosted collection archives are SHA256-verified today; cryptographic signature verification is planned, not currently enforced.
- Documented the official registered hosted catalog as populated early-access while keeping private skill bodies out of the public MIT repo.
- Clarified that community list/search/preview/update checks do not upload skill bodies, while `community submit` uploads only the selected skill or pack after confirmation.
- Clarified Team Free limits, 24-hour auto-approval cap, no local skill-body upload during team sync, and Free-vs-Business-vs-Enterprise boundaries.
- Replaced remote client skeleton wording with working Local Skill Hub HTTP client behavior and explicit alpha limitations.
- `hub serve` now defaults to the cached validated allowlist and fails clearly when no allowlist is configured instead of requiring manual path wiring forever.

## v0.1.2-alpha

### Added

- Full Claude Code installer for personal skills, project skills, router launchers, `CLAUDE.md` patching, bundled/adapt-installed modes, and optional vector reindexing.
- Claude Code router skill with shell and PowerShell launcher placeholders.
- Claude Code router launchers now remember the installed project root so later project `.claude/skills` additions are mirrored on the next router CLI call.

### Changed

- Raised package version to `0.1.2`.
- README now documents Claude Code as a full installer target instead of migration-only.

## v0.1.0-alpha

Developer preview for a local-first skill router and context reducer.

### Added

- Local recursive `SKILL.md` discovery, lexical index, Chroma vector index, hybrid search, `view`, `where`, `list`, and `use`.
- Codex router skill and installer with managed `AGENTS.md` patch.
- OpenClaw installer for workspace, plugin, and built-in skill roots.
- Hermes installer with native skill mirroring, context-reduction mode, and rollback manifest.
- Migration scripts for Codex, Claude Code, OpenClaw, Hermes, and Vellum AI.
- Native skill sync for Codex, Claude Code, Hermes, and OpenClaw roots before common retrieval commands.
- Registered hosted update client with SHA256 archive verification and safe zip extraction.
- Registered local enhancement-script download with checksum verification.
- Team sync MVP: create, join request, pending list, master approval, temporary auto-approval, and sync.
- Public repo self-update from GitHub releases or tags.

### Known Limitations

- Hosted registry access is early-access and requires registration.
- Enterprise Skill Lock was roadmap-only in v0.1.0-alpha.
- Hosted archive signature metadata exists, but the current client enforces SHA256 verification only. Cryptographic signature verification is planned.
- Install from a GitHub clone for now. PyPI packaging should wait until repo assets such as scripts, router skills, docs, and packs are included and tested in wheels.
- OpenClaw installer modifies the selected workspace and patches `AGENTS.md` unless `--no-agents-patch` is passed.
- Warm daemon mode is experimental and not yet the default retrieval path.

### Suggested Smoke Tests

- Windows PowerShell: `install-codex.ps1`, `install-hermes.ps1 -Mode evacuate-visible-skills` dry-run.
- Linux/macOS: `pip install -e ".[all]"`, `reindex`, `search`, `view`, `serve`.
- Hermes sandbox: fake `.hermes/skills`, apply context reduction, verify only router remains visible, then rollback.
- OpenClaw sandbox: fake workspace, run installer, verify `AGENTS.md` patch and search.
- Unregistered instance: verify local `search` works and hosted `updates check` fails with registration-required wording.
