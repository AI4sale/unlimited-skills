# MCP signed profile bundles

**Status: PROTOTYPE (designed in E13, verification implemented by E14).**
This document is **Gate C** of the permissioned tool profiles design
([mcp-permissioned-tool-profiles.md](mcp-permissioned-tool-profiles.md), E09,
enforced by E10): the profile-signing gate that E09's "Signed/local format"
section reserved a slot for. It specifies **signed profile bundles** — a
distribution format that lets a team ship permissioned tool profiles to
consumers who did not author them, with authenticity, integrity, scope, and
freshness guarantees, so that nobody has to trust mutable local files
blindly. The E14 prototype implements the verification algorithm and refusal
codes below (`unlimited_skills/mcp/bundles.py`, opt-in via
`--profile-bundle`; see "Running the prototype"). Without the new flags the
E09/E10 behavior is byte-for-byte unchanged: raw profile files keep loading
exactly as before, and their optional signature envelopes are still
validated for shape only and grant nothing.

Artifacts:

- this document;
- `schemas/mcp-profile-bundle.schema.json` — JSON Schema (draft 2020-12) for
  the bundle format below;
- `examples/mcp/profile-bundle.example.json` — an annotated example that
  validates against the schema (`tests/test_mcp_profile_bundle_schema.py`);
- since E14: `unlimited_skills/mcp/bundles.py` (the verifier) and
  `tests/test_mcp_bundle_verification.py` (every refusal path, the
  verification order, rotation, the local-override intersection, and audit
  provenance, with ephemeral fixture keys).

## Running the prototype

```bash
unlimited-skills mcp gateway --config cfg.json \
  --profile-bundle ~/.unlimited-skills/team-bundle.json \
  --trusted-keys ~/.unlimited-skills/trusted-keys.json \
  --audience-id host:my-laptop [--audience-id team:core] \
  [--profile reviewer] [--profiles local-narrowing.json] \
  [--require-signed-profiles]
```

- `--profile-bundle FILE` configures the signed bundle, verified once at
  startup with the 10-step algorithm below; any failure is fail-closed
  refuse-all with the step's code (`-32014`…`-32019`), never unsigned
  fallback. `--trusted-keys FILE` is the local trust anchor;
  `--audience-id` (repeatable, beats the comma-separated
  `UNLIMITED_SKILLS_MCP_AUDIENCE` env var) presents the consumer's
  identifiers.
- Signature verification uses a pluggable backend; the default backend
  requires the optional `cryptography` package (real Ed25519). With no
  backend available a configured bundle refuses with `-32019`
  `bundle_key_missing` (decision 8) — never a silent pass.
- Profile selection inside a verified bundle: `--profile` >
  `UNLIMITED_SKILLS_MCP_PROFILE` > the bundle's `default_profile`.
- `--profiles` alongside the bundle is the `narrow-only` local override
  (decision 4): the single resolved selection name must exist in **both**
  artifacts (the local file's own `default_profile` is ignored — exactly one
  artifact owns selection), and the effective capability set is the
  intersection; the local file can narrow the bundle, never widen it.
- `--require-signed-profiles` is the signed-required policy: a raw
  `--profiles` file without a bundle — or no profile source at all — is
  refused fail-closed with `-32015` `bundle_signature_invalid`
  (decision 6). Default off pre-v0.6; without the flag the raw path is
  unchanged.
- Audit: the `profile_loaded` row records the source type
  (`raw_file`/`signed_bundle`), and for bundles the file SHA-256, issuer
  `key_id` and `display`, `audience`, `expires_at`, and verification status
  — never key material or signature values. Failed verifications append a
  `profile_loaded` row naming the failing step's code.
- Issuing/signing tooling is deliberately NOT in the consumer core; tests
  sign fixtures with ephemeral keys.

Compatibility note: the project has almost no users and backward
compatibility before v0.6 is explicitly not required. Signing is **opt-in**:
the local MIT core keeps loading unsigned profile files exactly as E09/E10
specify, and the signed-required policy below defaults to off pre-v0.6.

## Concept and pipeline

E09's threat model (vector 13, profile file tampering) deliberately stopped
at the local trust boundary: a local profile file has the same trust standing
as the upstream config beside it, because locally the file **author and the
file consumer are the same party** — signing would add ceremony without
adding a boundary. The moment profiles are *distributed* — checked out from
a team repo, pushed by an installer, or (future) synced from the registry at
unlimited.ai4.sale — author and consumer become different parties, and four
questions appear that a bare file cannot answer:

1. **Authenticity** — did the team's profile owner actually issue this file?
2. **Integrity** — is it byte-identical to what was issued?
3. **Scope** — was it issued *for this consumer* (team, org, host) and for
   *these upstreams*?
4. **Freshness** — is it still meant to be in force, or has it expired or
   been revoked?

The signed profile bundle answers all four. The pipeline, end to end:

```
local profile file ──(issue: wrap + sign)──▶ signed profile bundle
signed profile bundle ──(distribute: repo / installer / future registry)──▶ consumer host
consumer host ──(trust: local trusted-keys file)──▶ verification
verification ──(E09 selection precedence, unchanged)──▶ active profile
active profile ──(E09/E10 audit, extended)──▶ audit provenance
```

- **Issue.** The profile owner takes an E09 profile document (the `profiles`
  map and optional `default_profile`), wraps it in the bundle envelope below
  (issuer, audience, validity window, upstream-namespace ceiling, revocation
  pointer), canonicalizes, and signs with an Ed25519 key.
- **Distribute.** The bundle travels over any channel — the channel needs no
  trust, because trust is carried by the signature, not the transport.
- **Trust/verify.** The consumer's gateway verifies the bundle against a
  **local trusted-keys file** (no PKI, no network fetch in v1) before using
  any byte of its content. Every verification failure is fail-closed
  refuse-all with a named code (`-32015`…`-32019`), never a fallback to
  unsigned or open behavior.
- **Select.** Profile selection inside a verified bundle is E09's precedence
  unchanged: `--profile` > `UNLIMITED_SKILLS_MCP_PROFILE` > the bundle's
  `default_profile`; unresolved selection is `profile_not_found` (`-32013`).
- **Audit provenance.** The `profile_loaded` audit row is extended with the
  bundle's SHA-256, issuer key id, and audience, so "which issued artifact
  governed this session" is answerable from the audit log alone.

Everything E09 guarantees stays in force underneath: default-deny when a
profile is active, callable ⊆ visible, restriction-only inheritance,
existence-neutral refusals, restart-only reload, and the redaction floor. A
bundle can only ever *narrow* what the gateway would otherwise allow — a
verified bundle never widens anything, and a failed verification refuses
everything.

## Bundle format

A bundle is one local JSON file validated against
`schemas/mcp-profile-bundle.schema.json` (draft 2020-12,
`additionalProperties: false` throughout — unknown keys are load errors).
Annotated example at `examples/mcp/profile-bundle.example.json`:

```json
{
  "bundle_version": 1,
  "issuer": {
    "key_id": "ai4sale-team-profiles-2026",
    "display": "AI4SALE platform team"
  },
  "audience": ["team:core-ai4sale", "host:ci-runner"],
  "issued_at": "2026-06-01T00:00:00Z",
  "expires_at": "2026-09-01T00:00:00Z",
  "allowed_upstream_namespaces": ["github.*", "filesystem.*"],
  "default_profile": "dev-default",
  "profiles": {
    "dev-default": {
      "visible": ["github.*", "filesystem.*"],
      "callable": ["github.*", "filesystem.*"]
    },
    "reviewer": {
      "extends": "dev-default",
      "visible": ["github.*", "filesystem.*"],
      "callable": ["github.search_repositories", "filesystem.read_file"]
    }
  },
  "revocation": {
    "crl_path": "~/.unlimited-skills/profile-bundle-crl.json"
  },
  "signature": {
    "algorithm": "ed25519",
    "key_id": "ai4sale-team-profiles-2026",
    "value": "<base64 detached Ed25519 signature>"
  }
}
```

Top level (`comment` is accepted everywhere an object is and carries no
semantics, as in every other format in this repo):

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `bundle_version` | const `1` | yes | Bundle format version (independent of the embedded profile `schema_version`; a bundle embeds the E09 profile shapes directly). |
| `comment` | string | no | Annotation, ignored. |
| `issuer` | object | yes | Who issued the bundle: `key_id` (the signing key's identifier, same grammar as the E09 signature `key_id`) and `display` (a human-readable issuer name, 1–128 chars, for audit and refusal messages — never used for trust decisions; only `key_id` + the trusted-keys file decide trust). |
| `audience` | array of identifiers, 1–32, unique | yes | Who the bundle was issued *for*. Identifiers are `<scheme>:<name>` with exactly three schemes: `team:`, `org:`, `host:`. The consumer presents its own identifiers (see "Verification algorithm"); a non-empty intersection is required. An empty audience is unrepresentable (`minItems: 1`) — there is deliberately no "anyone" bundle. |
| `issued_at` | RFC 3339 UTC timestamp (`…Z`) | yes | Start of the validity window. |
| `expires_at` | RFC 3339 UTC timestamp (`…Z`) | yes | End of the validity window. Must be strictly after `issued_at` (static load check). Expiry is mandatory: an immortal bundle would make revocation the only freshness mechanism, and v1 revocation is a local file. Recommended validity ≤ 90 days. |
| `allowed_upstream_namespaces` | array of rules, 1–64, unique | yes | The bundle's upstream ceiling, in **the same two-form rule grammar as E09 profile rules** (exact `<upstream>.<tool>` or whole-upstream `<upstream>.*`; no regex, no partial globs, no wildcard upstream segment). Every `visible`/`callable` rule in every embedded profile must be covered by this list (static load check, see decision 10). |
| `default_profile` | profile name | no | Same meaning as E09's top-level `default_profile`, scoped to the embedded `profiles` map. |
| `profiles` | object, 1–64 entries | yes | The E09 profile map, embedded verbatim: the same per-profile shape (`comment` / `extends` / `visible` / `callable`), the same rule grammar, the same static load checks (extends exists, no self-reference, no cycles, depth ≤ 8, callable covered by visible). The bundle schema duplicates these constraints rather than `$ref`-ing across files, matching how the repo's schemas stay self-contained. |
| `revocation` | object | no | Revocation pointer, design-only in v1: `crl_path` (a local CRL file, format under "Trust and keys") and/or `registry_endpoint` (an `https://` URL reserved for the future registry gate — **never fetched in v1**; it is carried so that issued bundles do not need re-issuing when that gate opens). |
| `signature` | object | yes | Detached-signature block, exactly the E09 envelope shape: `algorithm` (enum, `ed25519` only), `key_id` (must equal `issuer.key_id` — static load check), `value` (base64 signature bytes). Unlike the E09 profile file, where the envelope is optional and shape-only, **a bundle without a signature is not a bundle** — the schema requires it. |

### Canonicalization and what is signed

The signature is computed over the **canonical JSON of the bundle document
with the top-level `signature` member removed**: UTF-8, object keys sorted
lexicographically, no insignificant whitespace — i.e. Python
`json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
encoded as UTF-8. This is the same normative definition E09 reserved, now
confirmed as Gate C's choice. It is an RFC 8785 (JCS)-style deterministic
serialization; full JCS differs only in number serialization, which cannot
bite here because the bundle format contains **no non-integer numbers
anywhere** (the only numeric fields are the two `const 1` versions;
timestamps are strings) — so the simple definition is exact, dependency-free,
and stays normative. Everything inside the document is signed: issuer,
audience, validity window, namespaces, profiles, default profile, and the
revocation pointer — an attacker can not splice a wider `audience` or a later
`expires_at` onto a signed profile set.

## Trust and keys

### Trusted-keys file (v1 key distribution — no PKI)

v1 key distribution is **one local trusted-keys file**: no certificate
chains, no X.509, no key servers, no network fetch. A consumer trusts
exactly the public keys a human put in that file, the same way they trust
the upstream config beside it. Shape (design-only in E13; E14 owns the
schema file if it needs one):

```json
{
  "schema_version": 1,
  "keys": [
    {
      "key_id": "ai4sale-team-profiles-2026",
      "algorithm": "ed25519",
      "public_key": "<base64 32-byte Ed25519 public key>",
      "not_after": "2027-01-01T00:00:00Z",
      "comment": "Current team profile-signing key."
    },
    {
      "key_id": "ai4sale-team-profiles-2025",
      "algorithm": "ed25519",
      "public_key": "<base64 32-byte Ed25519 public key>",
      "not_after": "2026-07-01T00:00:00Z",
      "comment": "Previous key, kept through the rotation overlap window."
    }
  ]
}
```

- `key_id` values are unique in the file and use the E09 `key_id` grammar.
- `public_key` is the raw 32-byte Ed25519 public key, base64. Public keys
  are not secrets; the file may be checked into a team repo and reviewed
  like any other config.
- `not_after` (optional) is a per-key trust deadline enforced by the
  consumer regardless of what bundles claim — the local side of rotation.
- The file is read once at gateway startup, like the profile file
  (restart-only reload, same E09 rationale).

### Key scopes

One key signs **profile bundles and nothing else**. Key ids are opaque
identifiers; the convention `<org>-<purpose>-<year>` (as above) keeps
rotation legible, but no semantics are parsed out of the id. A key in the
trusted-keys file is trusted for any audience — audience scoping lives in
the signed bundle, not in the key — because v1 has exactly one issuer per
trusted-keys file in practice (the team whose dotfiles these are), and
per-key audience restrictions are a delegation feature that belongs to the
registry gate if it is ever needed.

### Key rotation

Rotation is **multiple active keys with an overlap window**, selected by
`key_id`:

1. Generate the new keypair; add its public key to the trusted-keys file
   alongside the old one (consumers can now verify either).
2. Start signing new bundles with the new `key_id`.
3. After every consumer has received a bundle signed by the new key — at the
   latest when the last old-key bundle expires — remove the old key from the
   trusted-keys file (or let its `not_after` lapse), and optionally list the
   old `key_id` in the CRL if it must die before its bundles do.

The signature's `key_id` selects the verification key, so the overlap window
needs no heuristics: verification either finds the named key or refuses with
`bundle_key_missing`. Mandatory bundle expiry bounds how long a
forgotten-about old key keeps mattering.

### Revocation (v1: local CRL file)

The v1 revocation mechanism is a local CRL file (pointed at by the bundle's
`revocation.crl_path`, with `~` expansion; relative paths are a load error),
read once at startup:

```json
{
  "schema_version": 1,
  "revoked_bundles": ["<SHA-256 hex of revoked bundle file bytes>"],
  "revoked_key_ids": ["ai4sale-team-profiles-2024"]
}
```

- A bundle whose file SHA-256 is listed is refused with `bundle_revoked`
  (`-32017`).
- A signature whose `key_id` is listed is refused with `bundle_revoked`
  regardless of the bundle hash — key revocation kills every bundle the key
  ever signed.
- **A declared-but-unreadable CRL is fail-closed `bundle_revoked`**: if the
  bundle says "check this list" and the list cannot be read, the gateway
  cannot prove the bundle is *not* revoked, and "cannot prove not-revoked"
  must never silently become "trusted" (threat 18 below). A bundle with no
  `revocation` member skips this check — revocation is opt-in per bundle in
  v1, because mandating a CRL file before the registry gate exists would
  force every small team to maintain an empty file.
- `registry_endpoint` is carried but **never fetched in v1** — online
  revocation is the registry gate's problem (see "Future gates").

## Verification algorithm

Performed once, at gateway startup, before any byte of bundle content is
used for anything but parsing. The first failing step wins and produces a
**fail-closed refuse-all** state exactly like E09's: the gateway still
starts and serves the three meta-tools, but refuses every call with the
step's code, each refusal audited (same rationale — hosts swallow startup
stderr; a structured refusal is the loud failure).

1. **Read** the bundle file bytes; compute the file SHA-256 (used for
   revocation and audit provenance). Unreadable file → `profile_invalid`
   (`-32014`).
2. **Parse and shape-check** against the bundle schema's constraints (strict
   keys, grammars, bounds), plus the bundle-level static checks:
   `signature.key_id == issuer.key_id`, `issued_at < expires_at`, timestamps
   well-formed. Any violation → `profile_invalid` (`-32014`). (Shape
   validation necessarily runs on not-yet-verified data; it is strict,
   bounded, and allocation-light by construction — the same hardened-parser
   stance as every other loader in this repo.)
3. **Look up the key**: find `signature.key_id` in the trusted-keys file.
   Missing trusted-keys file, missing key, key past its `not_after`, or a
   missing verifier backend → `bundle_key_missing` (`-32019`) — see
   decision 8: never a silent fallback to unsigned.
4. **Verify the signature**: Ed25519 over the canonical JSON of the document
   minus `signature` (definition above). Mismatch → `bundle_signature_invalid`
   (`-32015`). Only after this step is any field of the bundle trusted.
5. **Check the validity window**: `issued_at − skew ≤ now < expires_at + skew`
   with a fixed clock-skew tolerance of 300 seconds. Outside the window
   (expired *or* not yet valid — one code for both, see decision 7) →
   `bundle_expired` (`-32016`).
6. **Check revocation**: if the bundle declares `revocation.crl_path`, load
   the CRL; bundle SHA-256 listed, signing `key_id` listed, or CRL
   unreadable → `bundle_revoked` (`-32017`).
7. **Check the audience**: the consumer's own identifiers (from repeatable
   `--audience-id` flags, or the `UNLIMITED_SKILLS_MCP_AUDIENCE` env var,
   comma-separated; flag wins over env, matching E09's explicitness order)
   must have a non-empty intersection with the bundle's `audience`. No local
   identifiers configured, or empty intersection →
   `bundle_audience_mismatch` (`-32018`).
8. **Check the namespace ceiling**: every `visible` and `callable` rule in
   every embedded profile must be covered by
   `allowed_upstream_namespaces` (an exact rule is covered by the same exact
   rule or its upstream's `.*` entry; a `.*` rule only by the same `.*`
   entry — the E09 coverage relation). Any uncovered rule →
   `bundle_audience_mismatch` (`-32018`) — the bundle reaches outside what
   it was issued for (decision 10).
9. **Run the E09 static load checks** on the embedded profile map unchanged
   (extends exists / no self-reference / no cycle / depth ≤ 8, callable
   covered by visible, `default_profile` exists). Violation →
   `profile_invalid` (`-32014`).
10. **Resolve the profile selection** with E09 precedence (`--profile` >
    `UNLIMITED_SKILLS_MCP_PROFILE` > bundle `default_profile`); unresolved →
    `profile_not_found` (`-32013`). Compile the active profile exactly as
    E10 does, append the extended `profile_loaded` audit row ("Audit
    provenance"), and enforce for the lifetime of the process — no hot
    reload, restart is the re-verification procedure.

## The ten design decisions

1. **Are unsigned profiles allowed by default?** **Yes.** No-profiles mode
   and unsigned local profile files (`--profiles`) keep working exactly as
   E09/E10 specify, and the signed-required policy
   (`--require-signed-profiles`) defaults to **off** pre-v0.6. Rationale:
   signing solves a distribution problem; forcing it on the local
   single-user case would add key ceremony with no boundary gained (the E09
   vector-13 analysis stands: local write access already grants upstream
   command configuration). Defaults change loudly or not at all — the v0.6
   flip is the place to revisit the default, not a silent side effect of
   shipping bundles.
2. **Does the local-only MIT core allow unsigned profiles?** **Yes,
   indefinitely.** The free local core is the author==consumer case by
   definition; an unsigned profile file there is a personal dotfile, and the
   MIT core must stay fully usable offline with zero key infrastructure.
   Bundles in the local core are opt-in hardening (a user may still verify a
   team bundle locally), never a requirement.
3. **Do registered/business profiles require signatures?** **Yes,
   unconditionally.** Any profile distributed through the
   registered/business tier — registry download, team sync, enterprise
   policy push — MUST arrive as a signed bundle, and the consuming gateway
   in those contexts MUST run with the signed-required policy. The
   sync/policy machinery is forbidden from ever writing an unsigned profile
   file onto a consumer host: the moment author ≠ consumer, an unsigned
   file is exactly the "mutable local file trusted blindly" this design
   exists to eliminate.
4. **How does enterprise policy override local profiles?** **The bundle is
   a ceiling; local config may only narrow it.** When a bundle is active,
   the bundle's `local_override` stance applies (a future enterprise-policy
   gate may set it centrally; in v1 it is the documented default
   `narrow-only`): a local unsigned profile file passed alongside the
   bundle is resolved independently and **intersected** with the bundle's
   selected profile — the same restriction-only conjunction as E09
   `extends`, applied across the file boundary at evaluation time, with no
   name resolution between the files. Local config can therefore tighten an
   enterprise bundle but can never widen it, mirroring E09's
   parent-as-ceiling inheritance. See "Local override policy" for the
   exact rules and the `deny` variant.
5. **How do signed bundles interact with the future registry/team sync?**
   **The registry distributes bundles as opaque signed blobs; verification
   stays local.** The future `policy_sync` gate (E09 "Team distribution")
   becomes a *transport* for bundle files: it downloads a bundle from
   unlimited.ai4.sale and drops it where `--profile-bundle` points. It
   never gains the power to bypass verification — the trusted-keys file
   remains the only trust anchor, sync never edits it, and a synced bundle
   that fails any verification step refuses exactly like a hand-copied one.
   The bundle's `registry_endpoint` revocation pointer and the `issued_at`
   ordering are the designed hooks that gate will build on (online CRL,
   monotonic-version warnings); neither is live in v1.
6. **What is the refusal code for a bad signature?** **`-32015`
   `bundle_signature_invalid`.** Also returned when the signature block is
   absent where one is required (signed-required policy with an unsigned
   file) and when no verifier backend is available — "cannot verify" and
   "verified false" are deliberately the same code, so an attacker gains
   nothing by *removing* a signature versus corrupting it (threat 16).
7. **What is the refusal code for an expired bundle?** **`-32016`
   `bundle_expired`.** The same code covers a not-yet-valid bundle
   (`issued_at` in the future beyond skew): both are "outside the signed
   validity window", the remediation is identical (obtain a currently valid
   bundle or fix the clock), and splitting them would spend a code to
   distinguish two states the agent must treat identically.
8. **What is the fallback when the key is missing?** **There is no
   fallback: fail-closed refuse-all with `-32019` `bundle_key_missing`.**
   A configured bundle whose signing key cannot be found (missing
   trusted-keys file, unknown `key_id`, key past `not_after`, missing
   crypto backend) refuses every meta-tool call, exactly like E09's
   `profile_not_found`/`profile_invalid` states. Silently proceeding
   unsigned would convert a key-distribution hiccup into a security
   downgrade an attacker can induce at will (delete one file → open mode);
   loud refusal converts it into a fixable configuration stop.
9. **Can a child profile extend an unsigned parent?** **No. Bundles are
   self-contained.** `extends` inside a bundle resolves only within the
   bundle's own `profiles` map (this is already the E09 grammar — `extends`
   is same-file by construction — and E13 reaffirms it across the new
   boundary: no mechanism for cross-file parents exists or will be added).
   A bundle profile extending an unsigned local profile would let unsigned
   bytes participate in defining a signed capability set, dissolving the
   integrity guarantee; the reverse (a local profile naming a bundle
   profile as parent) is equally unrepresentable — local narrowing happens
   by evaluation-time intersection (decision 4), never by name resolution
   into the bundle.
10. **Can a signed profile reference an upstream outside its audience?**
    **No.** Every `visible`/`callable` rule in every embedded profile must
    be covered by the bundle's `allowed_upstream_namespaces` (verification
    step 8); an uncovered rule is a static load error refused with
    `-32018` `bundle_audience_mismatch`, fail-closed refuse-all. The
    namespace ceiling is part of what the bundle was *issued for*, exactly
    like the audience identifiers: a reviewer reads one bounded list to
    know the maximal upstream surface any profile in the bundle can touch,
    and a compromised or sloppy profile entry deep in the map cannot reach
    an upstream the issuer never named. (Upstreams that exist in the
    gateway config but not in the ceiling are simply outside the bundle's
    world: invisible and uncallable under every bundle profile, by E09
    default-deny.)

## Refusal codes

Extending the implemented `-32001`…`-32014` family in
`unlimited_skills/mcp/gateway.py` / `unlimited_skills/mcp/profiles.py`
contiguously (next free code is `-32015`; all within the JSON-RPC
implementation-defined server-error range). These five codes are **reserved
by this design** and must not be reused for anything else. Like E09's
fail-closed states, each is a refuse-all condition: the gateway serves the
meta-tools but refuses **every** call with the code, every refusal audited.

| Code | Name | Meaning | Suggested agent behavior |
| --- | --- | --- | --- |
| `-32015` | `bundle_signature_invalid` | The bundle's Ed25519 signature does not verify over the canonical document — or the signature is absent where the signed-required policy demands one, or no verifier backend is available. Never distinguishes "tampered" from "stripped" from "unverifiable". | Never retry. Surface verbatim — this is a security stop: the bundle must be re-obtained from the issuer, or the policy/keys configuration fixed. |
| `-32016` | `bundle_expired` | The current time is outside the bundle's signed validity window (`issued_at`/`expires_at`, ±300 s skew) — expired or not yet valid. | Never retry. Tell the user to obtain a currently valid bundle (or fix the host clock). |
| `-32017` | `bundle_revoked` | The bundle's file SHA-256 or its signing `key_id` is listed in the configured CRL — or the bundle declares a CRL that cannot be read (cannot prove not-revoked). | Never retry. Surface verbatim; the issuer has withdrawn this bundle or its key, or the CRL file needs fixing. |
| `-32018` | `bundle_audience_mismatch` | The consumer's identifiers do not intersect the bundle's `audience` (or the consumer presented none) — or an embedded profile rule reaches outside `allowed_upstream_namespaces`. The bundle was not issued for this consumer or this upstream surface. | Never retry. Report which side mismatched (the message names the bundle's audience and the local identifiers); the user needs a bundle issued for this host/team. |
| `-32019` | `bundle_key_missing` | The signature's `key_id` is not present and valid in the local trusted-keys file (file missing, key absent, key past `not_after`, or verifier backend unavailable). Verification could not even be attempted. | Never retry. Surface verbatim — the user must install/update the trusted-keys file (or the signing key was rotated away and the bundle must be re-issued). |

Malformed bundle documents (JSON, schema shape, `issued_at`/`expires_at`
ordering, `signature.key_id` ≠ `issuer.key_id`, embedded-profile static
violations) reuse the existing `-32014` `profile_invalid` — the bundle *is*
the profile file in bundle form, and "the configured profile artifact is
structurally broken" is the same condition with the same remediation.
Selection failures inside a verified bundle reuse `-32013`
`profile_not_found` unchanged.

## Local override policy

What a local unsigned profile file may and may not do while a bundle is
active:

- **Default (`local_override: narrow-only`, the v1 documented stance):**
  the gateway may be started with *both* `--profile-bundle BUNDLE` and
  `--profiles LOCALFILE`. The local file is loaded and selected under the
  full E09 rules, completely independently (its `extends` graph never sees
  bundle profile names and vice versa — decision 9). The effective
  capability set is then the **intersection** of the bundle's selected
  profile and the local file's selected profile, for both visibility and
  callability — implementable in E14 by concatenating the two resolved rule
  chains, which preserves E09's evaluation semantics (conjunction of
  declared rule lists) and the callable ⊆ visible invariant. The local file
  can therefore hide tools the bundle shows and block calls the bundle
  allows, and can never do the reverse.
- **`deny`:** a future enterprise-policy gate may set the stance to `deny`,
  under which starting the gateway with both a bundle and a local profile
  file is a startup configuration error (and fail-closed `profile_invalid`
  refuse-all for hosts that swallow startup errors) — for fleets where even
  restriction-only local edits are unwanted noise. v1 designs the stance
  but ships no mechanism to select `deny`; it is listed so the enum exists
  before the policy gate needs it.
- **Never:** a local file widening the bundle, a local file replacing the
  bundle's profile of the same name, a local `default_profile` overriding
  the bundle's selection precedence (the local file's `default_profile` is
  ignored when a bundle is active — exactly one artifact owns selection),
  or any unsigned bytes entering the signed bundle's own resolution.
- Under the signed-required policy (`--require-signed-profiles`),
  `--profiles` **without** a bundle is refused outright
  (`bundle_signature_invalid`, decision 6); alongside a bundle it remains
  legal under `narrow-only`, because a strictly narrowing unsigned file
  cannot escalate anything (the bundle stays the ceiling).

## Audit provenance

Extends the E09/E10 audit model without weakening it. All new fields are
non-sensitive by grammar (key ids, hashes, audience identifiers, timestamps
— bounded charsets, no values, no paths), so they may appear at both audit
levels; the existing redaction floor is untouched.

- **The `profile_loaded` row gains bundle provenance.** When a bundle is
  active, the row records — in addition to E10's resolved profile name,
  profile-file SHA-256 (now the bundle file's SHA-256), and rule counts —
  the issuer `key_id`, the issuer `display` (length-capped like every
  audited string), the `audience` list, and `expires_at`. One row answers
  "which issued artifact, from whom, for whom, valid until when, governed
  this session".
- **Per-call rows are unchanged** beyond E10's `profile` field: provenance
  is pinned once per session by `profile_loaded` (the same reasoning as
  E09's no-reload decision — the bundle cannot change mid-process, so
  per-row repetition would be noise).
- **Every `-32015`…`-32019` refusal is audited** with its code name in the
  error string, like every existing refusal — fail-closed states caused by
  verification failures must be as observable as profile denials.
- **Verification failures record the stage, never the content**: the audit
  row for a failed verification names the failing step's code and the
  bundle file SHA-256 (when computable), but never embeds bundle content,
  public keys, or signature values — hashes and ids suffice for forensics.

## Threat model additions

Numbered continuing E07's nine and E09's 10–13:

| # | Vector | Description | Impact | Mitigations |
| --- | --- | --- | --- | --- |
| 14 | **Signing-key theft** | An attacker obtains the issuer's private key and mints arbitrary "valid" bundles widening any consumer's profile. | Fleet-wide silent privilege escalation — the worst case this design can produce. | Private keys never live on consumer hosts (only public keys in the trusted-keys file); mandatory bounded expiry (recommended ≤ 90 days) limits the blast radius of any minted bundle; key revocation via CRL `revoked_key_ids` kills every bundle a stolen key signed; rotation procedure makes replacing a compromised key routine; `profile_loaded` provenance (key id + bundle hash) makes minted-bundle use forensically visible. Residual risk: between theft and revocation, minted bundles verify — this is inherent to any signature scheme and is why expiry is mandatory. |
| 15 | **Stale / replayed bundle** | An attacker (or sync glitch) re-delivers an older, wider, still-unexpired bundle after the issuer shipped a narrower one. | Revoked-in-spirit capability stays live until the old bundle expires. | Mandatory expiry bounds the replay window; per-bundle revocation by file SHA-256 kills a specific stale bundle immediately; the `profile_loaded` SHA-256 row makes "which version governed when" reconstructable; the future registry gate adds monotonic `issued_at` ordering (warn/refuse on regression) — designed hook, not v1 behavior. |
| 16 | **Downgrade to unsigned** | An attacker swaps the signed bundle for an unsigned profile file, strips the signature member, or unsets the bundle flags, hoping the gateway quietly falls back to unsigned or open behavior. | Total bypass of every guarantee in this document. | The signed-required policy refuses unsigned profile sources outright; a stripped signature fails the schema's `required` (a bundle without a signature is not a bundle) and, under policy, refuses with the same `-32015` as a corrupted one — stripping gains nothing over tampering; missing keys/backends are fail-closed (`-32019`), never fallback (decision 8); bundle-vs-file loading is distinguishable in the audit log, so a downgrade that relies on flag changes leaves a visible trail. Residual risk: an attacker who can edit the gateway's own invocation (host config) can remove `--require-signed-profiles` itself — host-config integrity is the E07 trust boundary, explicitly out of scope here. |
| 17 | **Audience confusion** | A bundle legitimately issued for team A (wide grants) is delivered to team B's hosts, or a multi-team host loads the wrong team's bundle. | Capability cross-contamination between teams without any forgery. | Mandatory non-empty `audience` with mandatory non-empty intersection against locally configured identifiers (`-32018`); the audience is inside the signed document (unspliceable); `allowed_upstream_namespaces` bounds the upstream surface even when identifiers collide; audience identifiers are stamped into `profile_loaded` rows for after-the-fact detection. |
| 18 | **Revocation unavailability** | The CRL file a bundle points to is deleted, unreadable, or (future) the registry endpoint is unreachable, exactly when a revoked bundle is replayed. | Revocation silently stops working while everything else verifies. | Declared-but-unreadable CRL is fail-closed `bundle_revoked` — "cannot prove not-revoked" never degrades to "trusted"; v1 CRLs are local files, so unavailability is local misconfiguration (fixable, auditable), not network weather; bundles without a `revocation` member never depend on CRL availability, and their freshness rests on mandatory expiry alone; the v1 `registry_endpoint` is never fetched, so a network outage cannot affect v1 verification at all. |

## Future gates

- **Registry / team sync (`policy_sync`, E09's future gate).** Builds on
  this design as transport only (decision 5): bundle download/refresh from
  unlimited.ai4.sale, online CRL via `registry_endpoint`, monotonic
  `issued_at` regression warnings, and rollout staging. It must not touch
  the trust model: trusted-keys file remains the only anchor, verification
  remains local, and every guarantee in this document is a precondition,
  not an effect, of sync.
- **Enterprise policy.** A future gate may deliver centrally managed
  policy — the signed-required flag, the `local_override: deny` stance,
  mandated audience identifiers per fleet — through the registered/business
  tier. This document deliberately designs the *enforcement points* those
  policies will set (the flag, the stance enum, the identifier sources) so
  the policy gate composes with E13 instead of reopening it.
- **Verifier backend decision (resolved by E14).** The repo is
  zero-dependency by stance, and the Python standard library has no
  Ed25519. E14 chose a **pluggable backend with one optional dependency**:
  the default backend uses the `cryptography` package when importable
  (real Ed25519, never vendored curve math), an absent backend with a
  bundle configured is `-32019` fail-closed (decision 8), and key
  *generation*/signing tooling stays out of the consumer code path.

## Non-goals

- **No signing/keygen tooling shipped with verification.** The E14
  prototype implements *verification only* (`unlimited_skills/mcp/bundles.py`);
  issuing bundles remains the profile owner's tooling, outside the consumer
  code path.
- **No PKI.** No certificate chains, no X.509, no CAs, no key servers, no
  delegation/threshold schemes (no TUF-style roles). One flat local
  trusted-keys file is the v1 trust anchor.
- **No network fetch of keys, bundles, or CRLs.** Everything verified in v1
  is a local file; `registry_endpoint` is carried, never dereferenced.
- **No signing/keygen tooling in the consumer core.** Issuing bundles is
  the profile owner's tooling (registry-side or scripts gated to E14+);
  this design specifies only what consumers verify.
- **No per-profile signatures, no partial trust.** The whole bundle is
  signed or nothing is; signing individual profiles inside one file invites
  mix-and-match splicing attacks for no distribution benefit.
- **No confidentiality.** Bundles are authenticated, not encrypted —
  profile rules are non-sensitive by grammar (E09 "Redaction"), and
  encryption would only complicate review.
- **No hot reload, no online revocation, no per-call re-verification** —
  verification is once-at-startup, restart is the re-verification
  procedure, matching E09's load-once semantics and its TOCTOU rationale.

## Migration path and E14

Relationship to the E09 migration path and the proposed v0.6 flip:

1. **E13 (design):** codes `-32015`…`-32019` reserved; the bundle schema
   and example exist; nothing verified, nothing enforced; E09/E10 behavior
   byte-for-byte unchanged.
2. **E14 (this prototype, pre-v0.6):** implements this
   document — `--profile-bundle` / `--trusted-keys` / `--audience-id` /
   `--require-signed-profiles` on the gateway, the verification algorithm,
   the five refusal codes, the intersection-based local override, and the
   extended `profile_loaded` row. All **opt-in**: without the new flags,
   nothing changes. Evidence gating E14 (mirroring how E10 evidenced
   E09): enforcement tests in the style of
   `tests/test_mcp_tool_profile_enforcement.py` covering at minimum —
   tamper detection (flip one signed byte → `-32015`), signature stripping
   under the signed-required policy (`-32015`), expiry and not-yet-valid
   with an injected clock (`-32016`), bundle and key revocation plus
   unreadable-CRL fail-closed (`-32017`), audience mismatch and
   namespace-ceiling violations (`-32018`), missing key / missing
   trusted-keys file / missing backend (`-32019`), key rotation across an
   overlap window (two active keys), the local-override intersection never
   widening, refuse-all coverage of all three meta-tools in every failed
   state, and a leak-grep proof that audit rows and refusal messages never
   contain key material or signature values.
3. **v0.6 (the E09 flip, unchanged by E13):** the explicit
   profiles-or-`--no-profiles` stance ships as designed in E09. E13 adds
   one clause to that flip: in registered/business contexts the stance must
   additionally be `--require-signed-profiles` + a bundle (decision 3). The
   local MIT core's unsigned option survives the flip (decision 2) — v0.6
   forces a *choice*, not signing.

## Invariants preserved

Everything in E07's and E09's invariant lists holds unchanged. Bundles add
two more:

- **A verified bundle never widens anything.** Its only possible effects
  are the E09 effects (hiding tools, refusing calls) plus refusing
  everything when verification fails. Removing a bundle returns the gateway
  to exactly the E09/E10 behavior of whatever else is configured.
- **Unverifiable is invalid.** No state in this design lets unverified
  bundle content govern enforcement: every path that cannot complete
  verification ends in a named, audited, fail-closed refuse-all — never in
  open behavior, never in unsigned fallback.
