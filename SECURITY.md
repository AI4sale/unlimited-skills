# Security Policy

## Supported Version

`v0.4.3-alpha` is a developer preview. Security fixes should target the current `main` branch first.

The older `v0.3.7-alpha` security boundary remains documented for compatibility with the v0.2.x smoke claims that protect release-history wording.

## Responsible Disclosure

Report security issues privately before public disclosure.

- Email: security@ai4.sale
- Include affected version or commit, reproduction steps, expected impact, and the smallest safe logs or archive samples needed to reproduce.

Do not send live credentials, private keys, customer data, tokens, secrets, full repository paths, environment dumps, or unrelated private data in reports. If a secret was exposed while reproducing an issue, rotate it before sending the report.

## Local-First Boundary

The MIT Community Core is designed to work offline. Local commands such as `search`, `list`, `view`, `where`, `use`, `feedback`, `reindex`, `vector-reindex`, `serve`, `adapt`, installers, migration scripts, local learning logs, native sync, and public self-update do not require registration.

Registration is required only for official AI4sale-hosted services: hosted adapted catalog, community catalog/submissions, adapted collection updates, registered local enhancement scripts, hosted archives, team sync, dashboard/cloud/business/enterprise features, and future hosted services.

The hosted clients must not upload:

- skill bodies;
- prompts or conversation history;
- source code;
- full local paths or repository paths;
- customer names;
- environment variables;
- tokens, secrets, or credentials;
- device private keys.

## Hosted Archives And Enhancers

Current `v0.4.3-alpha` behavior:

- hosted remote manifests must include valid signed manifest envelopes;
- signatures verify hosted manifest authenticity;
- trusted manifest keys are scoped, can be pinned to registry origins, and can be revoked locally;
- hosted collection archives are SHA256-verified before extraction;
- zip extraction rejects path traversal;
- local enhancement scripts are SHA256-verified before execution;
- hosted features require a registered installation token and signed device proof;
- private signing keys are never shipped in the client.

Use "signed hosted manifests plus SHA256-verified hosted collection archives" for the current security boundary. Do not describe hosted archive bytes as cryptographically signed or cryptographically verified unless archive-byte signatures are implemented separately.

## Local Skill Hub MVP Boundary

Local Skill Hub is an alpha MVP. The runtime is allowlist-only, does not execute skills, and does not forward local search queries to the hosted registry. It is intended for local or controlled LAN testing.

Current `v0.4.3-alpha` limitations:

- Hub client token creation, revocation, and request enforcement are implemented for Local Skill Hub `/v1/...` APIs. `GET /health` remains unauthenticated for liveness checks.
- Use the default `127.0.0.1` bind address unless you are testing on a trusted LAN.
- LAN bind requires explicit `--allow-lan` and at least one active hub client token. For serious LAN testing, put the hub behind a reverse proxy or network control that provides TLS, authentication, access logging, and IP allowlisting.
- Local install plan skills are metadata/resolution only until client capability checks are implemented.
- Full catalog distribution remains disabled; the hub may serve only allowlisted skills.
- Release artifacts are checked by the v0.2.2, v0.3.0, v0.3.1, v0.3.2, v0.3.3, v0.3.4, v0.3.5, v0.3.6, v0.3.7, v0.3.8, and v0.3.9 alpha release verifiers for version consistency, unsafe release claims, final publication placeholders, and obvious private key/token material. The `v0.3.9-alpha` tag remains pending release-owner approval until the publication verifier passes on the selected tag target.

## Catalog Browser Boundary

Catalog browser commands require registration, hosted token, and signed device proof. Responses must be signed metadata, not skill bodies. The client hides unapproved statuses by default, refuses body-including preview responses, and keeps `catalog install --dry-run` write-free.

Catalog browser support diagnostics must not print search queries, item names, skill bodies, local paths, hosted tokens, device proofs, or device private keys.

## Private Team Packs Boundary

Private team pack hosted operations require registration, device proof, trusted `private-team-pack` manifest keys, and registry-side entitlement or Business/Enterprise plan. The public client verifies the signed manifest, downloads archives through proofed POST requests, verifies archive SHA256, safely extracts under `registry/private/<pack_id>`, and removes only registry-owned private-pack paths.

Setup, service diagnostics, doctor, and support bundle output include only redacted counters and error codes by default. They must not print private pack names by default, private skill names, skill bodies, archive URLs, local paths, hosted tokens, device proofs, or private keys.

## Org/Team Governance Diagnostics Boundary

`org status` reads local cached organization/team status without hosted calls. `org status --refresh` requires a registered installation and hosted device proof. Private pack access diagnostics use hashed pack references and stable denial codes by default; they must not print private pack names, private skill names, private skill bodies, raw archive URLs, hosted tokens, device proofs, or private keys.

## Billing Lifecycle Diagnostics Boundary

`billing status` and `billing doctor` are local/cache-only diagnostics. `billing refresh` requires a registered installation and hosted device proof. The public client treats billing as sandbox lifecycle visibility only: it does not create checkout sessions, collect payment data, store card or bank data, create real charges, or enable live payment providers.

Billing diagnostics and support bundles must not print checkout URLs, payment links, invoice URLs, card data, bank data, hosted tokens, device proofs, device private keys, local paths, private skill names, private skill bodies, or private pack bodies.

## Community Catalog Boundary

Hosted community list, search, preview, install, submission status, withdraw, and review-notes require registration. `community submit --dry-run` remains local-only and does not upload content. Preview and install require signed hosted responses, and install is allowed only for signed items whose review status is `approved` or `published`.

Community diagnostics and support bundles must not print search queries, private item names by default, private skill bodies, prompts, raw archive URLs, hosted tokens, device proofs, device private keys, checkout URLs, payment links, invoice URLs, card data, bank data, or local paths.

## Skill Improvement Boundary

Skill improvement status is a maintainer-controlled workflow. The public client can display signed metadata for improvement status, known issues, fixed pending eval status, preview-only update recommendations, and deprecated or retired warnings.

The public client and v0.3.9-alpha tests must not rewrite skills automatically, auto-publish, execute untrusted remediation scripts, upload prompts, upload task text, upload search queries, upload skill bodies, perform user telemetry, or call production hosted services.

Support bundles include only aggregate skill improvement counters. They must not print item ids, issue titles, raw feedback, recommendations, private skill bodies, prompts, search queries, local paths, repo paths, hosted tokens, device proofs, or private keys.

## v0.4 Cross-Repo Readiness Boundary

The v0.4 cross-repo readiness suite is a fixture/local-checkout verification gate, not v0.4 feature implementation. It verifies signed SkillOps metadata, unsigned and forbidden-field rejection, policy-aware refusal codes, eval gate fixtures, maintainer queue transition fixtures, skill improvement workflow evidence, and support-bundle redaction.

The suite must not call production hosted services, require production signing keys, distribute private registry content in the public repo, enable live billing, publish to PyPI, distribute the full catalog, install/update/remove skills automatically, rewrite skills automatically, or auto-publish.

The v0.4 go/no-go package can approve starting implementation epics after review and merge, but it does not authorize production rollout. Every v0.4 implementation layer still needs runtime, registry, security, privacy, and release-owner review before release.

## v0.4.0-alpha E01-E04 Boundary

The v0.4.0-alpha SkillOps foundation milestone is an alpha verification and publication layer for policy-aware recommendation preview, eval release operator workflow, maintainer queue runtime/status, and governance dashboard signed summaries. It is not a production SLA.

The gate must not call production hosted services, require production signing keys, upload prompts, upload task text, upload skill bodies, upload search queries, include private pack bodies, include local or repository paths, enable live billing, publish to PyPI, distribute the full catalog, install/update/remove skills automatically, rewrite skills automatically, or auto-publish. MIT local core behavior remains registration-free. Codex must not create or push the final release tag; the tag stays pending release-owner approval until the selected `main` SHA passes `verify-v040-alpha-publication.py`.

## v0.4.1-alpha Reliability Boundary

The v0.4.1-alpha Reliability milestone is an alpha verification and publication layer for transactional installs, rollback manifest schema v2, same-second reinstall backup collision protection, `VectorModelMismatch`, hybrid lexical fallback on stale vector indexes, modular CLI command routing, and `skillops usage-snapshot` compatibility after the CLI split. It is not a production SLA.

The gate must not call production hosted services, require production signing keys, upload prompts, upload task text, upload skill bodies, upload search queries, include private pack bodies, include local or repository paths, enable live billing, publish to PyPI, distribute the full catalog, rewrite skills automatically, enable automatic telemetry, or auto-publish. Codex must not create or push the final `v0.4.1-alpha` tag; the release owner verifies the selected `main` SHA and runs the human tag command.

## v0.4.2-alpha MCP Integration Boundary

The v0.4.2-alpha MCP milestone is an alpha publication layer for `unlimited-skills mcp serve`, `unlimited-skills mcp gateway`, the fixture-only Unlimited Tools smoke harness, and the E07 upstream security model contract. It proves local stdio JSON-RPC handshake, `skills_search`, `skills_view`, `skills_use`, `tools_search`, `tools_schema`, `tools_call`, context-budget reduction, lazy upstream spawn/reuse, structured refusals, compact schema retrieval, audit redaction, and security-model documentation/schema evidence. It is not a production SLA.

The gate must not call production hosted services, require production signing keys, upload prompts, upload task text, upload skill bodies, upload search queries, include private pack bodies, include local or repository paths, enable live billing, publish to PyPI, distribute the full catalog, rewrite skills automatically, enable automatic telemetry, expose a hosted gateway, implement OAuth or remote upstreams, enable MCP resources or prompts, or auto-publish. E07 runtime enforcement is intentionally tracked as later implementation work; v0.4.2-alpha verifies the contract and fixture behavior. Codex must not create or push the final `v0.4.2-alpha` tag; the release owner verifies the selected `main` SHA and runs the human tag command.

## v0.4.3-alpha MCP Upstream Enforcement Boundary

The v0.4.3-alpha MCP milestone integrates E08 runtime enforcement for local stdio upstreams. It proves disabled upstream refusal, future-remote-placeholder refusal, command allowlist enforcement, names-only `env_allowlist` enforcement, `schema_too_large` and `response_too_large` refusal paths, startup timeout and request timeout hard bounds, audit rotation, and audit redaction.

The gate remains alpha and local stdio only. It must not call production hosted services, require production signing keys, upload prompts, upload task text, upload skill bodies, upload search queries, include private pack bodies, include local or repository paths, enable live billing, publish to PyPI, distribute the full catalog, rewrite skills automatically, enable automatic telemetry, expose a hosted gateway, implement OAuth or remote upstreams, enable MCP resources or prompts, allow shell execution, or auto-publish. Codex must not create or push the final `v0.4.3-alpha` tag.

## Known Security Limitations In v0.3.9-alpha

- Hosted manifest signatures verify manifest authenticity; archive bytes are still verified with SHA256 and safe extraction, not archive-byte signatures.
- The hosted registry is early-access and availability may be limited.
- Community submissions are implemented as explicit uploads behind local validation, preview, confirmation, registration, hosted maintainer review, and signed approved/published distribution.
- Production-signed registry artifacts are not verified until the protected private-registry signing ceremony completes. The final v0.3.1-alpha publication verifier blocks by default in this state unless the release owner explicitly accepts blocked registry signing as a known issue.
- Enterprise Skill Lock is implemented as an opt-in local policy MVP. Managed hosted policy sync client behavior is implemented and verified against a fixture contract; production private-registry endpoint delivery remains an in-review private registry dependency for the v0.3 alpha stack. SSO, SCIM, live billing, hosted payment provider integration, organization administration, hosted dashboard controls, and broad enterprise private-registry enforcement are not implemented in this alpha.
- Warm daemon mode is experimental and binds to `127.0.0.1` by default; do not expose it on public interfaces.
- Private team packs are an alpha registered/entitled flow. Production access depends on the private registry distribution, publishing, admin, and entitlement PRs being accepted and deployed.
- Catalog feedback is explicit only and registration-gated. It must not include prompts, task text, skill bodies, local paths, repo paths, customer data, tokens, device proofs, private keys, archive URLs, checkout URLs, or payment links.
- Skill improvement recommendations are preview-only signed metadata. They do not install, update, remove, rewrite, sign, promote, or publish skills.
- The GitHub clone is the v0.3.9-alpha distribution path because repo assets are required. PyPI packaging is not the supported alpha install path yet.
- Catalog browser official and private-visible installs are metadata/dry-run only until dedicated install-plan capability checks are implemented.
- Registry signing status is `blocked_no_production_signing_key` in the v0.3.7 final publication gate until the release owner updates it to `production_signed` or records an explicit override.

## Scope

In scope:

- path traversal in archive extraction;
- hosted update or enhancement downloads that bypass checksum verification;
- leakage of local skill contents, prompts, secrets, or full paths through hosted client payloads;
- unsafe installer behavior that overwrites unrelated files outside documented target roots;
- authentication or authorization issues in registered hosted flows;
- doctor or status commands that print registration tokens or device private keys.

Out of scope for this public alpha policy:

- social engineering;
- denial-of-service without a practical security impact;
- vulnerabilities in third-party dependencies unless Unlimited Skills uses them in a way that creates additional risk;
- issues requiring already-compromised local administrator/root access without a clear privilege boundary.
