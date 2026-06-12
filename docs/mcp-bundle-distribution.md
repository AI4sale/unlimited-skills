# MCP bundle distribution: channels and assignments (E23 design)

**Status: DESIGN (E23, docs/schema only — nothing implemented, nothing
hosted).** Branch stack: this design is based on the E22 lineage
(`feat/v04-e22-mcp-profile-stack-stabilization-audit-v1`), i.e. the fullest
local MCP profile stack — E06–E22 including the E12B warm cache — with the
later stack tests present. It specifies HOW signed profile bundles
([mcp-signed-profile-bundles.md](mcp-signed-profile-bundles.md), E13/E14)
get distributed to registered/business teams: a publisher issues bundles
into named **channels**, and team members hold **assignments** saying which
channel or pinned bundle a given audience identifier should activate. It
bridges the existing local stack (E13–E22) to the future registry sync at
unlimited.ai4.sale **without implementing anything hosted**: channels and
assignments are plain local FILES a team can distribute over any transport
today (git repo, shared drive, USB stick), and the future registry sync is
designed to be a *dumb carrier* for these same files.

Everything here is offline by construction: no network, no hosted calls, no
registry API, no telemetry. Distribution files never grant capability by
themselves — the signed bundle stays the only capability artifact, and
every bundle a member activates still passes the unchanged E14 verification
(`resolve_bundle_state`) against the E15 trust store, fail-closed with the
reserved codes `-32014`…`-32019`. A channel or assignment can route a
member to a bundle; it can never weaken what verification demands of that
bundle.

Artifacts:

- this document;
- `schemas/mcp-bundle-channel.schema.json` — JSON Schema (draft 2020-12)
  for the channel document below;
- `schemas/mcp-bundle-assignment.schema.json` — JSON Schema (draft 2020-12)
  for the assignment document below;
- `examples/mcp/bundle-channel.example.json` and
  `examples/mcp/bundle-assignment.example.json` — annotated examples that
  validate against the schemas
  (`tests/test_mcp_distribution_schemas.py`, which also encodes the
  semantic load rules below as executable documentation).

## The distribution model

The local stack already covers one publisher handing one consumer one file:
the E19 ceremony ([mcp-bundle-publishing.md](mcp-bundle-publishing.md))
produces a signed bundle, the consumer imports the public key into the E15
store ([mcp-trust-store.md](mcp-trust-store.md)), and the E20 library
([mcp-bundle-library.md](mcp-bundle-library.md)) installs and activates it.
What is missing is the *team* shape of the same flow: ten members, three
roles, a stable and a beta track, and one operator who needs to answer
"who should be running what, and how do I move everyone safely?". Two
file-based concepts close that gap:

- **Channel** — a named, ordered publish history owned by one issuer key:
  "the `stable` channel currently points at bundle `<sha256>`". Channels
  are how the publisher *moves* a team: publish a new bundle, point the
  channel at it, and every follower picks it up at its next library
  refresh. Channel names are operator vocabulary (`stable`, `beta`,
  `team-reviewers`); nothing parses semantics out of them.
- **Assignment** — a statement that a given audience (team, org, or host
  identifier — the same `team:`/`org:`/`host:` grammar as the bundle
  `audience`) should activate either a channel's current bundle
  (**follow** mode) or one exact bundle SHA-256 (**pin** mode). Assignments
  are how the operator *differentiates* a team: reviewers follow `stable`,
  the CI host is pinned to an exact sha, a pilot group follows `beta`.

The end-to-end pipeline, composing only existing layers:

```
publisher ceremony (E19: keygen/publish/verify, signed bundle + manifest)
        │
        ▼
channel publish record (this design: append the bundle sha to the channel
        │                history, point `current` at it, bump `revision`)
        ▼
assignment (this design: audience → channel follow | sha pin, validity)
        │
        ▼  any transport: git repo / shared drive / future registry sync
member's library (E20: `library add` then `activate` — both run the REAL
        │          E14 verification against the E15 trust store)
        ▼
gateway startup (E14: re-verifies the active bundle itself; fail-closed
                 refuse-all with -32014..-32019 on any failure)
```

Nothing in the last three rows is new: the member-side mechanics are
exactly E20 + E14 + E15, unchanged. E23 adds only the two routing files
above the library, and a small amount of future client behavior ("resolve
my assignment, fetch the named sha from wherever the files live, run
`library add` + `activate`") that is deliberately specified as *operator
procedure first* — a human can execute the whole flow today with the
existing CLI and a shared folder.

## Offline-first: files over any transport

Channels and assignments are single JSON documents, like every other
artifact in this stack. A team distributes them exactly as it distributes
bundles today (E13 decision 5: the transport needs no trust, because trust
is carried by signatures, not the channel):

- **git repo** — a `profiles/` directory holding `*.bundle.json`,
  `*.channel.json`, and `*.assignment.json`; review happens in pull
  requests; members pull and run the library commands.
- **shared drive / installer** — the same files pushed by whatever fleet
  tooling the team already has.
- **future registry sync** — the registered/business transport: the
  registry stores and delivers these same files as opaque blobs. The file
  contracts in this document are the whole interface; the hosted side adds
  storage, listing, and entitlement gating, and nothing else. It never
  parses profile rules, never verifies on behalf of the member (the
  trusted-keys file stays the only trust anchor, E13 decision 5), and
  never gains the power to mint, widen, or substitute a bundle without
  breaking a signature a member would catch locally.

Because the registry is a dumb carrier, the threat model of distribution
does not change with the transport: a hostile git remote, a compromised
shared drive, and a compromised registry all have exactly the same power —
withhold files or replay old ones — and the same mitigations (signatures,
bundle expiry, revision monotonicity, CRL revocation) apply identically.

## Channel document

One JSON file validated against `schemas/mcp-bundle-channel.schema.json`
(draft 2020-12, `additionalProperties: false` throughout — unknown keys
are load errors). Annotated example at
`examples/mcp/bundle-channel.example.json`:

```json
{
  "channel_version": 1,
  "name": "stable",
  "revision": 3,
  "owner": {
    "key_id": "ai4sale-team-profiles-2026",
    "display": "AI4SALE platform team"
  },
  "history": [
    { "bundle_sha256": "<64-hex>", "published_at": "2026-06-01T00:00:00Z", "status": "superseded" },
    { "bundle_sha256": "<64-hex>", "published_at": "2026-06-05T00:00:00Z", "status": "revoked" },
    { "bundle_sha256": "<64-hex>", "published_at": "2026-06-08T00:00:00Z", "status": "active" }
  ],
  "current": "<64-hex of the single active entry>",
  "signature": { "algorithm": "ed25519", "key_id": "ai4sale-team-profiles-2026", "value": "<base64>" }
}
```

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `channel_version` | const `1` | yes | Channel document format version. |
| `comment` | string | no | Annotation, ignored (accepted on every object, as everywhere in this repo). |
| `name` | channel name (`^[A-Za-z0-9][A-Za-z0-9_-]*$`, ≤ 64) | yes | The channel's operator-facing name (`stable`, `beta`, `team-reviewers`). Opaque: no semantics are parsed out of it. Channel identity is the *pair* (`name`, `owner.key_id`) — two channels with the same name and different owners are different channels, so a name alone can never be squatted. |
| `revision` | integer ≥ 1 | yes | Monotonic document revision. Every republication of the channel (new publish, rollback, status change) bumps it. Consumers remember the highest revision they have applied per channel identity and refuse to move to a lower one — the offline anti-replay analogue of the registry-gate "monotonic `issued_at`" hook in E13 threat 15. |
| `owner` | object | yes | The channel's owning issuer: `key_id` (same grammar as the bundle issuer `key_id`; the only field trust decisions use, against the E15 trusted-keys file) and `display` (human-readable, audit/messages only, grants nothing). |
| `history` | array of publish records, 1–256, ordered | yes | The append-only publish history, oldest first. Each record: `bundle_sha256` (64-hex SHA-256 of the signed bundle file bytes — the same content address the E20 library and the E15 CRL already use), `published_at` (RFC 3339 UTC `Z`, non-decreasing across the array), `status` (`active` / `superseded` / `revoked`), optional `comment`. Exactly one record has status `active` (semantic load check). A sha may appear more than once: rollback re-publishes a prior sha as a NEW record (see "Rollback"). `revoked` in a history record is *informational routing state* ("do not activate this one"); authoritative revocation stays the E15 CRL, which the member's verification enforces regardless of what any channel claims. |
| `current` | 64-hex SHA-256 | yes | The current pointer. Must equal the `bundle_sha256` of the single `active` history record (semantic load check) — the pointer and the history can never disagree. |
| `signature` | object | no (format) / **required for registered-tier distribution** (decision 1) | Detached-signature envelope, exactly the E13 shape (`algorithm` enum `ed25519` only, `key_id` — must equal `owner.key_id`, semantic load check — and base64 `value`), computed over the canonical JSON of the document minus `signature` (the same normative canonicalization as bundles: UTF-8, sorted keys, no insignificant whitespace; the format contains no non-integer numbers, so the simple definition stays exact). Optional in the *format* so the MIT core can use unsigned channel files locally (decision 1); the signed-distribution policy and the registered tier refuse unsigned channels outright. |

Channels deliberately carry **no validity window**: freshness rides on the
bundles themselves (mandatory `expires_at` per E13 — a stale channel points
at bundles that refuse with `bundle_expired`, `-32016`) plus the monotonic
`revision`. Adding a second expiry to the routing layer would create
two clocks that can disagree without adding a boundary.

## Assignment document

One JSON file validated against
`schemas/mcp-bundle-assignment.schema.json` (draft 2020-12,
`additionalProperties: false` throughout). Annotated example at
`examples/mcp/bundle-assignment.example.json`:

```json
{
  "assignment_version": 1,
  "audience": ["team:core-ai4sale"],
  "channel": { "name": "stable", "owner_key_id": "ai4sale-team-profiles-2026" },
  "mode": "pin",
  "bundle_sha256": "<64-hex>",
  "issuer": { "key_id": "ai4sale-team-profiles-2026", "display": "AI4SALE platform team" },
  "revision": 2,
  "issued_at": "2026-06-08T00:00:00Z",
  "expires_at": "2026-09-01T00:00:00Z",
  "signature": { "algorithm": "ed25519", "key_id": "ai4sale-team-profiles-2026", "value": "<base64>" }
}
```

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `assignment_version` | const `1` | yes | Assignment document format version. |
| `comment` | string | no | Annotation, ignored. |
| `audience` | array of identifiers, 1–32, unique | yes | WHO this assignment is for: the exact E13 `audience` grammar (`team:`/`org:`/`host:` identifiers, no other schemes, no "anyone"). A member applies an assignment only when one of its own locally configured identifiers (`--audience-id` / `UNLIMITED_SKILLS_MCP_AUDIENCE`) is in this list. These are the SAME identifiers the bundle's own `audience` binds, so a misrouted assignment cannot smuggle a bundle past audience verification — the bundle itself still refuses with `bundle_audience_mismatch` (`-32018`). |
| `channel` | object | yes | The channel this assignment routes through: `name` plus `owner_key_id` — the full channel identity pair, so an assignment can never be satisfied by a same-named channel from a different owner. Required even in `pin` mode: the pin still names where the sha came from, for provenance and for the eventual return to `follow`. |
| `mode` | enum `follow` / `pin` | yes | `follow`: activate the channel's `current` (the member moves when the channel moves). `pin`: activate exactly `bundle_sha256` and ignore channel movement until the assignment is reissued. |
| `bundle_sha256` | 64-hex SHA-256 | only in `pin` mode | The pinned bundle's file SHA-256. Semantic load checks: required when `mode` is `pin`, **must be absent** when `mode` is `follow` (exactly one artifact owns the pointer — the channel — mirroring E13's "exactly one artifact owns selection"). |
| `issuer` | object | yes | Who issued the assignment: `key_id` + `display`, same shapes and same trust rule as everywhere else (only `key_id` + the trusted-keys file decide trust). Typically the channel owner; a fleet may use a separate assignment-issuing key (it must simply be in the members' trusted-keys file). |
| `revision` | integer ≥ 1 | yes | Monotonic per (issuer `key_id`, `audience`) revision, same anti-replay role as the channel's. |
| `issued_at` / `expires_at` | RFC 3339 UTC `Z` | yes | The assignment's validity window; `issued_at` strictly before `expires_at` (semantic load check). Expiry is mandatory for the same reason bundle expiry is (E13): an immortal routing statement would make revocation the only freshness mechanism. Recommended validity ≤ 90 days. Expiry semantics are deliberately mild — see decision 6. |
| `signature` | object | no (format) / **required for registered-tier distribution** (decision 1) | Same envelope, same canonicalization, `key_id` must equal `issuer.key_id` (semantic load check). |

## Decision table

Every distribution decision, answered explicitly:

| # | Decision | Answer |
| --- | --- | --- |
| 1 | **Are unsigned channels/assignments allowed?** | Mirrors the E13 decisions exactly. **MIT core: yes** — the schemas make `signature` optional, because routing files grant no capability: the worst an unsigned channel/assignment can do is point a member at a *signed* bundle that still has to pass full E14 verification (signature, expiry, CRL, audience, ceiling) against the member's own trust store. A small local team using a reviewed git repo as transport gets author-visibility from the repo itself. **Registered/business tier: signatures required, unconditionally** — any channel or assignment distributed through the registry/team sync MUST be signed, the sync machinery is forbidden from delivering unsigned routing files, and consumers in those contexts run with the signed-distribution policy (the future extension of `--require-signed-profiles` to routing files), refusing unsigned channels/assignments outright. Rationale: at fleet scale, routing manipulation (threat 19) is exactly the replay amplifier the signature kills. |
| 2 | **Who may publish to a channel?** | The channel owner's key and nothing else: a channel document is valid only when signed by `owner.key_id` (signature `key_id` must equal `owner.key_id` — same one-key rule as bundles). v1 scopes are unchanged from E13 "Key scopes": keys are flat entries in the trusted-keys file, one issuer per file in practice, no delegation, no multi-publisher channels, no threshold schemes. Per-channel ACLs and delegated publishing are registry-side concepts and are explicitly deferred (see "Deferred registry-side decisions"). |
| 3 | **Channel-follow vs sha-pin precedence?** | **Pin wins.** A `pin` assignment activates exactly its `bundle_sha256` and ignores channel movement until the assignment itself is reissued; `follow` tracks the channel's `current`. The two never mix inside one document: `pin` requires `bundle_sha256`, `follow` forbids it (semantic load check) — exactly one artifact owns the pointer. |
| 4 | **What happens when a channel points at a revoked bundle?** | **Fail-closed at the member, no exceptions.** The member's `library add`/`activate` runs the real E14 verification, and a CRL-revoked bundle refuses with `bundle_revoked` (`-32017`) no matter what the channel's history claims — the channel's `revoked`/`active` statuses are routing hints, never trust inputs. The member keeps its last-activated known-good bundle (the E20 library's append-only history and `rollback` are the mechanism; an already-active bundle is untouched because there is no hot reload). The publisher's fix is a channel rollback (decision under "Rollback"), not a member-side override — no `--allow-revoked` exists or will be added. |
| 5 | **Assignment expiry behavior?** | An expired assignment stops directing **new** activations: the member treats it as no-assignment (loud warning naming the expired file), does not follow further channel movement under it, and never auto-activates anything because of it. The **already-activated bundle keeps working until its own `expires_at`** — assignment expiry never deactivates a verified bundle and never flips a gateway to open mode. Rationale: the bundle's signed validity window is the capability clock; the assignment window only bounds how long the *routing statement* may be acted on. Operators refresh assignments on the same cadence as bundles (≤ 90 days recommended). |
| 6 | **Multiple assignments conflict resolution?** | When more than one unexpired assignment matches a member's identifiers, resolution is deterministic: (a) **most specific audience scheme wins** — `host:` beats `team:` beats `org:` (a host-specific statement is more deliberate than a team-wide one); (b) within the same specificity, **`pin` beats `follow`** (a pin is the more deliberate statement); (c) still tied, **highest `revision` wins**, then latest `issued_at`; (d) a residual exact tie is **refused loudly** — the member activates nothing new, keeps the last-activated bundle, and reports both files; ambiguity is an operator error to fix, never something a client guesses through. |
| 7 | **Offline grace period?** | **None needed, by construction.** Channels and assignments are local files; a member that cannot reach its transport simply keeps its current files and its last-activated bundle, which keeps verifying until the *bundle's* `expires_at` — the signed bundle expiry IS the grace bound, exactly as in E13/E20 today. No distribution-layer timer, no phone-home requirement, no "must sync within N days" rule exists or will be added to the local stack. (Whether the *registry* requires periodic entitlement re-checks for the hosted transport is a registry-side decision, deferred.) |
| 8 | **Do distribution files reserve new refusal codes?** | **No.** E23 is design-only and reserves nothing. The bundle-verification codes (`-32014`…`-32019`) keep their exact meanings; the future change that implements channel/assignment loading will reserve its own codes contiguously after the current family, with the same fail-closed refuse-nothing-silently rules. |

## Privacy boundary

Distribution files are routing metadata and contain, exhaustively:

- channel/assignment **names** and `revision` integers;
- bundle file **SHA-256 hashes** (content addresses of already-signed
  public artifacts);
- issuer/owner **key ids** and display names (public, non-secret — the
  same fields bundles already carry);
- **audience identifiers** (`team:`/`org:`/`host:` strings — the same
  bounded grammar the bundle `audience` already exposes);
- RFC 3339 **timestamps** and **status enums**;
- base64 **signature values** over public documents.

They never contain — and the schemas make unrepresentable via
`additionalProperties: false` and bounded grammars:

- tool names, tool arguments, tool results, or profile rule contents
  (profiles live inside the signed bundle, not in routing files);
- audit data of any kind (no usage, no call counts, no refusal history);
- member PII beyond the audience identifiers themselves (no emails, no
  usernames, no hostnames beyond what an operator deliberately encodes in
  a `host:` identifier they control);
- key material or private keys (key *ids* only, same stance as E13/E15);
- local filesystem paths.

**What the future registry sync may see:** the distribution files above
and the bundle files, as opaque signed blobs, plus whatever account/
entitlement identity the registered tier already requires for any hosted
interaction. **What it may not see, ever:** audit logs, tool arguments or
results, library state, activation history, trust-store contents, or any
telemetry about which member activated what when. Delivery is one-way:
the sync carries files down; nothing in this design defines an upload of
member-side state, and the privacy stance of
[privacy-and-telemetry.md](privacy-and-telemetry.md) is a precondition of
the sync gate, not something it may renegotiate.

## Entitlement gate

The tier split follows the existing product boundary
([product-editions.md](product-editions.md),
[plans-and-entitlements.md](plans-and-entitlements.md),
[public-core-boundary.md](public-core-boundary.md)):

- **Local file-based distribution stays MIT-free, indefinitely.** The
  schemas, the semantic rules, the conflict resolution, and the member-side
  library behavior in this document require no registration, no account,
  and no entitlement. A free team with a git repo gets the full
  channels-and-assignments model (signing optional per decision 1 but
  available at zero cost via the E19 DEV ceremony for pilots).
- **The hosted transport is the registered/business feature.** The
  entitlement check happens **at registry-sync time, in the future
  design**: uploading channels/assignments/bundles to unlimited.ai4.sale
  and having members fetch them through the registry requires an
  entitled plan, evaluated by the registry's existing entitlement concepts
  (plans, feature denials, org/team membership — the same machinery the
  registered tier already uses for other hosted features). E23 deliberately
  designs **no registry API** for this: which endpoint checks what, token
  shapes, seat mapping, and denial responses are all deferred (list below).
  The local consumer core never gains an entitlement check — a member who
  received the files by ANY transport can always use them; entitlement
  gates the *carrier*, never the verification.
- Signed distribution itself is gated organizationally, not
  cryptographically, in v1: production signing keys for registered/business
  issuing remain out of this repo entirely (the E13/E15/E19 boundary —
  DEV/FIXTURE keys only in the consumer core), so the registered tier's
  "signatures required" rule (decision 1) is enforceable at sync time
  without the core ever handling production key material.

## Rollback and offline behavior

- **Member offline:** nothing changes at all. The gateway keeps starting
  against the library's `active.bundle.json`, re-verifying it at every
  start (E20/E14); the last-activated bundle keeps working until its own
  `expires_at`, and every failure mode stays the documented fail-closed
  refusal. Distribution adds no liveness dependency.
- **Channel rollback:** the publisher publishes a **superseding record
  pointing back** — a new channel document revision whose history appends
  a new record re-publishing the previous good sha as `active`, marks the
  bad sha `superseded` (or `revoked`, mirroring an actual CRL action), and
  bumps `revision`. History is append-only across revisions; nothing is
  rewritten or deleted, so "what did `stable` point at last Tuesday" stays
  answerable from the file alone. Followers move back at their next
  refresh; pinned members were never affected. This is the channel-level
  twin of the E19 `ROLLBACK.json` metadata and the E20 `rollback`
  history walk.
- **Revocation propagation expectations:** revocation is authoritative in
  exactly one place — the E15 CRL on each member's trust store — and the
  channel's `revoked` status is a routing courtesy on top. The expected
  operator sequence for a bad bundle is: (1) `unlimited-skills mcp trust
  revoke --bundle-sha256 <sha>` distributed to members the same way trust
  updates already travel; (2) a channel rollback revision as above; (3)
  assignments reissued only if pins referenced the bad sha. Propagation is
  as fast as the team's transport; until a member receives the CRL update,
  its protection is the bundle's bounded expiry — the same residual-risk
  shape as E13 threat 15, unchanged. Online CRL delivery via the bundle's
  `registry_endpoint` remains a registry-gate hook, never fetched in v1.
- **Incident handling** for every underlying failure (revoked, expired,
  tampered, key-missing) stays the E18 runbook
  ([mcp-incident-runbook.md](mcp-incident-runbook.md)); distribution adds
  the two file-level recoveries above and nothing else.

## Trust and key rotation

- **Channel ownership across key rotation** uses the E13 overlap window
  unchanged: the owner generates a new key, members import it into their
  trusted-keys file alongside the old one (E15 `trust import` — explicit
  human/operator action, never automatic), and the next channel revision is
  signed with the new `key_id` and carries the new `owner.key_id`.
  Because consumers track channel identity as (`name`, owner key lineage
  in their own trust store), the handover is legible: a member accepts the
  re-keyed channel only when BOTH keys are in its trusted set during the
  overlap, which is precisely the window the operator controls. After the
  overlap, the old key expires (`not_after`) or is revoked as usual.
- **Owner key revocation freezes the channel, fail-closed.** When the
  owner's `key_id` lands in the CRL, every bundle it signed dies
  immediately (E14 rule, unchanged) AND every channel/assignment document
  it signed stops being acceptable. The channel is **frozen**: members
  keep their last-activated still-verifying bundle (if its own signing key
  survives) or fall into the documented fail-closed refusals (if not), and
  no further channel movement is honored **until a successor key from the
  member's trusted set re-signs the channel** at a higher revision. There
  is no automatic ownership transfer and no "any trusted key may adopt an
  orphaned channel" rule — adoption requires the operator to have imported
  the successor key, which is the same deliberate trust action that
  bootstrapped the channel in the first place.
- **Assignment issuers rotate identically.** An assignment signed by a
  revoked key is no longer acceptable; the no-new-activations posture of
  decision 5 applies (keep last-good, move on nothing).

## Threat-model additions

Numbered continuing E13's 14–18:

| # | Vector | Description | Impact | Mitigations |
| --- | --- | --- | --- | --- |
| 19 | **Routing manipulation** | An attacker on the transport swaps or edits channel/assignment files to point members at an older, wider, still-valid signed bundle, or at a different team's bundle. | Members activate a capability set the operator no longer intends — replay (E13 threat 15) amplified by automation. | Signed channels/assignments (mandatory in the registered tier, decision 1) make edits detectable; monotonic `revision` refuses regression to older routing documents; pins name an exact sha; the bundle's OWN verification still binds audience and expiry, so cross-team redirection dies at `bundle_audience_mismatch` (`-32018`) and stale bundles at `bundle_expired` (`-32016`); per-bundle CRL revocation kills a specific replayed sha outright. |
| 20 | **Stale/replayed routing files** | An old channel or assignment document (legitimately signed, since superseded) is re-delivered. | Members follow last month's pointer. | Monotonic `revision` per channel identity / assignment issuer+audience: consumers never move to a lower revision; assignment expiry bounds how long any routing statement may be acted on; bundle expiry bounds the damage even when routing replay succeeds. |
| 21 | **Channel-owner key compromise** | The owner's signing key is stolen; the attacker can mint valid channel revisions and assignments at will. | Fleet-wide redirection to attacker-chosen (but still validly signed) bundles — the routing twin of E13 threat 14. | Same containment as threat 14: key revocation via the CRL freezes the channel fail-closed (every document the key signed stops being acceptable); mandatory bundle expiry bounds the window; the attacker still cannot mint *bundles* without also holding a bundle-signing key the members trust; recovery is the documented successor-key re-signing, requiring an explicit member-side trust import the attacker does not control. |
| 22 | **Assignment audience confusion** | An assignment intended for team A is delivered to team B (mis-scoped audience, or a multi-team host applying the wrong file). | Wrong team follows the wrong channel. | Assignments bind the same `team:`/`org:`/`host:` identifiers the bundle audience already binds, and the bundle's own `-32018` audience check is unchanged underneath — a misrouted assignment can at worst point a member at a bundle that refuses to verify for it; the conflict-resolution order (decision 6) is deterministic and refuses residual ambiguity loudly instead of guessing. |

## Non-goals (the no-hosted-implementation proof)

E23 implements nothing and hosts nothing. Explicitly out of scope:

- **No hosted sync** — no service, no daemon, no scheduled fetch, no
  client sync implementation of any kind.
- **No registry API** — no endpoints, no request/response schemas, no
  authentication design for unlimited.ai4.sale; the file contracts above
  are the entire interface this design fixes.
- **No billing** and no entitlement-check implementation — the gate's
  *location* (registry-sync time) is decided; its mechanics are not.
- **No production signing keys** — unchanged E13/E15/E19 boundary;
  DEV/FIXTURE keys only anywhere near this repo.
- **No telemetry**, no usage reporting, no distribution-event upload.
- **No OAuth** and no identity provider integration.
- **No remote upstreams, no MCP resources/prompts, no hosted gateway** —
  the E07 future gates stay closed.
- **No new refusal codes, no verifier changes, no CLI changes** — E14/E15/
  E20 semantics are referenced, never modified; no runtime module is added
  or touched by E23.

### Deferred registry-side decisions

The next private-registry work inherits these open decisions, in rough
dependency order:

1. **Member identity and authentication** to the registry (token shapes,
   device vs user identity, OAuth or not) — explicitly not designed here.
2. **Entitlement-check mechanics** at sync time: which plan unlocks signed
   distribution, seat/audience-identifier mapping, denial semantics, and
   how `feature-denial` style responses surface in the client.
3. **Server-side publish authorization**: per-channel ACLs, delegated or
   multi-publisher channels, org-level namespace ownership of channel
   names (locally, identity is `name` + `owner.key_id`; the registry may
   want human-friendly uniqueness on top).
4. **Anti-rollback service guarantees**: whether the registry enforces
   revision monotonicity server-side (refusing stale uploads) in addition
   to the client-side refusal designed here.
5. **Online revocation delivery**: serving CRLs via the bundle's reserved
   `registry_endpoint`, push vs poll, and freshness expectations.
6. **Bundle/channel retention and history depth** on the hosted side
   (locally, history is bounded at 256 records per document).
7. **Periodic entitlement re-validation** for already-downloaded files,
   if any — bearing in mind the local rule that verification never gains
   an entitlement check (decision table, "Entitlement gate").
8. **Discovery surfaces**: listing channels available to an audience,
   without leaking other teams' channel names or membership.
9. **Production issuing ceremony** for registered/business signing keys —
   outside the consumer core by standing decision; the registry work must
   place it somewhere concrete.

## Relationship to the existing stack

| Layer | What E23 takes from it | What E23 must never change |
| --- | --- | --- |
| E13/E14 signed bundles | The capability artifact, its verification, canonicalization, refusal codes, audience grammar. | Verification semantics; the rule that a bundle is the ONLY thing that grants/narrows capability. |
| E15 trust store | The only trust anchor for bundle, channel, and assignment signatures alike; the CRL as authoritative revocation. | The store stays local, public-keys-only; sync never edits it. |
| E16/E17 | Dry-run and replay tooling members can point at a channel's `current` BEFORE following it (operator due diligence on a channel move). | Read-only stance. |
| E18 runbook | Recovery procedures for every refusal a routed bundle can produce. | Incident classes and codes. |
| E19 publishing | The ceremony that produces what channels point at; its `MANIFEST`/`ROLLBACK` metadata feeds publish records. | DEV-keys-only boundary; private-key hygiene. |
| E20 library | The member-side enforcement point: `add`/`activate`/`rollback` with re-verification is exactly where assignments land. | Verify-before-store, no quarantine, no hot reload, append-only history. |
| E21/E22 | The acceptance flow and the stabilization audit that any future implementing change must keep green. | Audit dimensions; the consistency invariants. |

## Threat model and abuse-case test plan (E25)

The full hosted/team distribution surface — this design's client side plus
the registry-side carrier contract (E24, private repo) — has a consolidated
adversarial threat model in
[mcp-distribution-threat-model.md](mcp-distribution-threat-model.md)
(threat classes `DT-01`…`DT-23`, consolidating and extending threats 19–22
above and E13's 14–18) and a matching abuse-case test plan in
[mcp-distribution-abuse-test-plan.md](mcp-distribution-abuse-test-plan.md)
(test ids, fixtures, pass criteria, owners, and a
threat→mitigation→test→owner traceability table).
`tests/test_mcp_distribution_threat_docs.py` keeps the two documents and
their refusal-code citations consistent. The future implementation of
hosted sync MUST land those abuse-case tests with the code — they are its
adversarial acceptance criteria, written before any hosted code exists.

## Fixture E2E harness (E26)

The whole planned flow above — fixture registry directory, signed channel
and assignment, entitlement-gated fetch, member-side verification, library
activation, gateway resolution, incident rollback, redacted audit — runs
end-to-end TODAY, with nothing hosted, in
`scripts/run-mcp-profile-distribution-fixture-e2e.py` (fixture mode only;
offline by construction — no network, no hosted calls, no production keys).
See [mcp-distribution-e2e-harness.md](mcp-distribution-e2e-harness.md) for
what the harness proves, what it deliberately does not, the per-step E25
`ABT-*` traceability, and how the future registry implementation swaps in
behind the same step interfaces. The machine report validates against
`schemas/mcp-distribution-e2e-report.schema.json` and is re-checked by
`scripts/verify-mcp-profile-distribution-e2e.py`.
