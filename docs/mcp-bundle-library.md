# MCP profile bundle library and activation manager (E20)

Status: implemented (`unlimited_skills/mcp/bundle_library.py`,
`tests/test_mcp_bundle_library.py`).

A LOCAL library of signed MCP profile bundles -- install, list, status,
pin/unpin, activate/deactivate, rollback to a known-good bundle. No registry
sync, no hosted calls, no production signing keys. It closes one operational
gap: *"I have 5 bundle files. Which are installed? Which is active? How do I
roll back?"*

```
unlimited-skills mcp profiles library status|list|add|inspect|activate|
                                      deactivate|rollback|pin|unpin|remove|doctor
```

Common flags on every subcommand: `--library-dir` (default
`<library root>/.unlimited-skills-bundles/`), `--trusted-keys` (default: the
E15 managed store's `trusted-keys.json` under
`<root>/.unlimited-skills-trust/` when it exists -- exactly the gateway's
rule; with neither, verification refuses with `-32019 bundle_key_missing`),
`--audience-id` (repeatable), `--json`.

## What the library stores

- Bundle files are stored IMMUTABLE and content-addressed as
  `<sha256-prefix>-<name>.bundle.json`. The library never edits bundle
  bytes -- that would break the detached signature.
- `library-state.json` (atomic writes: temp file + `os.replace`, the E15
  pattern) tracks the entries (sha256, name, issuer key_id, audience,
  validity window, added_at, source BASENAME, pinned flag, verification
  status at add time), the single ACTIVE bundle sha (at most one), and an
  append-only activation history `(sha, action, ts)` that powers
  `rollback`.
- No key material beyond what bundles already contain (public information
  only) is ever stored or printed; audit-style outputs carry source
  basenames, never the operator's absolute source paths.

## Verification: the real E14 path, three times

Verification is always :`resolve_bundle_state` (via the E19 `verify`
wrapper) -- never a reimplementation, never a bypass:

1. **`add FILE`** verifies BEFORE anything is stored. Any refusal carries
   the exact reserved code (`-32014` malformed, `-32015` signature,
   `-32016` expired, `-32017` revoked, `-32018` audience, `-32019` key
   missing) and nothing is written. There is NO quarantine mode and no
   `--allow-unverified`: a bundle that cannot be verified has no business
   in an activation library -- fix the bundle or the trust store, then add
   it. A duplicate sha256 is an idempotent no-op.
2. **`activate` / `rollback`** RE-verify at activation time -- the trust
   store keys and the CRL may have changed since `add`.
3. **`doctor`** re-verifies every entry against the CURRENT trust
   store/CRL.

Audience note: explicit `--audience-id` flags (or
`UNLIMITED_SKILLS_MCP_AUDIENCE`) are checked strictly. When omitted
entirely, the library verifies with the bundle's own first declared
audience identifier (self-audience): signature, validity window,
revocation, and key trust are still fully proven; audience BINDING stays
enforced by the gateway at startup with the consumer's real identifiers.

## Operator lifecycle

```text
# 1. Publish (E19 ceremony) or receive a signed bundle file.
unlimited-skills mcp bundle publish --profiles team.json --signing-key ... --audience team:alpha --out dist

# 2. Install it (verified through the real E14 path before storing).
unlimited-skills mcp profiles library add dist/team.bundle.json

# 3. See what is installed and what state each bundle is in NOW.
unlimited-skills mcp profiles library list
unlimited-skills mcp profiles library status

# 4. Activate (re-verified; writes <library>/active.bundle.json atomically).
unlimited-skills mcp profiles library activate team

# 5. Start the gateway against the activation pointer.
unlimited-skills mcp gateway --config gateway.json \
    --profile-bundle <library-dir>/active.bundle.json --audience-id team:alpha

# 6. Roll back to the previous known-good bundle when v2 misbehaves.
unlimited-skills mcp profiles library activate team-v2   # oops
unlimited-skills mcp profiles library rollback           # back to team
# ... then RESTART the gateway (no hot reload).
```

### Activation pointer mechanism

`activate` copies the verified stored bytes to
`<library>/active.bundle.json` atomically (a plain file copy via temp +
`os.replace` -- no symlinks, Windows-safe). The gateway is pointed at that
file with `--profile-bundle` and reads it ONCE at startup; **there is no
hot reload**, consistent with E10/E14 -- activating or rolling back takes
effect at the next gateway start. The gateway re-runs the full E14
verification itself at startup, so a stale, expired, or since-revoked
active copy still fails closed with the exact reserved code; the pointer
file grants nothing by itself.

`deactivate` clears the active record and removes `active.bundle.json`
(idempotent). A gateway restarted WITHOUT `--profile-bundle` runs in OPEN
no-profiles mode (no enforcement) -- the command says so loudly; restarted
against the now-missing pointer file it fails closed (`-32014`).

### Rollback semantics

`rollback` walks the append-only activation history backwards (most recent
first), skips the currently active sha, and re-verifies each candidate
through the real E14 path. Candidates that are now revoked, expired, or
otherwise refused are skipped LOUDLY -- each skip is reported with its
exact code -- until one verifies and is activated (history action
`rollback`). If no candidate verifies, rollback refuses (exit 1) and
nothing changes. When nothing is active (after `deactivate`), rollback
re-activates the most recent still-verifying activation.

### Pin semantics

`pin` / `unpin` are subcommands (idempotent). A PINNED entry always
refuses `remove` -- `--force` does NOT override a pin (that is what
pinning is for); unpin first. The ACTIVE entry refuses `remove` without
`--force`; with `--force` it is deactivated first (recorded in the
history) and then removed.

### Doctor

`doctor` re-verifies every entry against the current trust store/CRL and
checks the library invariants. PROBLEMS (exit 1): corrupt/unreadable state
file (with rebuild guidance: move it aside and re-add the original bundle
files -- the stored bundles are immutable, nothing signed is lost), an
entry whose stored file is missing or whose bytes no longer match the
recorded sha256, an ACTIVE bundle that no longer verifies (the gateway
would fail closed at its next start), a stale active pointer
(`active.bundle.json` not matching the active entry, or present with
nothing active), an active sha with no entry or no activation history
record. WARNINGS (exit 0): non-active entries that no longer verify
(expired/revoked/key-missing -- they only block activation and rollback),
orphan `*.bundle.json` files no entry references, history records naming
bundles no longer installed.

## Relationship to the publisher ceremony and the trust store

The E19 publisher (`mcp bundle keygen|publish|verify`,
[mcp-bundle-publishing.md](mcp-bundle-publishing.md)) PRODUCES signed
bundle files; this library CONSUMES them. The E15 managed trust store
(`mcp trust ...`, [mcp-trust-store.md](mcp-trust-store.md)) decides which
keys are trusted and which bundles/keys are revoked -- the library only
ever reads it (default trusted-keys resolution) and never writes trust
artifacts. A `mcp trust revoke --bundle-sha256 ...` takes effect in the
library at the next `activate`/`rollback`/`doctor` re-verification and in
the gateway at its next start.

## Boundaries (unchanged)

E14 verification semantics are reused, never changed or bypassed. Offline
by construction: no network, no registry sync, no hosted calls, no
telemetry, no production signing keys, no hot reload. Atomic state and
pointer writes; loud refusals with the exact reserved codes.

## End-to-end operator acceptance

The whole lifecycle this library sits inside -- publish, trust import,
verify, add, rollout-plan, replay-audit, activate, gateway resolve,
revocation incident, rollback, audit report -- is exercised as ONE
fixture-mode workflow by `scripts/run-mcp-operator-acceptance.py`
([mcp-operator-acceptance.md](mcp-operator-acceptance.md)), which also
serves as the operator onboarding walk-through.
