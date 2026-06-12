# MCP managed profile sync client (E27, fixture-only prototype)

**Status: PROTOTYPE (fixture mode only — no hosted sync exists or is
called).** `unlimited_skills/mcp/managed_sync.py` plus the
`unlimited-skills mcp profiles managed sync|status|last-good|doctor` CLI
are a local, fixture-only managed profile sync client: they simulate how a
future registered/team assignment would be **received, verified, stored,
previewed, and optionally staged** into the local bundle library — without
real hosted sync, registry API calls, entitlement server calls, or
production signing keys. Everything is offline by construction: no
network, no hosted calls, no telemetry, no OAuth. The "registry" is a
plain local **fixture-source directory** in the E26 layout
([mcp-distribution-e2e-harness.md](mcp-distribution-e2e-harness.md));
anything URL-shaped refuses outright with *"hosted sync is not
implemented; design gated"* — the registered transport stays behind the
E23/E24 design gates
([mcp-bundle-distribution.md](mcp-bundle-distribution.md)).

Tests: `tests/test_mcp_managed_sync.py`. The E26 fixture E2E harness
(`scripts/run-mcp-profile-distribution-fixture-e2e.py`) imports this
module's routing loaders, conflict resolution, and carrier-summary loader
— its abuse battery is their regression suite, exactly as the harness doc
promised ("when that module lands in `unlimited_skills/mcp/`, the harness
imports it instead").

## Operator story

A team operator (or fleet tooling) drops a fixture-source directory —
produced today by the E19 ceremony plus the E23 channel/assignment files,
laid out like the E26 fixture registry — somewhere the member can read it
(git checkout, shared drive, USB stick). The member then:

```
# 1. Preview. DEFAULT IS DRY-RUN: verifies everything, mutates nothing.
unlimited-skills mcp profiles managed sync --source ./fixture-source \
    --audience-id team:core-ai4sale

# 2. Review the report: which assignment won, which channel revision,
#    which bundle WOULD be staged, watermark movement, drift.

# 3. Stage it. Adds the verified bundle to the E20 library and records
#    the sync state. STILL does not activate anything.
unlimited-skills mcp profiles managed sync --source ./fixture-source \
    --audience-id team:core-ai4sale --apply

# 4. Activate EXPLICITLY through the library, after your own review
#    (rollout-plan / replay-audit are the due-diligence tools).
unlimited-skills mcp profiles library activate managed-<sha-prefix>
```

`status`, `last-good`, and `doctor` close the loop:

- `managed status` — the recorded sync state, offline: source id and
  content fingerprint, per-channel revision watermarks, last sync result,
  the last-good bundle, **staged-but-not-activated** bundles, and drift
  ("the assignment now points at vX, you run vY").
- `managed last-good [--restore [--source DIR]]` — show the last-good
  bundle recorded by the sync history, re-verified through the real E14
  path; `--restore` re-stages it **through the real library add**
  (verify-before-store) when it is missing — verification is never
  bypassed, and activation stays the explicit library step. Exit 1 when
  none is recorded or it no longer verifies.
- `managed doctor [--source DIR]` — offline self-checks, exit 0/1: state
  file shape, sync-staged bundles still verify against the CURRENT trust
  store, drift report, and — with a source — watermark monotonicity
  against the source (replay detection) and assignment expiry warnings.

Common flags: `--library-dir` (E20 library), `--trusted-keys` (defaults to
the E15 managed store under the root), `--audience-id` (repeatable; this
member's `team:`/`org:`/`host:` identifiers), `--json` everywhere.

## What one sync pass does

`sync --source DIR` is one deterministic pass; with `--apply` it is the
only mutating step and every refusal leaves all state untouched:

1. **Refuse URLs.** A URL-shaped `--source` refuses with
   `source_url_rejected` before anything is read.
2. **Receive.** Read every `assignments/*.assignment.json` in the source
   and verify each one under the signed-distribution policy (E23
   decision 1): strict closed schemas, the E24 decision-20 forbidden-field
   denylist, a required Ed25519 signature whose `key_id` equals the
   issuer's, the key present/unexpired in the member's E15 trusted-keys
   file and not revoked by the local CRL. A tampered or unsigned routing
   file anywhere refuses the whole sync loudly.
3. **Resolve.** Apply the E23 decision-6 conflict resolution over the
   assignments matching the member's audience identifiers: `host:` beats
   `team:` beats `org:`, pin beats follow, then highest revision, then
   latest `issued_at`; a residual exact tie refuses with
   `assignment_tie` and names both files. Expired assignments direct no
   new staging (named loudly; the active bundle keeps working until its
   own expiry — E23 decision 5).
4. **Verify the channel + anti-rollback.** The winning assignment's
   channel (full identity pair: name + owner key id) is loaded and
   verified the same way; the channel `revision` is compared against the
   recorded **watermark** for that identity — a LOWER revision refuses
   the sync with `routing_revision_regression` (replay), state untouched.
5. **Carrier summary (metadata only).** The candidate sha's
   `summaries/<sha>.summary.json` must be carrier-signed (verified against
   the source's own `public-keys.json`, never the member's trust store —
   carrier trust is not capability trust), structurally body-free, and
   not carrier-marked `revoked`. Summaries grant nothing.
6. **Full E14 verification.** The candidate body from
   `bundles/<sha>.bundle.json` is content-address-rechecked and verified
   through the REAL `resolve_bundle_state` path against the member's
   trust store with the member's audience identifiers — any refusal
   carries its exact reserved code (`-32014`…`-32019`).
7. **Report (dry-run) or stage (`--apply`).** Dry-run reports what would
   change — new bundle to stage, watermark movement, drift — and writes
   nothing. `--apply` stages via the real E20 `add_bundle`
   (verify-before-store, idempotent on duplicate sha) and records the
   sync state file atomically. **Never activates** (below).

## No silent activation, ever

`sync --apply` stages; activation stays a separate, explicit
`mcp profiles library activate` step. The reason is the trust boundary,
not convenience: a sync client that activated on its own would let the
routing layer — the one layer an attacker on the transport can try to
manipulate (E23 threats 19–22) — flip a member's *enforcement* with no
human in the loop, and would turn every routing mistake (mis-scoped
audience, stale channel, fat-fingered pin) into an immediate fleet-wide
behavior change. Staging is reversible and inert; activation is the
capability decision, and it stays where E20 put it: an explicit operator
action that re-verifies at activation time, with the E16 rollout dry-run
and the E17 replay simulator as the due-diligence tools in between. No
flag weakens this; there is no `--activate`.

## Sync state file

`<library>/.unlimited-skills-managed-sync/state.json`, written atomically
(temp file + `os.replace`, the E15/E20 pattern) and ONLY on a successful
`--apply` — refusals and dry-runs never touch it. Contents, exhaustively:

```json
{
  "schema_version": 1,
  "source_id": "fixture-source",
  "source_hash": "<64-hex content fingerprint of the routing files>",
  "watermarks": { "stable@ai4sale-team-profiles-2026": 2 },
  "last_sync": {
    "at": "2026-06-12T00:00:00Z",
    "result": "ok",
    "assignment": "team-managed",
    "channel": "stable",
    "channel_owner_key_id": "ai4sale-team-profiles-2026",
    "channel_revision": 2,
    "bundle_sha256": "<64-hex>",
    "applied": true
  },
  "last_good_bundle_sha256": "<64-hex>"
}
```

Identifiers, hashes, and revisions only — never key material, rule text,
audit data, or local paths (`source_id` is the directory BASENAME;
`source_hash` is a SHA-256 over the sorted basename:hash inventory of the
routing files). **Watermark semantics:** `watermarks` maps each channel
identity (`name@owner_key_id` — the E23 identity pair, so a same-named
channel from another owner has an independent watermark) to the highest
revision ever applied; sync refuses to move DOWN and `doctor --source`
reports a source presenting a lower revision as a replay. The watermark
is the client half of E23 threat-20's mitigation; whether the registry
also enforces monotonicity server-side stays a deferred registry-side
decision.

## Refusal vocabulary

Fail-closed and loud, two layers, no new numeric codes:

- **Routing/sync layer — reason NAMES** (the E26 fixture vocabulary):
  `schema_invalid`, `forbidden_field_rejected`, `routing_unsigned`,
  `routing_signature_invalid`, `routing_key_missing`,
  `routing_key_revoked`, `routing_revision_regression`,
  `channel_identity_mismatch`, `unsigned_artifact_rejected`,
  `content_address_mismatch`, `assignment_tie`, `bundle_revoked` (the
  carrier-marked-revoked courtesy; authoritative revocation stays the E15
  CRL). Sync-client additions (still names, never numbers):
  `source_url_rejected` (hosted sync not implemented; design gated),
  `source_invalid` (not a directory in the E26 layout / missing body or
  summary), `channel_missing`, `audience_unconfigured`,
  `crl_unreadable`, `state_invalid`, `library_add_refused`.
- **Bundle verification — the unchanged reserved codes**, produced by the
  real E14 path and surfaced verbatim:

| Code | Name | Managed-sync occasion |
| --- | --- | --- |
| `-32014` | `profile_invalid` | the candidate bundle fails a static load check |
| `-32015` | `bundle_signature_invalid` | candidate tampered after signing |
| `-32016` | `bundle_expired` | candidate outside its signed validity window |
| `-32017` | `bundle_revoked` | candidate (or its key) in the local CRL |
| `-32018` | `bundle_audience_mismatch` | a misrouted assignment pins another team's bundle |
| `-32019` | `bundle_key_missing` | signing key absent from the member's trust store |

## What future hosted sync changes — only the transport

Per the E23/E24 designs, the hosted registered/team sync replaces exactly
one thing: "read a file from the fixture-source directory" becomes "call
the carrier". Everything else in this module is the contract the hosted
client must keep byte-identical: the routing-document verification, the
decision-6 resolution, the watermark anti-rollback, the metadata-only
carrier summary check, the full E14 verification with the member's own
trust store, the dry-run default, staging-without-activation, and the
state file. Entitlement gates the *carrier*, never verification — a
member who received the files by any transport can always use them. The
hosted work also inherits the E24 access-check semantics (anti-oracle
`unknown_or_unauthorized`, decision-18 publish gates) that the E26 harness
models as fixtures.

## Relationship to the E26 harness

`scripts/run-mcp-profile-distribution-fixture-e2e.py` proves the WHOLE
planned flow (publisher → fixture registry → entitlement gate → client →
library → gateway → abuse battery → audit) as one composition; this
module is the client slice of that flow turned into a real, reusable
runtime module. The harness now imports `verify_routing_document`,
`resolve_assignments`, `load_summary_document`, the forbidden-field
boundary, and `DistributionRefusal` from
`unlimited_skills/mcp/managed_sync.py`, so the harness's tampered/
unsigned/stale/squatting/conflict abuse steps regression-test the exact
code `mcp profiles managed sync` runs. The fixture-source directory the
sync client consumes IS the harness's fixture-registry layout — one
contract, two consumers.

## See also

- [mcp-bundle-distribution.md](mcp-bundle-distribution.md) — the E23
  channel/assignment design (conflict resolution, pin/follow, audience).
- [mcp-distribution-e2e-harness.md](mcp-distribution-e2e-harness.md) —
  the E26 fixture layout and end-to-end composition.
- [mcp-bundle-library.md](mcp-bundle-library.md) — the E20 library that
  staging and activation delegate to.
- [mcp-trust-store.md](mcp-trust-store.md) — the E15 trust anchor and CRL.
- [mcp-signed-profile-bundles.md](mcp-signed-profile-bundles.md) — the
  E13/E14 verification the candidate bundle must always pass.
