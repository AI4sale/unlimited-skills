# Changelog

## Unreleased

### Added

- E23 design (docs/schema only, no implementation, nothing hosted): MCP bundle distribution -- channels and assignments (`docs/mcp-bundle-distribution.md`, `schemas/mcp-bundle-channel.schema.json`, `schemas/mcp-bundle-assignment.schema.json`, validated annotated examples `examples/mcp/bundle-channel.example.json` / `examples/mcp/bundle-assignment.example.json`, `tests/test_mcp_distribution_schemas.py`): how signed profile bundles (E13/E14) reach registered/business TEAMS. A publisher issues bundles into named CHANNELS -- one JSON file per channel with an owner issuer key_id, a monotonic `revision` (consumers refuse regression -- offline anti-replay), an append-only ordered publish history (`bundle_sha256` + `published_at` + status `active`/`superseded`/`revoked`, exactly one active record), and a `current` pointer that must equal the active record's sha; members hold ASSIGNMENTS -- audience identifiers (the exact E13 `team:`/`org:`/`host:` grammar), the FULL channel identity pair (name + owner key id), `follow` vs `pin` mode (`pin` requires `bundle_sha256`, `follow` forbids it -- exactly one artifact owns the pointer), a mandatory validity window, and a monotonic revision. Flow: E19 publisher ceremony -> channel publish record -> assignment -> member's E20 `library add`/`activate` with the unchanged E14 verification against the E15 trust store -- routing files grant NO capability and every routed bundle still verifies fail-closed (`-32014`..`-32019`), including the bundle's own audience binding. Offline-first: channels/assignments are plain FILES distributable over any transport (git repo, shared drive); the future registry sync at unlimited.ai4.sale is designed as a DUMB CARRIER for these same files. Both signature envelopes reuse the exact E13 shape and canonical-JSON signing input and are OPTIONAL in the format (MIT core may use unsigned routing files; bundle verification stays the security floor) but REQUIRED for registered/business-tier distribution, which the sync machinery is forbidden to deliver unsigned. Decision table covers publish authority (channel owner's key only, no delegation in v1), pin-beats-follow precedence, revoked-channel-target fail-closed behavior (member keeps last-good via the E20 library), mild assignment-expiry semantics (stops NEW activations, never deactivates a verified bundle), deterministic multi-assignment conflict resolution (host > team > org, pin > follow, highest revision, residual ties refused loudly), no offline grace timer (the bundle's signed expiry IS the grace bound), and no new refusal codes reserved (deferred to the implementing change). Privacy boundary: distribution files carry names, sha256 content addresses, key ids, audience identifiers, timestamps, statuses, and signatures ONLY -- never tool args, audit data, profile rules, key material, paths, or member PII beyond audience identifiers; the future registry may see these files as opaque blobs plus entitlement identity, and may never see audit logs, library state, or member activity. Entitlement gate: local file-based distribution stays MIT-free indefinitely; the entitlement check gates the hosted CARRIER at registry-sync time (future design) and verification never gains an entitlement check. Trust: channel ownership survives key rotation via the E13 overlap window (successor revisions signed by the new key after an explicit member-side `trust import`); owner key revocation freezes the channel fail-closed until a successor key from the member's trusted set re-signs it -- no automatic ownership transfer. Threat-model vectors 19-22 (routing manipulation, stale/replayed routing files, channel-owner key compromise, assignment audience confusion). Tests validate both examples against both schemas with the repo's self-contained validator pattern, pin the E13 envelope/grammar reuse against `schemas/mcp-profile-bundle.schema.json`, encode the semantic load rules as executable documentation, and cover negatives (unknown keys, bad sha formats, empty channel history, unknown status/mode, bad audience and channel names, zero revisions, loose timestamps, pin/follow pointer violations, two-or-zero active records, unordered history, signature key-id mismatches). Explicit non-goals: no hosted sync, no registry API, no client sync implementation, no billing, no production signing keys, no telemetry, no OAuth, no remote upstreams, no MCP resources/prompts, no verifier/CLI/runtime changes; the deferred registry-side decisions (identity/authn, entitlement mechanics, server-side publish ACLs, anti-rollback service guarantees, online CRL delivery, retention, re-validation, discovery, production issuing ceremony) are listed to feed the next private-registry work.

- E22: MCP profile stack stabilization audit (`scripts/run-mcp-profile-stack-stabilization-audit.py [--fixture-mode] [--json] [--out DIR]`, `schemas/mcp-stabilization-audit-report.schema.json`, `examples/mcp/stabilization-audit-report.example.json`, `tests/test_mcp_stabilization_audit.py`, `docs/mcp-stabilization-audit.md`): NOT a new runtime module -- a read-only CONSISTENCY MAP of the whole MCP profile stack (E06-E21 plus the E12B warm cache) audited over the repository itself across six dimensions: (1) the reserved refusal-code registry -32001..-32019 (code constants in gateway.py/profiles.py/bundles.py vs the E11 inspector's code->name->meaning table vs the E16/E19 name tables vs every docs-table naming claim: no duplicates, no gaps in the claimed range, identical names everywhere, docs<->code reference closure); (2) CLI taxonomy (the real `build_parser` argparse tree under `mcp`: every subcommand has a docs mention and a CHANGELOG mention, `--json` everywhere it makes sense -- `serve`/`gateway` exempt as stdio servers -- and flag-vocabulary uniformity `--out`/`--store-dir`/`--library-dir`, REPORTED as warnings, never auto-fixed); (3) schema inventory (every `schemas/mcp-*.schema.json`: valid JSON, draft 2020-12 declared with the two pre-E07 draft-07 files flagged as stragglers, a validating example under `examples/mcp/` via the repo's self-contained validator, referenced from at least one test and one doc); (4) docs map (every relative link in the stack docs resolves; every `unlimited_skills/mcp/` module is mentioned by some doc; the `verify-mcp-boundaries.py` phrase checks are invoked programmatically so the two can never drift); (5) audit field names (the writer/call-site field set -- base row, `profile_loaded` provenance, E12B cache events -- vs what the E11 inspector and E17 replay read and what the docs name; documented `*_sha256` fields must be exempt in the inspector's redaction self-check; gateway event rows must never be miscounted as meta-tool calls); (6) security boundary consistency (fail-closed language in every bundle-layer doc, no-go/locality phrases in every stack doc, and an AST import scan proving no `unlimited_skills/mcp/` module imports a network library). Findings carry severities info/warning/problem; exit 0 when no problems (warnings allowed), 1 otherwise; `--json` validates against the new draft 2020-12 schema; report strings are repo-relative names only (test-enforced leak-grep with the audit writer's own heuristics) and the audit is offline by construction -- no network, no telemetry, no subprocess, never a write outside an explicit `--out`. Stabilization fixes shipped with the audit (each one a problem the first run surfaced): the E11 inspector now names the E13/E14 bundle refusal family `-32015`..`-32019` (REFUSAL_CODES + error-text markers for the `(bundle_*)` refusal phrases) instead of reporting `unknown`; the inspector now knows the E12B `cache_loaded`/`cache_refresh` event rows (excluded from call summaries, refusal breakdowns, upstream health, and profile sections instead of being miscounted as meta-tool calls); the inspector's redaction self-check now exempts the documented `bundle_sha256`/`local_profile_sha256`/`cache_sha256` hash fields alongside `profile_sha256` so a signed-bundle or warm-cache gateway run no longer self-flags its own documented provenance hashes; `docs/mcp-trust-store.md` and `docs/mcp-bundle-publishing.md` carry explicit fail-closed language; `docs/mcp-gateway.md` documents the lifecycle event rows' exact field names; `docs/mcp-audit-inspector.md` documents the full named code range and the event-row exclusion. Policy: the runner is a release-gate candidate (`docs/mcp-stabilization-audit.md`). Tests cover the clean current-tree run (zero problems, exit 0), schema + shipped-example validation and sync, injected-inconsistency detection in temp copies (duplicated reserved code, renamed docs-table code name, corrupted and schema-violating examples, removed boundary phrase, injected network import), regression pins for every inspector fix, leak-grep over the report and both CLI output modes, and `--out` containment.

- E21: MCP profile stack end-to-end operator acceptance suite (`scripts/run-mcp-operator-acceptance.py`, `schemas/mcp-operator-acceptance-report.schema.json`, `examples/mcp/operator-acceptance-report.example.json`, `tests/test_mcp_operator_acceptance.py`, `docs/mcp-operator-acceptance.md`): a fixture-only acceptance suite proving the whole MCP profile stack works as ONE operational workflow, executed by the REAL modules end-to-end (no mocks, no reimplementations) inside a private temp directory with shared state: 1 `keygen` (E19 DEV Ed25519 keypair) -> 2 `trust_import` (the PUBLIC half into the E15 managed store + empty CRL) -> 3 `publish` (the E19 ceremony publishes `team-v1` and `team-v2`, v2 recording v1 as its `--previous` rollback predecessor; post-package self-check through the real E14 path) -> 4 `verify` (standalone E19 verify) -> 5 `library_add` (E20 verify-before-store, content-addressed) -> 6 `rollout_plan` (E16 dry-run over a what-if tools fixture: 2 of 3 tools visible+callable, the legacy tool hidden, no blockers) -> 7 `replay_audit` (E17 over a synthetic historical audit log written through the REAL redacted writer: the historically-used legacy tool becomes newly denied, recommendation `safe_with_warnings` under the 20% block threshold) -> 8 `activate` (v1 then v2; re-verify at activation; atomic `active.bundle.json` pointer; append-only history) -> 9 `gateway_resolve` (the REAL `commands.mcp._resolve_gateway_profile_state` resolves the active pointer under `--require-signed-profiles` into an enforced `ActiveProfile` with bundle provenance) -> 10 `incident_drill` (E15 `trust revoke --bundle-sha256` withdraws the ACTIVE bundle; the library's activation re-verify refuses `-32017 bundle_revoked` and the stale pointer fails CLOSED at the next gateway start; the refusal is recorded through the real audit writer) -> 11 `rollback` (E20 history walk-back to the prior good `team-v1`; the gateway resolves it again under the same signed-required policy) -> 12 `audit_report` (the E11 inspector over the run's own audit log shows the `-32017` refusal with a passing redaction self-check). CLI: `[--json] [--out DIR] [--step NAME|all]` (`--step` runs the workflow prefix ending at NAME -- the suite is one flow, not twelve independent checks); exit 0 only when every selected step passes, 1 on the first failing step (the workflow stops), 2 for usage errors or a missing `cryptography` package (the E19 publisher has no fallback signature scheme). The machine report (per step: name, ok, key facts, duration) validates against the draft 2020-12 schema and carries key facts ONLY -- names, SHA-256 PREFIXES, counts, refusal codes, statuses, basenames; never key material, full hashes, argument values, or local paths (test-enforced leak-grep over the report AND stdout with the audit writer's own heuristics). Deterministic apart from `generated_at` and durations (profile env vars are neutralized for the run; the verification clock is pinned once). Tests cover the full 12-step run (exit 0, every step ok), schema + shipped-example validation and sync, single-step selection, failure injection (a bundle corrupted between publish and library add makes exactly step 5 fail with `bundle_signature_invalid` and exit 1), leak-grep, containment (an explicit base dir means no temp dir of its own and no writes to the repo's managed trust store or default audit log), and docs sync. Hard safety by construction: fixture mode only -- no production keys, no hosted calls, no registry sync, no OAuth, no MCP resources or prompts, no network, no telemetry. `docs/mcp-operator-acceptance.md` doubles as the operator onboarding story; `docs/mcp-bundle-library.md` and `docs/mcp-incident-runbook.md` cross-reference it. Composition only: every layer's semantics (E11/E14/E15/E16/E17/E19/E20 and the gateway resolution) are reused unchanged -- nothing is reimplemented, widened, or bypassed.

- E20: MCP profile bundle local library and activation manager (`unlimited_skills/mcp/bundle_library.py`, `tests/test_mcp_bundle_library.py`, `docs/mcp-bundle-library.md`): `unlimited-skills mcp profiles library status|list|add|inspect|activate|deactivate|rollback|pin|unpin|remove|doctor [--library-dir DIR] [--trusted-keys FILE] [--audience-id ID] [--json]` is a LOCAL library of signed profile bundles closing the operational gap "I have 5 bundle files -- which are installed, which is active, how do I roll back?". Bundle files are stored IMMUTABLE and content-addressed (`<sha256-prefix>-<name>.bundle.json`) under `<library root>/.unlimited-skills-bundles/`, with an atomically written `library-state.json` tracking the entries (sha256, name, issuer key_id, audience, validity window, added_at, source BASENAME, pinned flag, verification status at add time), the single ACTIVE bundle sha (at most one), and an append-only activation history that powers `rollback`. Verification is the REAL E14 path (`resolve_bundle_state` via the E19 verify wrapper -- never a reimplementation, never a bypass), run THREE times: `add FILE` verifies BEFORE anything is stored and refuses invalid/tampered/expired/revoked/key-missing bundles outright with the exact reserved code (`-32014`..`-32019`; no quarantine mode, no `--allow-unverified`; duplicate sha256 = idempotent no-op); `activate`/`rollback` RE-verify at activation time (keys/CRL may have changed since add); `doctor` re-verifies every entry against the CURRENT trust store/CRL. The trusted-keys default is the gateway's E15 rule (explicit `--trusted-keys` > the managed store's file under `<root>/.unlimited-skills-trust` when it exists > `-32019` refusal); explicit `--audience-id` is checked strictly, and when omitted the bundle's own first audience is used (signature/expiry/revocation/key still fully proven; audience BINDING stays enforced by the gateway). Activation pointer: `activate` atomically copies the verified bytes to `<library>/active.bundle.json` (plain file copy, no symlinks, Windows-safe); the gateway is started with `--profile-bundle` pointing there and reads it ONCE at startup -- NO hot reload (consistent with E10/E14), and the gateway re-runs full E14 verification itself so a stale or since-revoked pointer copy still fails closed. `deactivate` clears the active record and removes the pointer (idempotent, loud open-mode note). `rollback` walks the activation history backwards, LOUDLY skipping candidates that no longer verify (each skip reported with its exact code, e.g. `-32017` for a since-revoked bundle) until one verifies; none verifying = refusal, nothing changes. Pin semantics: `pin`/`unpin` are idempotent subcommands; a PINNED entry always refuses `remove` (`--force` does NOT override a pin); the ACTIVE entry refuses `remove` without `--force`, and with it is deactivated first (recorded in history) then removed. `status` shows the active bundle (sha, name, issuer, expiry, days left, current re-verification), pinned count, totals, library dir, and the trust store in use; `list` shows per-entry CURRENT re-verification state (ok/expired/revoked/key-missing/...) plus active/pinned flags; `inspect` adds manifest-level detail (audience, validity window, namespace ceiling, per-profile rule counts). `doctor` (exit 0 ok / 1 problems) flags: corrupt state file (with rebuild guidance -- stored bundles are immutable, nothing signed is lost), missing/corrupt stored files (sha mismatch), an ACTIVE bundle that no longer verifies (the gateway would fail closed at its next start), stale/orphaned active pointer, active sha without an entry or an activation history record; non-active entries that no longer verify, orphan bundle files, and history records for uninstalled bundles are warnings. Privacy/safety: no key material beyond the bundles' own public content is ever stored or printed; outputs carry source basenames, never the operator's absolute source paths (test-enforced leak-grep); atomic state/pointer writes (a failed state write removes the just-copied bundle file -- no orphans); offline by construction -- no network, no registry sync, no hosted calls, no production signing keys. Tests cover the full lifecycle (E19 publish -> add -> list/status -> activate -> the REAL gateway profile path resolves the active pointer under `--require-signed-profiles` -> deactivate -> rollback including the skip-revoked walk-back), every add-refusal code, pin/remove semantics, every doctor problem class, state-corruption handling, atomicity, leak-grep, and CLI wiring/exit codes. E14/E15 verification and trust semantics are reused, never changed or bypassed.

- E19: MCP profile bundle publisher and signing ceremony, local-only (`unlimited_skills/mcp/bundle_publisher.py`, `tests/test_mcp_bundle_publisher.py`, `docs/mcp-bundle-publishing.md`): `unlimited-skills mcp bundle keygen|publish|verify` is a local, fixture-safe workflow turning a raw E09/E10 tool profile into a signed profile bundle package -- raw profile -> validate -> sign -> package -> verify -> handoff. `keygen --out DIR [--key-id ID --display NAME] [--force]` generates a DEV/FIXTURE Ed25519 keypair (the optional `cryptography` package is required; absent = clear refusal, no fallback scheme): the PRIVATE key is written ONLY to the operator-specified out dir with a loud `DEV KEY -- do not use in production` header and best-effort restrictive permissions, and the PUBLIC key is emitted in the exact `mcp trust import --key-file` format -- key material is never printed (paths and abbreviated fingerprints only), and the E15 store refuses to import the private file. `publish --profiles FILE --signing-key FILE [--issuer-key-id ID] --audience ID... [--expires-days N] [--namespaces NS...] [--out DIR] [--name N] [--previous FILE|SHA] [--crl-path P] [--dry-run] [--force]` validates the raw profile with the REAL E09/E10 loader, builds the bundle document (embedded profiles, issuer, mandatory non-empty audience, validity window, `allowed_upstream_namespaces` -- explicit or derived, every profile rule checked against the ceiling BEFORE signing -- and the optional revocation pointer slot), signs it over the REAL canonical JSON (`canonical_bundle_bytes`, reused -- never duplicated), packages `<out>/<name>.bundle.json` plus `<name>.MANIFEST.json` (bundle SHA-256, issuer key id/fingerprint, created_at, source profile SHA-256, profile/rule counts, publisher version), `<name>.VALIDATION-REPORT.json` (every check the ceremony ran), and `<name>.ROLLBACK.json` (previous bundle SHA-256 when `--previous` is given, plus the exact `unlimited-skills mcp trust revoke --bundle-sha256 ...` command), then runs the REAL E14 verification (`resolve_bundle_state`) over the packaged bytes as an automatic post-package self-check BEFORE the signed bundle gets its final name -- packaging is atomic (temp + `os.replace`) and any ceremony failure leaves no signed bundle (and no temp) behind; `--dry-run` performs every step including the self-check but writes nothing to the out dir. `verify --bundle FILE --trusted-keys FILE [--audience-id ID]` is a thin wrapper over the same real verification: exit 0 verified / 1 with the exact refusal code and name. Refusals (loud, exit 1, nothing signed written): invalid profile (E09/E10 errors surfaced), missing/unreadable signing key, PUBLIC-only key files, issuer key-id mismatch, `--expires-days < 1` (past/inverted window), empty or malformed audience, namespace rule grammar violations and rules outside the ceiling, out-dir collisions without `--force`, missing `cryptography`. Private-key hygiene is test-enforced: the seed (base64 and hex) and PEM/OpenSSH private markers appear in NO ceremony output -- bundle, manifest, validation report, rollback metadata, public key file, trust store files, stdout/stderr -- and the keygen out dir is the only place the private key exists; a drill-style round trip proves the rollback metadata's revoke command actually revokes the bundle through the real E15 store (`-32017`). DEV/fixture keys only: production signing keys are never generated, handled, or requested (the E13/E15 issuing boundary stands); offline by construction -- no network, no registry sync, no hosted calls, no telemetry. E14/E15 verification and trust semantics are reused, never changed or bypassed.

- E18: MCP signed-bundle incident drill and recovery runbook (`scripts/run-mcp-bundle-incident-drill.py`, `tests/test_mcp_incident_drill.py`, `docs/mcp-incident-runbook.md`): `python scripts/run-mcp-bundle-incident-drill.py [--json] [--out DIR] [--scenario NAME|all]` is a fully self-contained fixture-mode drill for every documented signed-bundle incident class. For each of nine scenarios it builds a known-good fixture in a private temp directory (ephemeral keypair, signed bundle, E15 managed trust store written by the real `trust_store` functions), injects the incident, runs the REAL E14 verification (`resolve_bundle_state`, never a reimplementation), asserts the exact fail-closed refusal code, then executes the documented recovery and proves verification returns to a working state: `bad_signature` (`-32015`, recovery: re-issue), `unknown_key` (`-32019`, recovery: `trust import`), `expired_key` (`-32019` per the E14 expired-equals-missing mapping; recovery: rotation -- new key_id imported, bundle re-signed), `expired_bundle` (`-32016`, recovery: fresh signed window), `revoked_bundle` (`-32017` via `trust revoke`; recovery: corrected bundle with a new SHA-256 while the append-only CRL keeps refusing the withdrawn one), `crl_outage` (`-32017` fail-closed on an unreadable declared CRL; recovery: restore the CRL, `trust doctor` exit 1 -> 0), `wrong_audience` (`-32018`, recovery: corrected `--audience-id`), `operator_rollback` (fail-closed bundle -> sanctioned fallback to the raw `--profiles` path and, last resort, open mode, with the documented losses: signed provenance, audience binding, namespace ceiling, signed-required policy), and `trust_store_recovery` (corrupted `trusted-keys.json` -> `-32019`, `trust doctor` detects, rebuild through the real import path). Refusals are recorded through the real redacted `AuditLog` writer and the E11 inspector (`build_report`) is run over the drill's own log: exit 0 requires every scenario to BOTH refuse with the expected code AND recover, every expected code to appear in the audit report, and the redaction self-check to pass. Signing uses the optional `cryptography` package (ephemeral real Ed25519) when present, else a clearly-marked TEST-ONLY HMAC backend; the drill is offline by construction -- no network, no telemetry, no subprocess, and the real library root, managed trust store, and audit log are never touched. `--json` validates against the new `schemas/mcp-incident-drill-report.schema.json` (draft 2020-12; generated example `examples/mcp/incident-drill-report.example.json`); the report carries scenario names, codes, booleans, durations, and operator-step text only -- never key material, signature values, hashes, or local paths (a leak-grep test re-scans every report string with the audit writer's own `looks_secret`/path heuristics). `docs/mcp-incident-runbook.md` is the operator runbook the drill automates: per incident -- symptoms (exact refusal code + audit evidence), immediate containment, recovery commands (`mcp trust import|revoke|doctor`, bundle re-issue, rollback flags), verification of recovery, and prevention notes; `tests/test_mcp_incident_drill.py` keeps the runbook's scenario and code lists in sync with the harness. E14/E15 verification and trust semantics are exercised, never changed or bypassed.

- E17: MCP audit replay and policy impact simulator (`unlimited_skills/mcp/audit_replay.py`, `tests/test_mcp_audit_replay.py`, `docs/mcp-audit-replay.md`): `unlimited-skills mcp profiles replay-audit [--audit-log FILE] [--profiles FILE] [--bundle FILE] [--trusted-keys FILE | --trust-store DIR] [--audience-id ID] [--profile NAME] [--config GATEWAY_CONFIG] [--json]` replays the HISTORICAL redacted audit JSONL log (the E11 inspector's readers reused verbatim: rotated generations in order, malformed lines counted and skipped, refusal classification by the same code tables) against a PROPOSED policy resolved with the REAL E10/E14/E15 machinery in dry-run (the gateway's startup dispatch, mirrored from E16 -- never a reimplementation). Each row is classified (`tools_search`/`tools_schema`/`tools_call`/`skills`/`other`/`profile_loaded`/malformed; rows lacking a tool identity -- audit level `minimal` -- are counted, never guessed); each replayable `tools_schema`/`tools_call` row is evaluated in the gateway's per-request order (fail-closed state, visibility `-32011`, callability `-32012`, then the config trust gates `-32005`/`-32010`/`upstream_not_configured`) and compared against the historical POLICY outcome (policy family `-32011`..`-32019`; runtime refusals had passed policy) into `newly_denied`/`newly_allowed`/`unchanged_allowed`/`unchanged_denied`, with breakdowns by tool, upstream, profile, would-be refusal code, UTC hour time bucket, and call type. Detections with severities: `policy_hides_used_tool`, `tool_view_only_but_called`, `bundle_verification_failure` (exact would-be code and failing step), `revoked_issuer` (`-32017`), `namespace_mismatch` (`-32018`, step `namespace_ceiling`), `policy_fail_closed`, `input_error`/`gateway_config_invalid`, plus `missing_tool_identity`/`malformed_rows`/`nothing_to_replay` warnings. Recommendation `safe`/`safe_with_warnings`/`blocked` (blocked when the proposed policy fails closed, a startup-refused input is present, or >20% of replayed calls become newly denied -- `BLOCK_BREAKAGE_RATIO = 0.20`, documented); exit 0 safe/warnings, 1 blocked or missing log. `--json` is deterministic for the same inputs (`generated_at` is the only wall-clock field) and validates against the new `schemas/mcp-audit-replay-report.schema.json` (draft 2020-12; generated example `examples/mcp/audit-replay-report.example.json`). Read-only and offline by construction: no tool execution, no upstream spawn (no subprocess use at all), no profile activation, no audit writes, no network, no telemetry; the report carries tool/upstream/profile names, counts, codes, timestamps, and documented non-sensitive hashes only -- never argument values, results, audit-row error text, key material, or local paths (inputs are basenames; a leak-grep test re-scans every report string with the audit writer's own `looks_secret`/path heuristics).

- E16: MCP profile bundle rollout simulator and policy doctor (`unlimited_skills/mcp/profile_rollout.py`, `tests/test_mcp_profile_rollout.py`, `docs/mcp-profile-rollout.md`): `unlimited-skills mcp profiles rollout-plan|doctor [--config FILE] [--profiles FILE] [--bundle FILE] [--trusted-keys FILE] [--audience-id ID] [--profile NAME] [--tools-fixture FILE] [--require-signed-profiles] [--json]` — a local DRY-RUN over the artifacts the gateway would load at startup, showing what WOULD happen before applying. `rollout-plan` reports visible/hidden/callable/view-only/refused-by-policy tool counts (with full lists) over the config's pre-declared `tools` entries or an explicit what-if fixture (a JSON list of `{upstream, name, description}`), which upstreams lose all visibility and would never spawn, the profile inheritance chain with per-step narrowing (restriction-only: cumulative counts can only shrink), the exact E14 verification outcome (the REAL `resolve_bundle_state` runs in dry-run — ok with provenance, or the refusal code/name and failing step), and the exact `profile_loaded` audit-row fields plus per-upstream audit-level effects; `--json` validates against the new `schemas/mcp-profile-rollout-plan.schema.json` (draft 2020-12; generated example `examples/mcp/profile-rollout-plan.example.json`). `doctor` turns the same dry-run into distinct findings with severities (problem exits 1 / warning exits 0): missing trust store, corrupt trust store, expired keys (problem when the bundle's signing key), revoked keys, unknown signing key ids, wrong audience, issuer namespace-ceiling violations, bundle outside its validity window, profiles hiding ALL tools, inert callable rules never covered by the resolved visible set, shadowed tool names across upstreams (confused-deputy heads-up), extends chains deeper than 8, unsigned sources under the signed-required policy (plus a warning when an unsigned local file narrows a signed bundle), E15 store-doctor pass-through, and the authoritative fail-closed outcome with its exact code. Both commands are read-only and offline by construction: no upstream spawn (no subprocess use at all), no audit writes, no runtime state changes, no network, no telemetry, never private keys; E10/E14/E15 loading, verification, and trust semantics are reused, never altered or bypassed.

- E15: managed MCP profile trust store (`unlimited_skills/mcp/trust_store.py`, `tests/test_mcp_trust_store.py`, `docs/mcp-trust-store.md`): `unlimited-skills mcp trust status|list|import|revoke|doctor` manages the E14 trust artifacts under a canonical store directory `<library root>/.unlimited-skills-trust/` (`--store-dir` overrides; `--json` everywhere). The store REUSES the E14 formats verbatim as its backend — `trusted-keys.json` (the strict trusted-keys file the gateway keeps loading unchanged) and `crl.json` (the local CRL) — plus a store-only `trust-metadata.json` sidecar (`schemas/mcp-trust-store-metadata.schema.json`) for display names, informational scopes, `not_before`, import timestamps, and the append-only revocation history with optional reasons; the sidecar is never read by verification and grants nothing. `status` reports key counts by state (active / expiring soon / expired / revoked) and CRL presence; `list` shows key_id, display, scopes, validity window, state, and an abbreviated SHA-256 fingerprint (full key bytes are never printed); `import` adds PUBLIC Ed25519 keys only (from a JSON key file or inline flags), refusing private material loudly before any write (PEM PRIVATE markers, private-looking JSON fields, 48/64-byte decoded material) and refusing duplicate key_ids with different material (no silent key replacement; same-material re-import is an idempotent no-op); `revoke` appends a key_id or bundle SHA-256 to the local CRL (idempotent, append-only, history never deleted); `doctor` is an offline self-check (malformed store files, duplicate key_ids, strict-loader agreement, expired-but-not-rotated, unreadable CRL, unexplained revocations, expiring-soon warnings, best-effort permission checks) with exit code 0 ok / 1 problems. All operations are offline (no network, no registry sync, no hosted calls, never private keys) with atomic writes (temp file + replace). Gateway: when `--profile-bundle` is set and `--trusted-keys` is omitted, the gateway now defaults to the managed store's `trusted-keys.json` when it exists (an explicit flag always wins; with no managed store the behavior is byte-for-byte unchanged, `-32019` `bundle_key_missing`). E14 verification semantics are untouched — the store is a management layer, never a bypass.

- E14: signed MCP profile bundle verification prototype (`unlimited_skills/mcp/bundles.py`, `tests/test_mcp_bundle_verification.py`) implementing the E13 design (`docs/mcp-signed-profile-bundles.md`, status design → prototype): opt-in `unlimited-skills mcp gateway --profile-bundle FILE --trusted-keys FILE --audience-id ID [--require-signed-profiles]`. The 10-step verification algorithm runs once at startup — file SHA-256, strict shape/static checks, trusted-key lookup (multiple active keys by `key_id` = rotation), detached Ed25519 signature over the canonical JSON minus `signature`, validity window (±300 s skew), local CRL (bundle SHA-256 and key-id revocation; declared-but-unreadable CRL fail-closed), audience intersection (`--audience-id` > `UNLIMITED_SKILLS_MCP_AUDIENCE`), namespace ceiling, then the unchanged E09 static checks and selection precedence. Every failure is a fail-closed refuse-all with the reserved codes: `-32015` `bundle_signature_invalid` (tampered/stripped-under-policy/unverifiable), `-32016` `bundle_expired` (also not-yet-valid), `-32017` `bundle_revoked`, `-32018` `bundle_audience_mismatch` (also ceiling violations), `-32019` `bundle_key_missing` (missing trusted-keys file/key/backend — never a silent fallback to unsigned); malformed bundles reuse `-32014`, selection failures `-32013`. Signature verification is a pluggable backend; the default uses the optional `cryptography` package (real Ed25519) and an absent backend is `-32019` fail-closed. `--profiles` alongside a bundle is the narrow-only local override (intersection; the local file can never widen the bundle; its `default_profile` is ignored); `--require-signed-profiles` refuses unsigned profile sources with `-32015`; without the new flags the raw `--profiles` path and no-profiles mode are byte-for-byte unchanged. The `profile_loaded` audit row now records the profile source type (`raw_file`/`signed_bundle`) plus, for bundles, the bundle SHA-256, issuer key id/display, audience, expiry, and verification status (failed verifications append a row naming the failing step's code); key material and signature values never appear in audit rows, and the existing redaction floor is untouched.

- E12B MCP warm tool-index cache (strictly opt-in, default OFF): `unlimited-skills mcp gateway --index-cache [DIR]` persists each upstream's indexed tool entries (names, descriptions, `inputSchema`s, oversized markers) to one atomic JSON file (`<library>/.learning/mcp-tool-index-cache.json` by default, or `<DIR>/mcp-tool-index-cache.json`), implementing candidate 1 of the `docs/mcp-performance.md` warm-start plan. On startup with the flag, valid entries load into the in-memory index without spawning anything, so a restarted gateway answers `tools_schema`/`tools_search` at near-reuse cost (~1 ms vs the ~150 ms first-touch spawn); `tools_call` still spawns lazily as before. Entries are keyed by the SHA-256 of the canonical upstream spec plus the `serverInfo` name/version captured at index time; any config change is a miss, every live spawn re-indexes and overwrites the entry (resolving version changes), `tools_search` `refresh: true` rewrites entries, entries older than 7 days are ignored, and corrupt/unknown-version cache files are ignored and counted, never a crash. Cached schemas are re-validated against `max_schema_bytes` at load (oversized → name-only marker, refused, never truncated); disabled/placeholder upstreams never receive cached tools; cache files contain only what the gateway already had in memory — never env values, credentials, arguments, or results. New audit events `cache_loaded`/`cache_refresh` carry counts, upstream names, and the cache file SHA-256 only (no schema bodies, no local paths). Without the flag the gateway behaves byte-for-byte as before (`tests/test_mcp_warm_cache.py` proves default-off, no-spawn cache hits, invalidation, and audit redaction). New module `unlimited_skills/mcp/index_cache.py`; flag docs in `docs/mcp-gateway.md`.
- v0.4.6-alpha MCP performance benchmark integration gate: fixture-only benchmark smoke, release manifest, verifier, integration test, version bump to `0.4.6`, and release docs covering cold start, spawn vs reuse, schema indexing, `tools_search`, audit overhead, context bytes, best-effort memory, report schema validation, no runtime default changes, and warm-start plan-only boundaries. Codex must not create or push the `v0.4.6-alpha` tag from this integration gate.
- v0.4.5-alpha final publication gate: publication smoke, publication verifier, upgrade notes, manifest tag policy, and traceability for the MCP audit inspector milestone. Codex may create and push the `v0.4.5-alpha` tag only after the final publication verifier passes on the selected `main` SHA.
- v0.4.5-alpha MCP audit inspector integration gate: read-only `mcp audit-report`, JSON schema-validated reports, rotated audit log discovery, safe recent refusal summaries with no argument values and no error text, profile audit evidence, redaction self-checks that never print suspect values, clear missing-log exits, and no OAuth/remote/resources/prompts/hosted-gateway/production-hosted-calls/audit-log-writes boundaries are covered by fixture-mode smoke and verifier evidence. Codex must not create or push the `v0.4.5-alpha` tag from this integration gate.
- E11 MCP audit inspector: `unlimited-skills mcp audit-report [--audit-log PATH] [--json] [--section summary|refusals|upstreams|profiles|redaction|all]` turns the local redacted audit JSONL log (active file plus rotated generations `.1`..`.N`, read in chronological order) into read-only reports — call summary with per-tool duration min/median/p95/max, refusal breakdown by named JSON-RPC code (`-32001`…`-32014`, unknown codes reported as `unknown`), per-upstream health with refusal-rate flagging (timeouts/protocol errors/spawn failures), profile usage (per-profile counts, `profile_loaded` SHA-256 events, profile refusals — present only when E10 `profile` fields exist in the log; accepted, never required), and a redaction self-check that re-scans audited strings with the writer's own `looks_secret`/path heuristics and reports PASS/FAIL with file+line+field+reason only (suspect values are never printed). Pure functions in `unlimited_skills/mcp/audit_inspector.py`; JSON document validated by `schemas/mcp-audit-report.schema.json` (draft 2020-12); docs `docs/mcp-audit-inspector.md`; tests `tests/test_mcp_audit_inspector.py`. Malformed JSONL lines are counted and skipped; a missing log is a clear message with exit code 1. The inspector never writes or rotates audit files and never changes the audit write format.
- v0.4.4-alpha MCP permissioned tool profile enforcement integration gate: default-deny selected profiles, CLI/env profile precedence, visible-only search, hidden schema refusal, non-callable call refusal, restriction-only inheritance, fail-closed missing/invalid profiles, `profile_loaded` audit rows, profile SHA-256 evidence, and no OAuth/remote/resources/prompts/hosted-gateway/production-hosted-calls boundaries are covered by fixture-mode smoke and verifier evidence.
- Added `scripts/run-v044-alpha-mcp-tool-profiles-smoke.py`, `scripts/verify-v044-alpha-mcp-tool-profiles.py`, `tests/integration/test_v044_alpha_mcp_tool_profiles.py`, and v0.4.4-alpha release docs/manifest.
- v0.4.4-alpha final publication package: upgrade notes, release smoke runner, publication verifier, final manifest tag policy, no-private-material scan, and exact Codex tag command for `v0.4.4-alpha`.
- Raised package, Claude plugin, and marketplace metadata versions to `0.4.4`.
- Updated the v0.4.3 release smoke/publication verifier so later release branches can verify the already-published `v0.4.3-alpha` tag while package/plugin versions move forward.
- v0.4.3-alpha MCP upstream enforcement integration gate: disabled upstream refusal, future-remote-placeholder refusal, command allowlist refusal, names-only `env_allowlist` enforcement, schema/response size refusals, startup timeout and request timeout hard bounds, audit rotation, and audit redaction are covered by fixture-mode smoke and verifier evidence.
- Added `scripts/run-v043-alpha-mcp-enforcement-smoke.py`, `scripts/verify-v043-alpha-mcp-enforcement.py`, `tests/integration/test_v043_alpha_mcp_enforcement.py`, and v0.4.3-alpha release docs/manifest.
- v0.4.3-alpha final publication package: upgrade notes, release smoke runner, publication verifier, final manifest, profile-design documentation proof, no-private-material scan, and exact Codex tag command for `v0.4.3-alpha`.
- Raised package, Claude plugin, and marketplace metadata versions to `0.4.3`.
- Updated the v0.4.2 release smoke/publication verifier so later release branches can verify the already-published `v0.4.2-alpha` tag while package/plugin versions move forward.
- E12 MCP performance benchmark pack (fixture-only, no runtime default changes): `scripts/run-mcp-performance-benchmarks.py --fixture-mode --json [--sizes 40,200,1000] [--out DIR]` (+ `scripts/mcp_perf_support.py`) measures cold gateway start (spawn → initialize → tools/list), warm spawn-vs-reuse for `tools_schema`/`tools_call`, `tools_search` latency with and without `refresh`, per-upstream schema indexing cost, audit write overhead (no audit vs `minimal` vs `standard`), context bytes (the context-budget methodology at every size), and best-effort gateway peak RSS via OS facilities (no psutil). High-resolution monotonic timers, K repeats with discarded warmup, raw samples carried in the JSON report (`schemas/mcp-perf-report.schema.json`); Markdown + JSON written to the gitignored `build/perf/`. Smoke-tested by `tests/test_mcp_performance_benchmarks.py` (schema validation, section completeness, no secret-shaped values or local paths in reports, context-bytes consistency, spawn > reuse).
- `docs/mcp-performance.md`: how to run the benchmarks, what each metric means, the measured reference tables (40/200/1000 tools), and the warm-start optimization PLAN (design only): persistent tool-index cache keyed by config hash, opt-in pre-spawn of allowlisted upstreams, index serialization and invalidation rules, expected impact, risks, and the evidence that would gate each optimization — everything default-off to preserve current lazy behavior.
- v0.4.2-alpha MCP integration gate: release notes, checklist, known issues, manifest, fixture-mode smoke JSON report, verifier, and integration test proving E06 MCP server/gateway core and E07 upstream security model evidence together without production hosted calls.
- v0.4.2-alpha final publication package: package/plugin version `0.4.2`, upgrade notes, release smoke runner, publication verifier, final manifest, no-private-material scan, and release-owner human tag instructions.
- `scripts/verify-v042-alpha-mcp.py` verifies MCP fixture transcripts, compact `tools_search`, single-tool `tools_schema`, fixture `tools_call`, no full schema dump, lazy spawn/reuse, audit redaction, no sensitive-marker leakage, and E07 security model requirements (`local-restricted` default, no shell contract, names-only `env_allowlist`, impossible wildcard forwarding, size/timeout caps, no OAuth/remote/resources/prompts).
- `scripts/verify-v042-alpha-publication.py` verifies the final v0.4.2-alpha publication boundary, required PR manifest, version consistency, release docs, tag state, and no private key/token/payment-field material in public release docs.

- E07 design (docs/schema only, no implementation): MCP upstream configuration and security model (`docs/mcp-upstream-security-model.md`) — per-upstream trust levels (`disabled` / `local-restricted` default / `local-trusted` / `future-remote-placeholder`), command allowlisting (no shell, absolute-path-or-known-binary), forward-nothing environment policy with a names-only `env_allowlist` (wildcards unrepresentable), bounded timeouts and schema/response size caps with refusal-not-truncation, audit levels and JSONL rotation/retention, extended refusal codes `-32005`…`-32010` (`upstream_disabled`, `command_not_allowed`, `env_forwarding_denied`, `schema_too_large`, `response_too_large`, `trust_level_violation`), a 9-vector threat model, and explicit future gates for OAuth/remote upstreams and MCP resources/prompts.
- `schemas/mcp-upstream-config.schema.json` (draft 2020-12) and validated annotated example `examples/mcp/upstreams.example.json`; `tests/test_mcp_upstream_config_schema.py` validates the example against the schema with a minimal self-contained validator (positive plus negative cases: unknown trust level, env wildcard, v1 `env` literal map, oversize/zero limits).
- E08: the gateway now ENFORCES the E07 upstream security model (`tests/test_mcp_upstream_enforcement.py`): trust levels (`disabled`/`enabled:false` upstreams are never spawned, never indexed, refused with `-32005`; `future-remote-placeholder` refuses all I/O with `-32010`), the command allowlist (absolute path required at `local-restricted`, frozen known-runner bare names — `node`, `npx`, `bunx`, `deno`, `python`, `python3`, `uv`, `uvx` — at `local-trusted`, shell binaries and relative paths refused everywhere with `-32006`), names-only env forwarding over a fixed minimal base set (`-32007` on violations), schema/response size caps with trust-level ceilings and refusal-not-truncation (`-32008`/`-32009`), timeout hard bounds (startup ≤ 120 s, request ≤ 300 s; out-of-range config rejected at load), per-upstream `audit_level` (`standard`/`minimal`, no `off`), and size-based audit JSONL rotation (`audit_max_bytes` default 10 MiB, `audit_max_files` default 5).
- E09 design (docs/schema only, no implementation): MCP permissioned tool profiles (`docs/mcp-permissioned-tool-profiles.md`) — named profiles with separate visibility (filters `tools_search`, gates `tools_schema`) and callability (gates `tools_call`) rule sets over fully qualified `<upstream>.<tool>` identifiers; a bounded two-form rule grammar (exact name or `<upstream>.*`, no regex, no partial globs, no wildcard upstream segment); callable always a subset of visible; default-deny when a profile is active and fail-closed refuse-all when the selected profile is missing or the file is invalid (no-profiles mode stays the open default until v0.6); selection precedence `--profile` > `UNLIMITED_SKILLS_MCP_PROFILE` > `default_profile`; single-parent restriction-only `extends` inheritance (a child can narrow but never widen; self-reference/cycles/depth>8 are load errors); reserved refusal codes `-32011`…`-32014` (`tool_not_visible` — existence-neutral, returned before any existence check; `tool_not_callable`; `profile_not_found`; `profile_invalid`); profile-stamped audit rows plus a `profile_loaded` row with the file SHA-256, restart-only reload; an optional forward-compatible detached-signature envelope (shape-only in v1, verification gated to a future signing gate); threat-model vectors 10–13; and a proposed v0.6 flip requiring an explicit `--profiles`-or-`--no-profiles` choice at gateway startup.
- `schemas/mcp-tool-profile.schema.json` (draft 2020-12) and validated annotated example `examples/mcp/tool-profile.example.json`; `tests/test_mcp_tool_profile_schema.py` validates the example against the schema with the same minimal self-contained validator pattern (extended with `patternProperties`/`minProperties`/`maxProperties`/`maxLength`) plus the design's semantic load rules as executable documentation (negative cases: unknown keys, glob/regex/whitespace rule strings, bad profile names, self-extends, inheritance cycles, unknown parents, uncovered callable rules, wrong types, malformed signature envelopes).
- E10: the gateway now ENFORCES the E09 permissioned tool profiles (`unlimited_skills/mcp/profiles.py`, `tests/test_mcp_tool_profile_enforcement.py`), opt-in via `unlimited-skills mcp gateway --profiles FILE [--profile NAME]` (no-profiles mode stays the unchanged open default until v0.6). Profile loading is once-at-startup (no hot reload) with strict shape validation (unknown keys fail loudly) plus the design's static checks (`extends` exists / no self-reference / no cycle / depth ≤ 8, callable covered by visible, `default_profile` exists; signature envelope shape-only, never verified); selection precedence is `--profile` > `UNLIMITED_SKILLS_MCP_PROFILE` > `default_profile`, with no fallback on unresolved names. Enforcement: `tools_search` returns only visible tools (hidden tools absent, pre-declared and live-indexed alike, with a `callable: true|false` field per hit) and `refresh` never spawns an upstream that cannot contribute a visible tool; `tools_schema`/`tools_call` refuse invisible tools with the existence-neutral `-32011` `tool_not_visible` before any existence check or lazy spawn (hidden ≡ nonexistent, byte-identical refusals); `tools_call` refuses visible-but-not-callable tools with `-32012` `tool_not_callable` without spawning; missing/invalid profiles fail closed (`-32013` `profile_not_found` / `-32014` `profile_invalid`) refusing every meta-tool call while the gateway keeps serving (plus a stderr notice on interactive starts). Audit rows carry the profile name at both audit levels while profiles are active, a `profile_loaded` startup row pins the profile file SHA-256 and rule counts, rule evaluation never receives call arguments, and the existing redaction floor is untouched.
- E13 design (docs/schema only, no implementation): MCP signed profile bundles (`docs/mcp-signed-profile-bundles.md`, Gate C of the E09 profiles design) — a signed, self-contained distribution envelope for permissioned tool profiles: issuer (key id + display), mandatory non-empty audience (`team:`/`org:`/`host:` identifiers), mandatory validity window (`issued_at`/`expires_at`, ±300 s skew), an `allowed_upstream_namespaces` ceiling in the E09 rule grammar that every embedded profile rule must stay inside, the E09 profile map embedded verbatim (self-contained `extends`, no cross-file parents in either direction), an optional revocation pointer (local CRL file with revoked bundle SHA-256s and key ids; declared-but-unreadable is fail-closed; `registry_endpoint` carried but never fetched in v1), and a mandatory detached Ed25519 signature over the canonical JSON (sorted keys, no insignificant whitespace) minus the `signature` member. Trust is one local trusted-keys file (no PKI, no network fetch); rotation is multiple active keys with an overlap window selected by `key_id`. Reserved refusal codes `-32015`…`-32019` (`bundle_signature_invalid` — also covers stripped signatures and missing verifier backends; `bundle_expired` — also not-yet-valid; `bundle_revoked`; `bundle_audience_mismatch` — also namespace-ceiling violations; `bundle_key_missing` — fail-closed, never a silent fallback to unsigned), all refuse-all states; malformed bundles reuse `-32014` `profile_invalid`. Unsigned local profiles stay allowed by default and in the MIT core indefinitely; registered/business distribution requires signed bundles; a `--require-signed-profiles` policy (default off pre-v0.6) refuses unsigned sources; local unsigned profiles may only narrow an active bundle by intersection (`local_override: narrow-only`), never widen it. Audit `profile_loaded` rows gain bundle SHA-256, issuer key id/display, audience, and expiry; threat-model vectors 14–18 (key theft, stale/replayed bundle, downgrade-to-unsigned, audience confusion, revocation unavailability); enforcement and evidence gates are specified for a future E14 change.
- `schemas/mcp-profile-bundle.schema.json` (draft 2020-12, `additionalProperties: false`, embeds the E09 profile shape verbatim) and validated annotated example `examples/mcp/profile-bundle.example.json` (placeholder signature: base64 of 64 zero bytes, clearly fake); `tests/test_mcp_profile_bundle_schema.py` validates the example against the schema with the same minimal self-contained validator pattern (extended with `minItems`), keeps the duplicated profile constraints honest against `schemas/mcp-tool-profile.schema.json`, and encodes the bundle's semantic load rules as executable documentation (negative cases: missing signature block, unknown algorithm, expired-before-issued and equal timestamps, empty audience, schemeless/unknown-scheme audience identifiers, regex/glob/wildcard namespace rules, unknown top-level and revocation keys, loose timestamp formats, `signature.key_id` ≠ `issuer.key_id`, profile rules outside the namespace ceiling, non-https `registry_endpoint`, and the E09 extends/coverage/default checks inside a bundle).

- Unlimited Tools MCP core (`unlimited_skills/mcp/`): a zero-dependency JSON-RPC 2.0 / MCP stdio implementation (no external MCP SDK) with auto-detected framing (newline-delimited JSON and LSP-style `Content-Length`), MCP lifecycle (`initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`), and a reusable `StdioServer` loop over a tool registry.
- `unlimited-skills mcp serve`: a skills MCP server exposing `skills_search` (metadata-only hits — never bodies or absolute paths), `skills_view` (one skill body capped at 16K chars with truncation marker), and `skills_use` (view plus a local learning event; reads SKILL.md text only, never executes scripts).
- `unlimited-skills mcp gateway --config ... [--audit-log ...]`: the Unlimited Tools gateway fronting upstream stdio MCP servers with 3 meta-tools — `tools_search` (names + descriptions only, never schemas), `tools_schema` (exactly one tool's `inputSchema`, lazily), `tools_call` (routed and relayed). Upstreams spawn lazily on first need, are reused, and are terminated on shutdown; the tool index is cached in-memory per process.
- Redacted append-only MCP audit log (`<library>/.learning/mcp-audit.jsonl` by default) recording `ts`, `tool`, `upstream`, `duration_ms`, `ok` for every meta-tool call.
- Schemas `mcp-server-config`, `mcp-gateway-config`, `mcp-tool-index` (draft-07); examples `examples/mcp/gateway-config.example.json` and `tools-call-request.example.json`; docs `docs/unlimited-tools.md`, `docs/mcp-server.md`, `docs/mcp-gateway.md`.
- Fixture-only MCP tests: protocol framing/lifecycle/error codes, skills server metadata boundaries and caps, gateway lazy spawn + routing against a fake subprocess upstream, audit redaction.
- MCP smoke and boundary harness: `scripts/run-mcp-smoke.py`, `scripts/verify-mcp-boundaries.py`, `scripts/run-v042-alpha-mcp-smoke.py`, subprocess integration tests, and JSON-RPC request examples for `skills_search`, `tools_search`, `tools_schema`, and `tools_call`.

- Local-only `skillops usage-snapshot` command with JSON, `--out`, `--dry-run`, and `explain` modes for privacy-preserving SkillOps recommendation context.
- Usage snapshot schema, example payload, and documentation covering included counts, excluded sensitive data, and no-hosted-call behavior.
- Support bundle counts-only usage snapshot summary.
- v0.4.1-alpha Reliability publication package: release notes, checklist, upgrade notes, known issues, release manifest, reliability smoke runner, release smoke runner, and publication verifier.
- Post-tag `v0.4.0-alpha` release smoke compatibility: the v0.4.0 smoke can verify that the published tag points to the expected release-owner commit without letting Codex create or overwrite tags.

### Security

- MCP servers are stdio-only and local-only: no network listeners, no OAuth upstreams, no MCP resources/prompts in v1.
- BREAKING (pre-0.6, no shim): the v1 gateway upstream `env` literal map (`{"X": "%X%"}`) is rejected at config load with a pointer to `env_allowlist`. Upstreams now receive a from-scratch environment: a fixed minimal base set (`COMSPEC` excluded — no shell) plus only the variable names in `env_allowlist`, copied from the local environment and never logged. The gateway's own working directory is never inherited (per-upstream scratch dir or explicit absolute `cwd`); the superseded draft-07 `schemas/mcp-gateway-config.schema.json` was removed in favor of `schemas/mcp-upstream-config.schema.json`.
- MCP audit redaction: argument values for keys matching token/secret/key/password/proof/authorization are never written; env values, skill bodies, and tool results are never written (only shapes/counts); local paths are scrubbed from error strings; `redact()` is a pure tested function.
- MCP audit now also redacts search queries and free-form text inputs, so local audit rows prove no prompt/query/tool-input plaintext leakage while preserving call shape, timing, upstream, and success/refusal status.
- The v0.4.3-alpha MCP upstream enforcement integration gate keeps OAuth, remote upstreams, MCP resources/prompts, hosted gateway, production hosted calls, automatic telemetry, full schema dumps, arbitrary shell execution, live billing, PyPI publication, full catalog distribution, and auto-publish disabled while proving E08 local stdio runtime refusals and audit controls.
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
