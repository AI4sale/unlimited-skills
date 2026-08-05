# Known Limitations

`v0.6.9` is a pre-1.0 release, not a production SLA. CLI and JSON contracts
covered by the frozen v0.6 verifier are protected inside the release line;
other APIs may still change before 1.0.

## Local retrieval

- The fast lexical path is optimized for English skill metadata. Native-language
  retrieval needs the optional `[all]` dependencies and a current vector
  sidecar (`unlimited-skills vector-reindex`).
- The Claude Code prompt hook keeps the loopback warm daemon running by
  default. Other hosts still need a manual daemon or their own lifecycle
  adapter. Restricted runtimes can set `UNLIMITED_SKILLS_NO_AUTOSERVE=1`.
- A newly launched embedding runtime may not answer the same prompt that
  started it. That prompt remains fail-open and receives an English-keyword
  rescue; later prompts use the warm daemon.
- If the optional server/vector runtime is absent or broken, automatic launch
  cannot repair packages in the background. Run `unlimited-skills doctor --fix`.
- The free daemon has no remote authentication. Autoserve is loopback-only; do
  not expose `unlimited-skills serve` to LAN or the public internet.
- Retrieval quality depends on skill names/descriptions and the indexed library.
  Use `reindex` after out-of-band file edits and `vector-reindex` after inventory
  or embedding-model changes.

## Agent integrations

- Enterprise Fleet runtime adapters use Claude Code `SessionStart`, Codex
  `SessionStart`, OpenClaw `agent:bootstrap`, and Hermes runtime evidence.
  Codex, OpenClaw, and Hermes have passed the current AI4SALE production
  pilot; Claude Code remains intentionally paused and outside that rollout.
- Codex user hooks must be explicitly reviewed and trusted. Production
  Enterprise rollout should use an organization-managed hook source; until the
  hook runs, Fleet truth remains `ACTIVATION_PENDING`.
- A newly provisioned OpenClaw internal hook may require a Gateway reload or
  restart for the installed OpenClaw version. `hooks info` proves
  configuration, not runtime activation.
- Codex and OpenClaw skills outside the adapter-owned subtree remain
  unmanaged. Fleet receipts describe only the signed managed inventory.
- Vellum AI remains migration-only; it does not have a full installer/router
  integration.
- Skill cards intentionally include the selected skill's body head at high
  confidence. Set `UNLIMITED_SKILLS_NO_INJECT=1` to keep NAME-only hints.
- Unlimited Tools MCP v1 remains local stdio: no OAuth upstreams, no MCP resources,
  no MCP prompts, and no hosted gateway.

## Learning and hosted surfaces

- The built-in learning loop records privacy-safe feedback and aggregates. An
  opt-in business-context provider may separately accept signed completion
  receipts, but the provider—not Unlimited Skills—owns cryptographic trust,
  completion judgment, entity/sensitivity policy, durable writes, quarantine,
  reindexing, and visibility proof.
- A configured provider is trusted owner code and receives the bounded task
  query or explicitly submitted signed receipt. The public transport cannot
  prove the adapter's business-wall or issuer-policy correctness; operators
  must review that policy.
- The bundled Stop hook cannot create a receipt. A trusted host/checker must
  supply one; otherwise Stop remains a no-op.
- Business and Enterprise Fleet is an opt-in hosted production pilot. Community
  catalog, billing-status, and Local Skill Hub surfaces remain pre-1.0 and may
  change. Registration is not required for local search, indexing, daemon,
  learning logs, quickstart, or MCP savings.
- Hosted clients must not upload prompts, source code, skill bodies, full local
  paths, environment values, tokens, private keys, or customer data. Community
  submission is the explicit exception for the selected submitted skill/pack.
- Full catalog distribution remains disabled. Local Skill Hub is allowlist-only;
  LAN binding requires explicit opt-in, active hub tokens, and normal network
  controls such as TLS/reverse proxy for serious deployment.
- Billing commands are diagnostics/status surfaces. The public client does not
  create charges, checkout sessions, invoices, refunds, or collect payment data.

Historical milestone-specific restrictions remain in `docs/releases/` and are
not statements about the current PyPI distribution path. Compatibility
verifiers still recognize these historical anchors:

- v0.4 cross-repo readiness;
- v0.4 go/no-go;
- v0.4.0-alpha E01-E04 integration.

Those anchors prove the old release evidence, not current product status.
