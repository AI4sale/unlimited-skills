# MCP profile trust store

**Status: implemented (E15).** A managed local trust store for the signed
MCP profile bundle artifacts of
[mcp-signed-profile-bundles.md](mcp-signed-profile-bundles.md) (E13 design,
E14 verification): trusted PUBLIC keys, key scopes, rotation, revocation,
expiry — managed by CLI instead of hand-editing JSON. The store is a
**management layer over the E14 files, never a bypass**: every trust
decision is still made by the unchanged verifier
(`unlimited_skills/mcp/bundles.py`, refusal codes `-32015`…`-32019`), and
the store only manages WHICH local files exist and what they contain.

Everything is **offline**: no network, no registry sync, no hosted calls.
The store holds **public keys only** — `import` refuses anything that looks
like private key material before a single byte is written. Output never
contains full key bytes beyond an abbreviated SHA-256 fingerprint (16 hex
chars).

## Store location and files

The canonical managed store is one directory under the library root:

```
<library root>/.unlimited-skills-trust/
├── trusted-keys.json     # EXACT E14 trusted-keys format — the gateway reads it unchanged
├── crl.json              # EXACT E14 local CRL format (revoked_bundles + revoked_key_ids)
└── trust-metadata.json   # store-only sidecar (schemas/mcp-trust-store-metadata.schema.json)
```

- `trusted-keys.json` and `crl.json` reuse the E14 formats **verbatim** —
  one source of truth; the store manages those files, verification keeps
  loading them with the same strict loaders. The E14 formats are strict
  (unknown keys are load errors), so store metadata that verification must
  never see (display names, informational scopes, `not_before`, import
  timestamps, revocation reasons) lives in the `trust-metadata.json`
  sidecar, which **is never read by verification and grants nothing**.
- `--store-dir DIR` on every `mcp trust` subcommand targets a different
  directory; the default is `<root>/.unlimited-skills-trust`.
- Explicit gateway paths keep working everywhere: `--trusted-keys FILE` and
  a bundle's `revocation.crl_path` may point anywhere, managed or not.
- All writes are atomic (temp file in the same directory + `os.replace`);
  a failed write never leaves a partial store file behind.

### Gateway default

When the gateway is started with `--profile-bundle` but **without**
`--trusted-keys`, and the managed store's `trusted-keys.json` exists under
the library root, the gateway defaults to that file. When no managed store
exists, behavior is byte-for-byte unchanged from E14: the verifier refuses
with `-32019` `bundle_key_missing` ("no trusted-keys file configured").
This only resolves *which file is read* — verification semantics are
untouched, and an explicit `--trusted-keys` always wins. To point the
gateway at a managed CRL, set the bundle's `revocation.crl_path` to
`<store>/crl.json` when issuing (the CRL pointer is signed bundle content,
by design).

## Commands

All commands accept `--store-dir DIR` and `--json` (machine-readable
report).

### `unlimited-skills mcp trust status`

Store location, key counts by state (`active` / `expiring_soon` — within
`--expiring-days`, default 30 / `expired` / `revoked`), CRL presence and
size, metadata presence, and a problems summary.

### `unlimited-skills mcp trust list`

Every trusted key with `key_id`, display name, scopes, `not_before` /
`not_after`, state, and the abbreviated fingerprint (never the full key).

### `unlimited-skills mcp trust import`

Add one PUBLIC Ed25519 key, from a small JSON key file (`--key-file`; keys:
`key_id`, `public_key`, optional `display` / `scopes` / `not_before` /
`not_after` / `comment` — inline flags win over file fields) or inline:

```bash
unlimited-skills mcp trust import \
  --key-id team-profiles-2026 \
  --public-key "<base64 raw 32-byte Ed25519 PUBLIC key>" \
  --display "Platform team" --scope profile-bundles \
  --not-after 2027-01-01T00:00:00Z
```

- `not_after` is written into the trusted-keys entry (the E14 per-key trust
  deadline, **enforced** by verification). `not_before` and `scopes` are
  informational sidecar metadata — v1 keys sign profile bundles and nothing
  else (design "Key scopes"), so scopes are labels, never parsed by
  verification.
- **Public keys only.** Refused loudly, with nothing written: any PEM
  `PRIVATE KEY` marker in the input, key-file fields that smell private
  (`private_key`, `seed`, `secret`, `d`, …), and decoded material whose
  length looks private (64 bytes = Ed25519 seed+public, 48 bytes = PKCS#8
  private key DER). Only a raw 32-byte public key is accepted.
- **Duplicate `key_id` with different material is a loud refusal** —
  silent key replacement is exactly what a trust store must not do; revoke
  the old key and import under a new `key_id`. Re-importing the identical
  key is an idempotent no-op.

### `unlimited-skills mcp trust revoke`

Add a key id (`--key-id`) **or** a bundle file SHA-256 (`--bundle-sha256`)
to the managed local CRL — the same E14 semantics: a revoked key kills
every bundle it ever signed; a revoked bundle hash kills that file.
Idempotent (already-listed targets are no-op successes) and **append-only**
— revocation history is never deleted. `--reason` is recorded in the
metadata sidecar only (the E14 CRL format has no reason field and stays
untouched).

### `unlimited-skills mcp trust doctor`

Offline self-check; exit code 0 ok / 1 problems.

Problems (exit 1): malformed or unreadable store files (trusted-keys, CRL,
metadata), duplicate `key_id`s, a file the strict gateway loader would
refuse, expired keys with **no** active key remaining
(expired-but-not-rotated), a revoked key still listed in trusted-keys with
no metadata revocation record (revoked outside the store, unexplained),
world-writable store files (POSIX; permission checks are best-effort on
Windows).

Warnings (exit 0): keys expiring within `--expiring-days`, expired keys
while an active key remains (normal rotation tail), an empty trusted-keys
file (the gateway would refuse with `bundle_key_missing`), revoked keys
kept in trusted-keys for history (the CRL wins), metadata naming unknown
key ids.

## Key lifecycle

1. **Import** the current signing key's public half (`trust import`,
   `--not-after` recommended).
2. **Rotate** with an overlapping validity window (the E14 rotation design,
   unchanged): import the NEW key under a new `key_id` while the old one is
   still trusted; bundles select the verification key by their signature's
   `key_id`, so both verify during the overlap.
3. **Expire**: let the old key's `not_after` lapse — verification then
   refuses it with `bundle_key_missing`. `doctor` warns while it is
   expiring and flags expired-but-not-rotated stores as problems.
4. **Revoke** (`trust revoke --key-id …`) when a key must die before its
   bundles do — compromised or withdrawn keys. Revocation beats expiry:
   the CRL kills every bundle the key signed immediately.

## Non-goals

Unchanged from E13/E14: no private keys (no keygen, no signing — issuing
stays outside the consumer core), no PKI, no network fetch, no registry
sync (the future `policy_sync` gate is transport only), no hosted calls,
no hot reload (the gateway reads trust files once at startup; restart is
the re-verification procedure).
