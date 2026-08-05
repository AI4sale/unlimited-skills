# Unlimited Skills

Unlimited Skills is governed skill infrastructure for AI agent fleets. Its
free MIT local core keeps large skill libraries out of standing context,
retrieves the relevant capability on demand, and security-gates supported
installation paths before skill files are copied.

This is `v0.6.9`, the stable pre-1.0 local core. Local use has no telemetry
or hosted dependency. Business and Enterprise Fleet are separate hosted
control-plane capabilities and are not required for local search or installs.

Use `unlimited-skills==0.6.9` for the stable security-gated Fleet client. The
`0.6.9rc12` candidate remains immutable release history.

## Install

```bash
pip install unlimited-skills
unlimited-skills quickstart
```

To avoid earlier uploaded-but-not-current artifacts explicitly, pin the
accepted v0.6 alpha floor:

```bash
pip install --upgrade "unlimited-skills>=0.6.9"
```

For hybrid/vector search:

```bash
pip install "unlimited-skills[vector]"
unlimited-skills vector-reindex
```

## Optional Local Business Context

An owner can configure a private local JSON-over-stdio adapter so card-mode
`suggest` returns the chosen skill plus cited business references. The public
package ships the bounded transport and policy boundary—not a company database,
credentials, or hosted dependency.

```bash
unlimited-skills context doctor --json
unlimited-skills context retrieve "current source-backed operating context" --json
```

Retrieved text is `retrieval_only`, treated as data rather than instructions,
and marked internal. `no_context` never means verified absence. The Claude Code
Stop hook never derives evidence from assistant prose. It only forwards an
explicit, bounded signed receipt supplied by a trusted host field or an
owner-controlled inbox. The private provider owns signature authentication,
acceptance, quarantine, idempotency, and durable writes.

## What Quickstart Proves

`unlimited-skills quickstart` is the first-value path for a clean install:

- imports the bundled ECC and Superpowers packs when your local library is
  empty;
- indexes the local skill library;
- runs a first search so you can see retrieval working;
- measures local MCP context savings when a Claude Code config is available;
- prints local next steps without uploading prompts, schemas, configs, or
  skill bodies.

The package smoke for v0.6.9 verifies the wheel in a fresh virtual
environment: `unlimited-skills --version`, `quickstart`, `suggest`,
`mcp savings`, `feedback prepare`, `learning-summary --events`, and
`roi receipt` all run from the installed package. The release smoke also
verifies retrieval precision and onboarding from a clean wheel install: weak
matches stay silent, mixed-language prompts request an English-keyword rescue,
quickstart completes missing bundled collections without touching local skills,
and the source release-gate verifier passes.

## Measured, Not Promised

Current release-gate measurements on the bundled library:

- skill retrieval eval: top-1 `0.933`, top-3 `0.967`, false positives `0`;
- MCP lab benchmark: `90,420` bytes of direct tool schemas versus `1,268`
  bytes behind the Unlimited Tools gateway.

Your local results depend on your installed skills and MCP servers. Run
`unlimited-skills mcp savings --json` to measure your own configuration.

## Local-First Boundaries

- No telemetry or automatic uploads.
- No skill execution by the library.
- No business provider is enabled by default. When explicitly configured, task
  queries and explicit signed completion receipts go only to that trusted local
  command.
- The Claude Code prompt hook may start the optional warm-search daemon on
  loopback; it never binds LAN/remote or uploads prompt data. Set
  `UNLIMITED_SKILLS_NO_AUTOSERVE=1` only for restricted runtimes.
- No paid, hosted, Team, Pro, Business, or Enterprise feature is required for
  local search, quickstart, suggestion, indexing, or MCP savings.
- Hosted Business and Enterprise Fleet capabilities are opt-in and separately
  operated; they are not required for the local core.

## Useful Links

- Repository: https://github.com/AI4sale/unlimited-skills
- Quickstart docs: https://github.com/AI4sale/unlimited-skills/blob/main/docs/quickstart.md
- Feedback guide: https://github.com/AI4sale/unlimited-skills/blob/main/docs/feedback.md
- Known limitations: https://github.com/AI4sale/unlimited-skills/blob/main/docs/releases/v0.5.0-alpha-known-issues.md
- Security policy: https://github.com/AI4sale/unlimited-skills/blob/main/SECURITY.md
