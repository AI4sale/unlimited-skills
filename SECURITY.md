# Security Policy

## Supported Version

`v0.3.5-alpha` is a developer preview. Security fixes should target the current `main` branch first.

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

Current `v0.3.5-alpha` behavior:

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

Current `v0.3.5-alpha` limitations:

- Hub client token creation, revocation, and request enforcement are implemented for Local Skill Hub `/v1/...` APIs. `GET /health` remains unauthenticated for liveness checks.
- Use the default `127.0.0.1` bind address unless you are testing on a trusted LAN.
- LAN bind requires explicit `--allow-lan` and at least one active hub client token. For serious LAN testing, put the hub behind a reverse proxy or network control that provides TLS, authentication, access logging, and IP allowlisting.
- Local install plan skills are metadata/resolution only until client capability checks are implemented.
- Full catalog distribution remains disabled; the hub may serve only allowlisted skills.
- Release artifacts are checked by the v0.2.2, v0.3.0, v0.3.2, v0.3.3, v0.3.4, and v0.3.5 alpha release verifiers for version consistency, unsafe release claims, final publication placeholders, and obvious private key/token material.

## Private Team Packs Boundary

Private team pack hosted operations require registration, device proof, trusted `private-team-pack` manifest keys, and registry-side entitlement or Business/Enterprise plan. The public client verifies the signed manifest, downloads archives through proofed POST requests, verifies archive SHA256, safely extracts under `registry/private/<pack_id>`, and removes only registry-owned private-pack paths.

Setup, service diagnostics, doctor, and support bundle output include only redacted counters and error codes by default. They must not print private pack names by default, private skill names, skill bodies, archive URLs, local paths, hosted tokens, device proofs, or private keys.

## Org/Team Governance Diagnostics Boundary

`org status` reads local cached organization/team status without hosted calls. `org status --refresh` requires a registered installation and hosted device proof. Private pack access diagnostics use hashed pack references and stable denial codes by default; they must not print private pack names, private skill names, private skill bodies, raw archive URLs, hosted tokens, device proofs, or private keys.

## Billing Lifecycle Diagnostics Boundary

`billing status` and `billing doctor` are local/cache-only diagnostics. `billing refresh` requires a registered installation and hosted device proof. The public client treats billing as sandbox lifecycle visibility only: it does not create checkout sessions, collect payment data, store card or bank data, or enable live payment providers.

Billing diagnostics and support bundles must not print checkout URLs, payment links, invoice URLs, card data, bank data, hosted tokens, device proofs, device private keys, local paths, private skill names, private skill bodies, or private pack bodies.

## Community Catalog Boundary

Hosted community list, search, preview, install, submission status, withdraw, and review-notes require registration. `community submit --dry-run` remains local-only and does not upload content. Preview and install require signed hosted responses, and install is allowed only for signed items whose review status is `approved` or `published`.

Community diagnostics and support bundles must not print search queries, private item names by default, private skill bodies, prompts, raw archive URLs, hosted tokens, device proofs, device private keys, checkout URLs, payment links, invoice URLs, card data, bank data, or local paths.

## Known Security Limitations In v0.3.5-alpha

- Hosted manifest signatures verify manifest authenticity; archive bytes are still verified with SHA256 and safe extraction, not archive-byte signatures.
- The hosted registry is early-access and availability may be limited.
- Community submissions are implemented as explicit uploads behind local validation, preview, confirmation, registration, hosted maintainer review, and signed approved/published distribution.
- Enterprise Skill Lock is implemented as an opt-in local policy MVP. Managed hosted policy sync client behavior is implemented and verified against a fixture contract; production private-registry endpoint delivery remains an in-review private registry dependency for the v0.3 alpha stack. SSO, SCIM, live billing, hosted payment provider integration, organization administration, hosted dashboard controls, and broad enterprise private-registry enforcement are not implemented in this alpha.
- Warm daemon mode is experimental and binds to `127.0.0.1` by default; do not expose it on public interfaces.
- Private team packs are an alpha registered/entitled flow. Production access depends on the private registry distribution, publishing, admin, and entitlement PRs being accepted and deployed.
- The GitHub clone is the v0.3.5-alpha distribution path because repo assets are required. PyPI packaging is not the supported alpha install path yet.
- Registry signing status remains release-owner controlled until the release owner confirms production signing or records an explicit override.

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
