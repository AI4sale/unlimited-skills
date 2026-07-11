# Unlimited Skills

Unlimited Skills is a local-first skill memory and retrieval layer for coding
agents. It keeps large skill libraries out of the agent context and retrieves
the small, relevant skill context only when it is useful.

This is `v0.6.6` of the free MIT local core. There is no telemetry, no hosted
dependency for local use, and nothing for sale in this release. The project is
still pre-1.0, so APIs and JSON output may change before `1.0`.

Use `unlimited-skills==0.6.6` or newer after this release is published. The
`0.6.0` package was uploaded to PyPI but was not tagged or released because the
published verifier caught a CLI contract issue after upload.

## Install

```bash
pip install unlimited-skills
unlimited-skills quickstart
```

To avoid earlier uploaded-but-not-current artifacts explicitly, pin the
accepted v0.6 alpha floor:

```bash
pip install --upgrade "unlimited-skills>=0.6.6"
```

For hybrid/vector search:

```bash
pip install "unlimited-skills[vector]"
unlimited-skills vector-reindex
```

## What Quickstart Proves

`unlimited-skills quickstart` is the first-value path for a clean install:

- imports the bundled ECC and Superpowers packs when your local library is
  empty;
- indexes the local skill library;
- runs a first search so you can see retrieval working;
- measures local MCP context savings when a Claude Code config is available;
- prints local next steps without uploading prompts, schemas, configs, or
  skill bodies.

The package smoke for this release verifies the wheel in a fresh virtual
environment: `unlimited-skills --version`, `quickstart`, `suggest`,
`mcp savings`, `feedback prepare`, `learning-summary --events`, and
`roi receipt` all run from the installed package. The v0.6.6 package smoke also
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
- No paid, hosted, Team, Pro, Business, or Enterprise feature is required for
  local search, quickstart, suggestion, indexing, or MCP savings.
- Hosted/registered catalog and team surfaces are early alpha paths documented
  in the repository; they are not required for the local core.

## Useful Links

- Repository: https://github.com/AI4sale/unlimited-skills
- Quickstart docs: https://github.com/AI4sale/unlimited-skills/blob/main/docs/quickstart.md
- Feedback guide: https://github.com/AI4sale/unlimited-skills/blob/main/docs/feedback.md
- Known limitations: https://github.com/AI4sale/unlimited-skills/blob/main/docs/releases/v0.5.0-alpha-known-issues.md
- Security policy: https://github.com/AI4sale/unlimited-skills/blob/main/SECURITY.md
