# MCP distribution fixture E2E harness (E26)

**Status: fixture-only test harness (E26) — NO hosted implementation.**
Branch lineage: `feat/v04-e26-mcp-distribution-fixture-e2e-harness-v1`, based
on `docs/v04-e25-mcp-distribution-threat-model-abuse-cases` (the full E13–E22
local stack + the E23 distribution design + the E25 threat model and
abuse-case test plan).

`python scripts/run-mcp-profile-distribution-fixture-e2e.py
[--fixture-mode] [--json] [--out DIR] [--step NAME|all]` executes ONE
end-to-end workflow proving that the planned registered/team distribution
flow — E23 channels/assignments
([mcp-bundle-distribution.md](mcp-bundle-distribution.md)) carried by the
E24 registry contract (private repo, modeled here) — **can be tested safely
before any production registry sync is implemented**. Exit 0 only when every
selected step passes; `--step NAME` runs the workflow prefix ending at NAME
(the harness is one flow with shared state, exactly the E21
`scripts/run-mcp-operator-acceptance.py` composition style —
[mcp-operator-acceptance.md](mcp-operator-acceptance.md)).
`scripts/verify-mcp-profile-distribution-e2e.py REPORT.json` is the thin
read-only verifier over the machine report.

Everything is offline by construction: no network, no hosted calls, no real
entitlement service, no production signing keys (ephemeral DEV Ed25519 keys
generated per run inside a private temp directory), no OAuth, no MCP
resources or prompts, no telemetry. The real library root, managed trust
store, and default audit log are never touched.

## What stands in for what

| Planned hosted piece (E24) | Fixture stand-in in this harness |
| --- | --- |
| Registry artifact storage (bundle bodies, channels, assignments) | A plain local DIRECTORY: content-addressed `bundles/<sha256>.bundle.json` opaque blobs, `channels/<owner_key_id>.<name>.channel.json` and `assignments/<label>.assignment.json` — the verbatim, inner-signed E23 files (`schemas/mcp-bundle-channel.schema.json`, `schemas/mcp-bundle-assignment.schema.json`). |
| Signed metadata summaries / listing surface | `summaries/<sha256>.summary.json` — a deliberately tiny field set (sha, issuer key id, audience SCHEMES, timestamps, size, status) signed by a fixture CARRIER key; bundle bodies, profile rules, and tool names are structurally absent. |
| `GET /v1/public-keys` carrier-trust bootstrap | `public-keys.json` in the fixture registry directory, holding the carrier's PUBLIC key only. The carrier key is deliberately NOT imported into the member's E15 trust store — carrier trust never becomes capability trust. |
| Entitlement resolution (`mcp_profile_sync`) | A fixture entitlement TABLE (`entitlements.json`): member id → audience identifiers + an allowed/denied feature decision. No plans, no billing, no accounts. |
| The download/access-check authorization chain | One fixture function implementing the E24 decision-4 chain in order: registered → entitled → matching unexpired assignment → sha reachable from that assignment (pin, channel current, or channel history for rollback fetches) → bundle not revoked. A nonexistent sha and an out-of-scope sha answer with the byte-identical anti-oracle code `unknown_or_unauthorized`. |
| Publish gates (decision 18) | Fixture put-functions that refuse unsigned channel/assignment uploads (`unsigned_artifact_rejected`), signature/owner key-id mismatches (`owner_key_mismatch`), and revision regression per channel identity (`revision_regression`). |

Everything CLIENT-side is the REAL stack, reused unchanged: the E19
publisher ceremony, the E15 trust store and CRL, the full E14 verification
(`resolve_bundle_state` — never reimplemented), the E20 library
(verify-before-store, activation pointer, append-only history, rollback),
the E16 rollout dry-run and E17 audit replay as pre-activation due
diligence, the real gateway startup resolution under
`--require-signed-profiles`, and the E11 audit inspector over the run's own
redacted audit log. Routing-file handling (strict loaders, signature
verification over the canonical JSON, the decision-6 conflict resolution,
per-identity revision watermarks) is implemented as fixture functions inside
the harness — the stand-in for the future client routing-resolution module.

## The 23-step flow

1–6 build the world: `keygen` (three ephemeral DEV keypairs: issuer,
other-owner, carrier) → `trust_import` (issuer + other-owner PUBLIC keys
into the E15 store; the carrier stays out) → `publish` (E19 ceremony:
`team-v1`, `team-v2`, plus an `other-team-v1` bound to a different
audience) → `registry_seed` (the fixture directory above) →
`channel_publish` (signed channel `stable`, revisions 1 then 2; an unsigned
publish attempt is refused) → `assignment_issue` (signed follow-mode
assignment for the team audience).

7–13 are the member's happy path: `entitlement_gate` (allowed / denied /
unknown member / anti-oracle; the denied member gets metadata only — the
body never moves; the SAME files delivered as plain local files verify with
zero entitlement consultation) → `client_fetch` (assignment resolution,
channel verification + identity pair + watermark, gated content-addressed
fetch of the current AND the prior history sha) → `client_verify` (real
E14) → `library_add` (E20 verify-before-store) → `rollout_replay` (E16/E17
due diligence BEFORE activation) → `activate` (v1 then v2) →
`gateway_resolve` (the real gateway resolves the routed bundle, enforced,
fail-closed posture intact).

14–22 are the abuse battery, each asserting the exact refusal and that
nothing moves: tampered channel and tampered assignment (signature
invalid), the unsigned-downgrade set (stripped channel/assignment under the
signed-distribution policy, unsigned summary, undeclared envelope key,
forbidden-field smuggling, a future `channel_version`), stale-revision
replay + channel-name squatting (full identity pair; independent
watermarks per identity), expired assignment (stops NEW activation only —
the active bundle keeps working; an injected clock past the BUNDLE expiry
then refuses `-32016` `bundle_expired`), wrong audience (misrouted
assignment ignored; forcing the foreign bundle refuses `-32018`
`bundle_audience_mismatch`), conflict resolution (every input permutation
deterministic per E23 decision 6; an engineered exact tie refused loudly
with both files named and the library state unchanged), a poisoned active
pointer (gateway startup re-verification refuses `-32015`
`bundle_signature_invalid`), and the revoked-bundle incident: the member's
CRL revokes the routed sha while the channel STILL marks it active —
activation refuses `-32017` `bundle_revoked` (channel statuses are
demonstrably never a trust input), the gateway fails closed, and the E20
rollback walks back to the last-good bundle WITH THE CARRIER OFFLINE (the
fixture registry directory is renamed away during recovery). Incident
semantics are exactly the E18 runbook's
([mcp-incident-runbook.md](mcp-incident-runbook.md)).

23 is `audit_report`: the E11 inspector over the run's own audit log proves
the refusal codes `-32015`, `-32016`, `-32017`, `-32018` are visible to
audit reporting and the redaction self-check passes.

## Report and verifier

The `--json` report validates against
`schemas/mcp-distribution-e2e-report.schema.json` (draft 2020-12; generated
example `examples/mcp/distribution-e2e-report.example.json`). Per step:
name, ok, key facts, duration, and the E25 `ABT-*` ids the step covers;
`abt_coverage` is the sorted union. Facts carry names, SHA-256 PREFIXES,
counts, refusal codes/reasons, statuses, and basenames only — never key
material, signature values, full hashes, argument values, or local paths
(test-enforced leak-grep with the audit writer's own heuristics).

`scripts/verify-mcp-profile-distribution-e2e.py` re-checks one report:
schema validity, all 23 steps ok (a prefix run fails the verifier — it
gates the FULL flow), non-empty ABT coverage equal to the union of per-step
claims, NO forbidden field per the E24 decision-20 denylist (encoded
locally in both scripts; the private contract is never read at run time),
and the leak-grep. Exit 0 verified / 1 findings / 2 usage.

## ABT traceability

The E25 plan ([mcp-distribution-abuse-test-plan.md](mcp-distribution-abuse-test-plan.md))
assigns each abuse test an owner. This harness is the designated
**end-to-end (E21-style)** owner and also exercises client-suite cases that
compose naturally into the flow; for REGISTRY-owned ids it provides a
fixture MODEL of the contract behavior, not the registry implementation —
those ids still land in the private registry suite with the real code.
`tests/test_mcp_distribution_e2e.py` asserts every claimed id exists in the
plan document.

| ABT id | Harness step | Status here |
| --- | --- | --- |
| ABT-01a | abuse_tampered_channel, abuse_tampered_assignment, abuse_unsigned_downgrade | covered (client-owned; tampered AND stripped routing files refused under the signed-distribution policy) |
| ABT-02b | abuse_unsigned_downgrade | modeled (the inner-signature-required wrap rule; the vendored-envelope parse stays with the client suite against the E24 examples) |
| ABT-03b | rollout_replay | covered in ordering (full surface reported BEFORE activation); the hostile-but-valid bundle variant stays with the client suite |
| ABT-04a | abuse_stale_replay, abuse_expired_assignment | covered (client-owned: revision regression refused; expired assignment directs no new activation) |
| ABT-05a | abuse_revoked_rollback | covered (client-owned: the lying channel never overrides the CRL) |
| ABT-06a | abuse_expired_assignment | covered (e2e-owned: no liveness dependency; injected clock past expiry refuses) |
| ABT-06b | abuse_revoked_rollback | covered (client-owned: CRL lands, next activation refuses) |
| ABT-08a | abuse_stale_replay | covered (client-owned: same-named other-owner channel never satisfies the assignment) |
| ABT-09a | abuse_wrong_audience | covered (client-owned: misrouted assignment ignored; the bundle's own audience binding refuses) |
| ABT-10a, ABT-10b | abuse_conflict_resolution | covered (client-owned: permutation-invariant total order; loud tie refusal) |
| ABT-12b | abuse_unsigned_downgrade | covered (client-owned: strict loader refuses undeclared keys and denylisted fields) |
| ABT-13a | entitlement_gate | modeled (registry-owned anti-oracle: byte-identical answers in the FIXTURE access-check) |
| ABT-14a | entitlement_gate | modeled (registry-owned entitlement denial in the FIXTURE table; no bytes move) |
| ABT-14b | entitlement_gate | covered (client-owned: local files verify with zero entitlement consultation) |
| ABT-19a | abuse_poisoned_pointer | covered (client-owned: tampered pointer copy never governs) |
| ABT-20b | abuse_revoked_rollback | covered (e2e-owned: rollback recovery entirely from local library state, carrier offline) |
| ABT-22a | abuse_unsigned_downgrade | covered (client-owned: future format versions are load errors) |
| ABT-23b | abuse_stale_replay | covered (client-owned: per-identity watermarks; same-identity regression refused, other-owner identity independent) |

Not exercised here (and deliberately so): every remaining registry-owned id
(`ABT-02a`, `ABT-04b`, `ABT-05b`, `ABT-08b`, `ABT-09b`, `ABT-11a/b`,
`ABT-12a`, `ABT-15a`, `ABT-16a/b`, `ABT-17a`, `ABT-20a`, `ABT-21a`,
`ABT-22b`, `ABT-23a`) needs the real registry validators/endpoints and
lands in the private repo's suite; the client-suite ids not composable into
one flow (`ABT-01b`, `ABT-03a`, `ABT-07a`, `ABT-18a`, `ABT-19b`) stay
individual pytest cases per the plan (several already run today via the E18
drill machinery).

## What this harness proves — and deliberately does NOT

Proves: the E23 file contracts, the E24 access-check semantics, and the
existing local stack COMPOSE — a signed channel/assignment can route a real
member through a gated carrier to a verified activation, every documented
abuse along that path refuses exactly as the threat model
([mcp-distribution-threat-model.md](mcp-distribution-threat-model.md))
requires, and the whole flow is testable with zero hosted infrastructure.

Deliberately NOT proven, because none of it exists and none of it is
implemented here:

- **no hosted calls and no network** — the registry is a directory; there
  are no endpoints, no HTTP, no sync client, no daemon;
- **no real entitlement service** — the entitlement table is a fixture
  file; plans, seats, tokens, and device proofs are not modeled
  (`not_registered` here is a table miss, not an authentication scheme);
- **no production keys** — DEV/FIXTURE keys only, generated per run,
  discarded with the temp directory (the standing E13/E15/E19 boundary);
- **no registry envelope wire format** — the E24 wrap schemas live in the
  private repo; this harness models their RULES (inner signature required,
  closed keys, forbidden fields) as fixture loader behavior;
- **no new refusal codes, no verifier/CLI/runtime changes** — the consumer
  core is composed, never modified; routing-file refusals carry fixture
  reason names, and the only numeric codes asserted are the unchanged
  reserved client codes.

## How the future implementation swaps in

The harness is organized around the same seams the hosted work will fill,
so each fixture piece can be replaced WITHOUT changing the steps around it:

- the `FixtureRegistry` put/list/access-check/fetch functions are the
  fixture twin of the E24 publish and consumer endpoints — the future
  client sync replaces "read a file from the directory" with "call the
  carrier", and every assertion downstream (verification, library,
  gateway, rollback) stays byte-identical because the files themselves are
  the contract;
- the routing-file loaders and the decision-6 resolution inside the
  harness are the specification of the future client routing-resolution
  module; when that module lands in `unlimited_skills/mcp/`, the harness
  imports it instead and the abuse battery becomes its regression suite;
- the fixture entitlement table is the stand-in for the registry's
  entitlement resolution; the access-check REASON-CODE vocabulary is
  already the E24 one, so client-side diagnostics built against this
  harness keep working against the real carrier;
- the per-step `abt` claims are the tracking mechanism: as real
  implementations land, modeled ids graduate to their owning suites and
  the harness keeps gating the composition.

## See also

- [mcp-bundle-distribution.md](mcp-bundle-distribution.md) — the E23
  channel/assignment design this harness exercises.
- [mcp-distribution-threat-model.md](mcp-distribution-threat-model.md) and
  [mcp-distribution-abuse-test-plan.md](mcp-distribution-abuse-test-plan.md)
  — the E25 threat catalogue and the ABT test plan traced above.
- [mcp-operator-acceptance.md](mcp-operator-acceptance.md) — the E21
  composition style the harness extends.
- [mcp-incident-runbook.md](mcp-incident-runbook.md) — the E18 recovery
  semantics the incident steps reuse.

## Managed sync client prototype (E27)

The promise above is now kept: the routing-file loaders, the strict
closed-schema and forbidden-field checks, the decision-6 conflict
resolution, and the carrier-summary loader live in
`unlimited_skills/mcp/managed_sync.py` (the fixture-only managed profile
sync client behind `unlimited-skills mcp profiles managed
sync|status|last-good|doctor`), and this harness imports them — the abuse
battery is their regression suite. The fixture-registry directory this
harness builds is byte-compatible with the sync client's `--source`
layout, so an operator can point `managed sync --source` at a harness-style
directory and walk the same flow interactively (dry-run by default; no
hosted calls, no network, no production keys; staging only — activation
stays the explicit E20 library step). See
[mcp-managed-sync.md](mcp-managed-sync.md).
