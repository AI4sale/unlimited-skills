# MCP profile bundle publishing ceremony (E19, local-only)

Status: implemented (`unlimited_skills/mcp/bundle_publisher.py`,
`unlimited-skills mcp bundle keygen|publish|verify`,
`tests/test_mcp_bundle_publisher.py`).

A local, fixture-safe signing/publishing workflow that turns a raw MCP tool
profile (the E09/E10 format, `docs/mcp-permissioned-tool-profiles.md`) into
a SIGNED profile bundle package (the E13/E14 format,
`docs/mcp-signed-profile-bundles.md`) with a manifest, provenance, a
validation report, and rollback metadata:

```
raw profile -> validate -> sign -> package -> verify -> handoff bundle
```

Everything runs on the local machine. There are **no production keys, no
hosted calls, no registry sync, and no private-key leakage** -- by
construction, not by convention:

- **DEV/FIXTURE keys only.** `keygen` produces Ed25519 keypairs clearly
  marked `DEV KEY -- do not use in production`, for local ceremonies, test
  fixtures, and team pilots. Generating, requesting, transporting, or
  storing PRODUCTION signing keys is explicitly OUT OF SCOPE of this tool
  and of the consumer core (the E15 non-goal stands: issuing for
  registered/business distribution happens outside this repo).
- **The real verification path.** The `verify` subcommand and the automatic
  post-package self-check inside `publish` run the REAL E14 verification
  (`resolve_bundle_state` in `unlimited_skills/mcp/bundles.py`) -- never a
  reimplementation, never a bypass. Canonicalization is the normative
  `canonical_bundle_bytes` (sorted keys, no insignificant whitespace, minus
  `signature`), reused from the verifier.
- **Private-key hygiene.** The private key exists ONLY in the keygen
  `--out` directory. Its bytes never appear in the bundle, the manifest,
  the validation report, the rollback metadata, stdout, stderr, logs, or
  audit rows; command output carries paths, abbreviated fingerprints, and
  SHA-256 hashes only. The E15 trust store refuses to import the private
  file (its private-material heuristics fire on the keygen format).
- **Offline.** No network, no telemetry, no subprocess.

## The ceremony, step by step

### 1. keygen -- a DEV keypair

```
unlimited-skills mcp bundle keygen --out ./dev-keys --key-id team-dev-2026 [--display NAME] [--force] [--json]
```

Requires the optional `cryptography` package (real Ed25519); refuses with a
clear message when it is absent -- there is no fallback signature scheme.
Writes exactly two files into `--out` (refusing collisions without
`--force`):

- `<key_id>.signing-key.json` -- the PRIVATE key, with a loud
  `# DEV KEY -- do not use in production` header and best-effort
  restrictive permissions (`0600`; advisory on Windows). This file never
  leaves this directory: never import it, never commit it, never share it.
- `<key_id>.public-key.json` -- the PUBLIC key in the
  `mcp trust import --key-file` format, ready for step 2.

Key material is never printed; the command reports paths and the
abbreviated SHA-256 fingerprint only.

### 2. trust import -- hand the PUBLIC key to the store

```
unlimited-skills mcp trust import --key-file ./dev-keys/team-dev-2026.public-key.json
```

Consumers (and the publisher's own machine, for the verify step) trust the
PUBLIC half through the managed E15 store (`docs/mcp-trust-store.md`).
Attempting to import the `.signing-key.json` file is refused loudly before
any write.

### 3. publish -- validate, sign, package, self-check

```
unlimited-skills mcp bundle publish \
  --profiles team-profiles.json \
  --signing-key ./dev-keys/team-dev-2026.signing-key.json \
  --issuer-key-id team-dev-2026 \
  --audience team:reviewers [--audience host:ci] \
  [--expires-days 30] [--namespaces fake.*] [--out ./dist] [--name team] \
  [--display NAME] [--previous FILE|SHA256] [--crl-path /abs/crl.json] \
  [--dry-run] [--force] [--json]
```

The pipeline, in order (the first failure refuses the whole ceremony with
exit 1 and leaves NOTHING signed behind):

1. **validate** -- the raw profile runs through the REAL E09/E10 loader
   (`load_profile_document`): shape, rule grammar, extends chains, callable
   coverage. E09/E10 errors are surfaced verbatim.
2. **sign** -- the bundle document is built (embedded profiles, issuer,
   the mandatory non-empty audience, the validity window `now ..
   now + --expires-days`, `allowed_upstream_namespaces` -- explicit rules
   or whole-upstream rules derived from the profile map, with every profile
   rule checked against the ceiling BEFORE signing -- and the optional
   `revocation.crl_path` pointer slot) and signed with a detached Ed25519
   signature over the canonical JSON.
3. **package** -- four files land in `--out` atomically (temp file +
   `os.replace`; collisions refuse without `--force`):
   - `<name>.bundle.json` -- the signed bundle;
   - `<name>.MANIFEST.json` -- bundle SHA-256, issuer key id and
     fingerprint, created/expires timestamps, source profile SHA-256,
     profile and rule counts, publisher version, the DEV-key warning;
   - `<name>.VALIDATION-REPORT.json` -- every check the ceremony ran and
     the E14 verification outcome;
   - `<name>.ROLLBACK.json` -- the previous bundle SHA-256 (when
     `--previous` is given: a 64-hex SHA-256 or the path of the previous
     bundle file), the EXACT revoke command
     (`unlimited-skills mcp trust revoke --bundle-sha256 <sha>`), and the
     rollback steps.
4. **verify (self-check)** -- the packaged BYTES are verified through the
   REAL E14 path against an ephemeral trusted-keys file holding the PUBLIC
   key only, BEFORE the signed bundle gets its final name. A failing
   self-check fails the ceremony: the temp file is removed and no signed
   bundle remains.

`--dry-run` performs every step -- including the E14 self-check against a
private temp copy -- but writes NOTHING to `--out`; it reports what WOULD
be produced (artifact names, the would-be bundle SHA-256, every check).

Refusals (all loud, exit 1, nothing signed written): invalid profile
(E09/E10 errors surfaced), missing/unreadable signing key, a key file that
looks PUBLIC-only (the keygen public file or a trusted-keys file), an
issuer key-id that does not match the signing key, `--expires-days < 1`
(a window expiring in the past, or inverted), an empty or malformed
audience, namespace rules violating the E09 rule grammar, profile rules
outside the namespace ceiling, out-dir collisions without `--force`, and a
missing `cryptography` package.

### 4. verify -- the consumer-side check

```
unlimited-skills mcp bundle verify --bundle ./dist/team.bundle.json \
  --trusted-keys <store>/trusted-keys.json --audience-id team:reviewers [--json]
```

A thin wrapper over the REAL E14 verification (`resolve_bundle_state`):
exit 0 with the resolved profile and provenance, or exit 1 with the exact
refusal code and name (`-32013`..`-32019`). This is the same call `publish`
runs automatically post-package.

### 5. distribute -- the handoff

Hand consumers the bundle file plus the MANIFEST (so they can pin the
SHA-256) and the PUBLIC key file for `mcp trust import`. The gateway then
loads it exactly as E14 documents:

```
unlimited-skills mcp gateway --config ... --profile-bundle team.bundle.json \
  --audience-id team:reviewers [--require-signed-profiles]
```

### 6. revoke / rollback

The ROLLBACK metadata carries the exact command:

```
unlimited-skills mcp trust revoke --bundle-sha256 <bundle sha256> --reason <why>
```

When the bundle declares `revocation.crl_path` (the `--crl-path` flag)
pointing at the managed store's `crl.json`, that revocation takes effect at
the next verification (`-32017 bundle_revoked`, append-only history). Then
restore the previous bundle (its SHA-256 is recorded when `--previous` was
given) or fall back to the raw `--profiles` path, and restart the gateway.
The incident-drill runbook (`docs/mcp-incident-runbook.md`) rehearses every
one of these failure modes.

## Dev vs production keys

The keys this tool generates are for development, fixtures, and local
pilots ONLY -- the warning header, the bundle comment, and the manifest all
say so. Production signing keys (registered/business distribution) are
never generated, handled, or requested here; that issuing ceremony lives
outside the consumer core, exactly as the E13/E15 designs state. A DEV key
that was accidentally over-trusted is killed like any other key:
`unlimited-skills mcp trust revoke --key-id <id>`.

## Boundaries (unchanged)

E14 verification semantics and the E15 store semantics are reused, never
changed or bypassed. No network, no registry sync, no hosted calls, no
telemetry, no hot reload. The publisher writes only into the operator's
`--out` directories; it never touches the library root, the managed trust
store (except through the documented `trust import`/`revoke` commands the
operator runs), or the audit log.
