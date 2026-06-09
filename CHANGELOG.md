# Changelog

## v0.3.3-alpha (in development)

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
