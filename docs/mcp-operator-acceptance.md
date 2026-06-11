# MCP profile stack: end-to-end operator acceptance suite

`scripts/run-mcp-operator-acceptance.py` is a fixture-only acceptance suite
proving that the whole MCP profile stack works as ONE operational workflow.
It composes the existing layers -- the E19 publisher ceremony, the E15
managed trust store, the E14 verification, the E20 bundle library, the E16
rollout simulator, the E17 audit replay, the real gateway profile
resolution, and the E11 audit inspector -- into a single 12-step flow with
shared state, executed by the REAL modules end-to-end (no mocks, no
reimplementations).

This document doubles as the operator onboarding story: the 12 steps below
are exactly the lifecycle a new operator walks through when adopting signed
profile bundles, in the same order and with the same commands.

## How to run it

```
python scripts/run-mcp-operator-acceptance.py [--json] [--out DIR] [--step NAME|all]
```

- Exit code 0 only when every selected step passes; 1 when a step fails
  (the workflow stops at the first failure); 2 for a usage error or a
  missing `cryptography` package (the E19 publisher has no fallback
  signature scheme, so the suite refuses to run without real Ed25519).
- `--json` prints the machine report
  (`schemas/mcp-operator-acceptance-report.schema.json`); the default is a
  human text rendering. `--out DIR` writes both as
  `operator-acceptance-report.json` / `.txt`.
- `--step NAME` runs the workflow up to and including NAME. Earlier steps
  are prerequisites of the one shared flow, so they run too and stay in the
  report -- the suite is one workflow, not twelve independent checks.
- Everything happens inside a private temp directory that is removed
  afterwards. The run is deterministic apart from `generated_at` and the
  per-step durations (the only wall-clock-dependent fields); the workflow's
  verification clock is pinned once at start.

A generated example lives at
`examples/mcp/operator-acceptance-report.example.json`;
`tests/test_mcp_operator_acceptance.py` runs the suite in CI, validates the
report against the schema, and leak-greps every string in the report and
the stdout.

## The 12-step operator story

Each step runs the real machinery the named CLI command wraps and asserts
the operator-visible outcome.

1. **keygen** -- the publisher generates a DEV Ed25519 keypair
   (`unlimited-skills mcp bundle keygen`). The private key exists only in
   the keygen out directory; the public half is emitted in the trust-store
   import format.
2. **trust_import** -- the consumer imports the PUBLIC key into the E15
   managed trust store (`unlimited-skills mcp trust import --key-file ...`)
   and starts an empty local CRL. The store refuses anything that looks
   like private material.
3. **publish** -- the E19 signing ceremony turns the raw team profile file
   into two signed bundles, `team-v1` and `team-v2` (v2 records v1 as its
   rollback predecessor via `--previous`). The ceremony's post-package
   self-check runs the REAL E14 verification before a signed bundle ever
   gets its final name.
4. **verify** -- a standalone `unlimited-skills mcp bundle verify` over the
   published bundle against the trust store: signature, validity window,
   revocation, audience, namespace ceiling.
5. **library_add** -- both bundles are installed into the E20 bundle
   library (`unlimited-skills mcp profiles library add`), which verifies
   through the real E14 path BEFORE storing (no quarantine mode) and stores
   immutable, content-addressed copies.
6. **rollout_plan** -- the E16 dry-run (`unlimited-skills mcp profiles
   rollout-plan`) simulates the rollout over a what-if tool fixture: under
   the bundle's `dev` profile, the two `fake.*` tools stay visible and
   callable, the `legacy.export` tool is hidden, and the plan has no
   blockers. Nothing is spawned, nothing is written.
7. **replay_audit** -- the E17 replay (`unlimited-skills mcp profiles
   replay-audit`) re-evaluates a synthetic HISTORICAL audit log (written
   through the real redacted writer) against the proposed bundle. It
   catches that the historically-used `legacy.export` would become newly
   denied and recommends `safe_with_warnings` -- under the 20% block
   threshold, so the rollout may proceed with eyes open.
8. **activate** -- the library activates `team-v1` (the earlier known-good
   rollout) and then `team-v2` (the current one), re-verifying each at
   activation time and copying the verified bytes to `active.bundle.json`
   atomically. The append-only history this builds powers step 11.
9. **gateway_resolve** -- the REAL gateway startup resolution
   (`commands.mcp._resolve_gateway_profile_state`) resolves the active
   pointer under `--require-signed-profiles` into an enforced
   `ActiveProfile` (`dev`): `fake.echo` callable, `legacy.export` hidden,
   provenance pinned to the active bundle's SHA-256.
10. **incident_drill** -- the active bundle is withdrawn through the
    managed store's append-only CRL (`unlimited-skills mcp trust revoke
    --bundle-sha256 ...`). The library's activation re-verify refuses with
    `-32017 bundle_revoked`, and the stale active pointer fails CLOSED at
    the next gateway start (the gateway re-runs the full verification
    itself). The refusal is recorded through the real redacted audit
    writer.
11. **rollback** -- `unlimited-skills mcp profiles library rollback` walks
    the activation history back to the prior good bundle (`team-v1`),
    re-verifies it, and restores the pointer; the gateway resolves it again
    under the same signed-required policy. The workflow is operational once
    more.
12. **audit_report** -- the E11 inspector (`unlimited-skills mcp
    audit-report`) over the run's own audit log proves the incident is
    visible to operations: the `-32017` refusal appears in the refusal
    breakdown and the redaction self-check passes.

## What the suite proves

- The layers COMPOSE: the artifact each step hands to the next (key file,
  signed bundle, library entry, active pointer, audit rows) is accepted by
  the real consumer of that artifact, with no glue code beyond the
  operator's own commands.
- Verification is one path: publish self-check, standalone verify, library
  add/activate/rollback, and the gateway all go through the same
  `resolve_bundle_state`, and a revocation made in step 10 is honored by
  every later consumer.
- Fail-closed is real: after the revocation, both the library and the
  gateway refuse with the exact reserved code (`-32017`), and the refusal
  is observable in the audit report.
- Rollback is real: the prior good bundle is restored from the library's
  append-only history and the gateway runs again -- still signed, still
  audience-bound, still under `--require-signed-profiles`.

## What is intentionally NOT covered

The suite is fixture-only and inherits every boundary of the layers it
composes. There are **no production signing keys** (DEV ephemeral keys
only, generated per run and discarded with the temp directory),
**no registry sync**, **no hosted anything** (no hosted gateway, no
hosted calls), **no OAuth upstreams**, **no MCP resources or prompts**,
no network, no telemetry, and no hot reload. It also does not rehearse the
organizational parts -- key ceremonies, out-of-band fingerprint
confirmation, rollback approval -- which belong to
[mcp-incident-runbook.md](mcp-incident-runbook.md).

## Relationship to the other harnesses

The incident drill (`scripts/run-mcp-bundle-incident-drill.py`,
[mcp-incident-runbook.md](mcp-incident-runbook.md)) goes DEEP on failure:
every documented incident class, refusal code, and recovery. This suite
goes WIDE on success: one healthy lifecycle across every layer, with a
single revocation incident (step 10) to prove the unhappy path composes
too. The per-layer docs remain the contracts:
[mcp-bundle-publishing.md](mcp-bundle-publishing.md),
[mcp-trust-store.md](mcp-trust-store.md),
[mcp-signed-profile-bundles.md](mcp-signed-profile-bundles.md),
[mcp-bundle-library.md](mcp-bundle-library.md),
[mcp-profile-rollout.md](mcp-profile-rollout.md),
[mcp-audit-replay.md](mcp-audit-replay.md),
[mcp-audit-inspector.md](mcp-audit-inspector.md).
