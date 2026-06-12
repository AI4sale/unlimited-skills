# MCP signed profile bundle incident runbook (E18)

Status: prototype (v0.4.x). Operator recovery procedures for every
fail-closed incident class of the signed-bundle machinery
([mcp-signed-profile-bundles.md](mcp-signed-profile-bundles.md)) and the
managed trust store ([mcp-trust-store.md](mcp-trust-store.md)).

Every procedure in this runbook is REHEARSED by the fixture-mode drill:

```
python scripts/run-mcp-bundle-incident-drill.py [--json] [--out DIR] [--scenario NAME|all]
```

For each scenario the drill builds a known-good fixture (ephemeral keys, a
signed bundle, an E15 managed trust store) inside a private temp directory,
injects the incident, asserts the exact fail-closed refusal code from the
REAL E14 verification, then executes the recovery steps below and proves
verification works again. Exit 0 only when every scenario both refuses
correctly AND recovers; the JSON report validates against
`schemas/mcp-incident-drill-report.schema.json` (generated example:
`examples/mcp/incident-drill-report.example.json`). The drill is offline and
self-contained: no network, no telemetry, no subprocess, and it never
touches the real library root, managed trust store, or audit log. Signing
uses the optional `cryptography` package (real Ed25519) when installed,
otherwise a clearly-marked TEST-ONLY fake backend keeps the refusal and
recovery paths exercised.

## How to read an incident

The gateway is **fail-closed refuse-all** for every bundle incident: it
keeps serving the meta-tools and refuses every call with one reserved code.
There is never a silent fallback to unsigned or open behavior, so the FIRST
diagnostic step is always the same:

1. read the refusal code and message (every refusal names its step), and
2. confirm it in the audit log: `unlimited-skills mcp audit-report`
   ([mcp-audit-inspector.md](mcp-audit-inspector.md)) shows the refusals
   and the failed `profile_loaded` startup row naming the failing step.
3. before re-applying any fix, dry-run it:
   `unlimited-skills mcp profiles rollout-plan|doctor`
   ([mcp-profile-rollout.md](mcp-profile-rollout.md)) shows the exact
   verification outcome WITHOUT restarting the gateway.

Verification runs once at startup; **restart is the re-verification
procedure** after every recovery below.

## Incident catalogue

| Drill scenario | Refusal code | Name |
| --- | --- | --- |
| `bad_signature` | `-32015` | `bundle_signature_invalid` |
| `unknown_key` | `-32019` | `bundle_key_missing` |
| `expired_key` | `-32019` | `bundle_key_missing` (E14 mapping: expired = missing) |
| `expired_bundle` | `-32016` | `bundle_expired` |
| `revoked_bundle` | `-32017` | `bundle_revoked` |
| `crl_outage` | `-32017` | `bundle_revoked` (fail-closed on unprovable status) |
| `wrong_audience` | `-32018` | `bundle_audience_mismatch` |
| `operator_rollback` | `-32015` (trigger) | rollback while the bundle is fixed |
| `trust_store_recovery` | `-32019` | store corruption, detect + rebuild |

### bad_signature -- tampered or corrupted bundle (`-32015`)

- **Symptoms**: every call refused with `-32015`
  `bundle_signature_invalid`; the audit `profile_loaded` row (ok: false)
  names `bundle_signature_invalid`. A stripped signature under
  `--require-signed-profiles` produces the SAME code (stripping gains
  nothing over tampering).
- **Containment**: treat the bundle file as hostile until proven otherwise
  -- quarantine it for forensics; do NOT weaken policy to get unblocked
  (see `operator_rollback` for the sanctioned fallback).
- **Recovery**: obtain or re-issue a correctly signed bundle -- the issuer
  re-signs the intended document with a trusted key -- and restart the
  gateway against it.
- **Verify**: `mcp profiles rollout-plan --bundle ...` shows verification
  OK; after restart the `profile_loaded` audit row reads
  `verification: verified`.
- **Prevention**: distribute bundles over channels with integrity checks;
  alert on any `-32015` (it is either corruption or an attack, never
  routine).

### unknown_key -- signing key not trusted locally (`-32019`)

- **Symptoms**: `-32019` `bundle_key_missing`, message naming the unknown
  `key_id`. Typical after an issuer rotation that was not propagated.
- **Containment**: none needed -- nothing was trusted. Confirm OUT OF BAND
  (not from the bundle itself) that the new key is legitimate.
- **Recovery**: import the new PUBLIC key:
  `unlimited-skills mcp trust import --key-id <id> --public-key <base64
  public key> [--not-after <deadline>]` (or `--key-file`); restart.
- **Verify**: `mcp trust list` shows the key `active`; verification
  succeeds.
- **Prevention**: issuers announce rotations ahead of time; import the new
  key during the overlap window (multiple active keys ARE the rotation
  mechanism).

### expired_key -- key past its local trust deadline (`-32019`)

- **Symptoms**: `-32019` naming the key's lapsed `not_after`;
  `mcp trust doctor` warns while it approaches and flags
  expired-but-not-rotated stores as problems.
- **Recovery**: rotate -- import the NEW public key under a NEW `key_id`,
  have the issuer re-sign bundles with it, restart; remove the expired
  entry after the overlap window.
- **Prevention**: run `mcp trust status` / `doctor` periodically; the
  `expiring_soon` state (default 30 days) is the rotation reminder.

### expired_bundle -- outside the signed validity window (`-32016`)

- **Symptoms**: `-32016` `bundle_expired`, message printing the signed
  window. Also raised for not-yet-valid bundles (one code by design).
- **Containment**: check the HOST CLOCK first -- a skewed clock fakes this
  incident (and ±300 s skew is already tolerated).
- **Recovery**: request a re-issued bundle with a fresh
  `issued_at`/`expires_at` window; restart against it.
- **Prevention**: track `expires_at` from the `profile_loaded` audit row
  and re-issue before expiry; short windows are a feature (stale-bundle
  replay defense), not a bug to engineer away.

### revoked_bundle -- bundle or key in the local CRL (`-32017`)

- **Symptoms**: `-32017` `bundle_revoked` (by bundle SHA-256 or by
  `key_id`; a revoked KEY kills every bundle it signed).
- **Containment**: revocation IS the containment. To revoke:
  `unlimited-skills mcp trust revoke --bundle-sha256 <hash> --reason <why>`
  or `--key-id <id>`. The CRL is append-only; history is never deleted.
- **Recovery**: issue a corrected bundle -- new bytes mean a new SHA-256,
  so the CRL entry keeps refusing only the withdrawn artifact. For a
  revoked key: rotate (see `expired_key`) and re-sign.
- **Verify**: the corrected bundle verifies; the revoked one still refuses
  (the drill asserts both).
- **Prevention**: record reasons with every revocation (`--reason` lands in
  the store metadata history); never "un-revoke" by editing the CRL.

### crl_outage -- declared CRL unreadable (`-32017`, fail-closed)

- **Symptoms**: `-32017` with "declared CRL file is missing or unreadable"
  -- the bundle DECLARES a CRL that cannot be read, and "cannot prove
  not-revoked" never degrades to "trusted" (threat 18).
- **Containment**: do not delete the `revocation` member from the bundle to
  get unblocked -- that is a signature break (`-32015`) and the wrong fix.
- **Recovery**: restore the CRL file -- from backup, or re-create it from
  the append-only revocation history in the store metadata sidecar
  (`trust-metadata.json` records every revocation with timestamps).
  `unlimited-skills mcp trust doctor` flags the unreadable CRL (exit 1)
  and confirms the repair (exit 0); then restart.
- **Prevention**: keep the CRL inside the managed store (atomic writes);
  include the store directory in local backups.

### wrong_audience -- bundle issued for someone else (`-32018`)

- **Symptoms**: `-32018` `bundle_audience_mismatch`; the message names BOTH
  sides (the bundle's signed audience and the local identifiers), so the
  diagnosis is in the refusal itself. Also raised when a profile rule
  escapes `allowed_upstream_namespaces` (the namespace ceiling).
- **Recovery**: fix the consumer's own identifier (`--audience-id`, or the
  `UNLIMITED_SKILLS_MCP_AUDIENCE` env var) when this host legitimately
  belongs to the audience -- or obtain the bundle actually issued for this
  team/org/host. For ceiling violations the ISSUER must fix and re-sign;
  there is no consumer-side override.
- **Prevention**: bake audience identifiers into provisioning, not shell
  history; one bundle per audience, never a shared "fits everyone" bundle.

### operator_rollback -- controlled fallback while the bundle is fixed

- **Symptoms**: any bundle incident above has the gateway fail-closed
  (refuse-all) and the fix needs time (issuer unavailable, key ceremony
  pending).
- **Recovery (rollback)**: restart the gateway with `--profiles <local
  file>` and WITHOUT `--profile-bundle` -- the raw E10 path keeps
  enforcing profiles. **What is lost during rollback**: signed provenance
  in audit rows, the audience binding, the namespace ceiling, and the
  `--require-signed-profiles` policy (it would refuse the unsigned source
  with `-32015`, so it must be dropped for the rollback window). The last
  resort is open no-profiles mode (no profile flags), which loses ALL
  profile enforcement -- record that decision and time-box it.
- **Verify**: the `profile_loaded` audit row shows `profile_source:
  raw_file` (or no profile fields in open mode) -- rollback leaves
  evidence by design.
- **Prevention**: keep a reviewed local fallback profile file ready (it can
  be the narrow-only override file already deployed next to the bundle);
  restore the signed bundle as soon as the re-issue lands.

### trust_store_recovery -- corrupted managed store (`-32019`)

- **Symptoms**: `-32019` `bundle_key_missing` with a malformed trusted-keys
  message; `unlimited-skills mcp trust doctor` reports the broken file and
  exits 1.
- **Recovery**: remove the corrupt `trusted-keys.json` and REBUILD through
  the real import path -- `unlimited-skills mcp trust import ...` for every
  known public key (atomic write + strict round-trip validation), then
  `mcp trust doctor` (exit 0) and restart. Never hand-edit the store files
  back to life.
- **Prevention**: store writes are already atomic (temp file + replace);
  corruption usually means disk trouble or an external editor -- keep the
  store out of hand-edit workflows and in backups.

## What the drill proves (and what it cannot)

The drill proves the refusal codes, the fail-closed behavior, the recovery
mechanics, and the audit evidence (it runs the E11 inspector over its own
redacted audit log and requires every expected code plus a passing
redaction self-check). It cannot rehearse the organizational parts --
issuer key ceremonies, out-of-band key fingerprint confirmation, who may
approve open-mode rollback -- which is exactly what this runbook adds on
top. Run the drill after any change to the bundle, trust-store, or audit
machinery; `tests/test_mcp_incident_drill.py` runs it in CI and keeps this
runbook's scenario and code lists honest.

## Non-goals

Unchanged from E13/E14/E15: no private keys in the consumer core (the drill
generates EPHEMERAL fixture keys in a temp directory and discards them), no
PKI, no network fetch, no registry sync, no hosted calls, no telemetry, no
hot reload.
