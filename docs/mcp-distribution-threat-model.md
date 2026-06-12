# MCP hosted/team distribution threat model and abuse cases (E25)

**Status: DESIGN (E25, docs/tests only — no implementation, nothing
hosted, no verifier or format change).** Branch lineage: this document
lives on `docs/v04-e25-mcp-distribution-threat-model-abuse-cases`, based
on `docs/v04-e23-mcp-bundle-distribution-design-v1` — i.e. the E23
client-side distribution design
([mcp-bundle-distribution.md](mcp-bundle-distribution.md)) on top of the
full E13–E22 local MCP profile stack. It is the adversarial acceptance
criteria for the WHOLE hosted/team distribution design: the E23 client
side AND the registry-side contract (E24, private repo). E24 concepts are
cited abstractly, exactly as that contract states them — its 20 registry
decisions, its reason-code table, and its forbidden-field denylist — with
no hostnames or internals beyond what the contract itself publishes to
its consumers.

The deliverable is this catalogue plus the consolidated abuse-case test
plan in
[mcp-distribution-abuse-test-plan.md](mcp-distribution-abuse-test-plan.md):
every threat class below names the abuse-case test that MUST exist in the
future implementation, written BEFORE any hosted code exists, so the
implementation inherits its adversarial tests instead of writing them
after the fact. `tests/test_mcp_distribution_threat_docs.py` keeps the
two documents and their refusal-code citations consistent.

## Scope and method

In scope: everything between a publisher's signing ceremony and a
member's activated bundle when the artifacts travel through team
transports or the future hosted registry — signed bundles (E13/E14),
trust store and CRL (E15), publishing (E19), library (E20), channels and
assignments (E23), and the registry carrier contract (E24: entities,
endpoints, envelopes, entitlement gate, reason codes). Out of scope, by
the standing E07 boundary: full host compromise (an attacker who can
rewrite the gateway invocation or the trust store with local write access
sits outside every signature scheme), and the gateway-internal vectors
already owned by the E07/E09 threat models.

Threat classes are numbered `DT-01`…`DT-23`. The ids are a self-contained
catalogue, deliberately NOT continuing the cross-document vector
numbering (E07 vectors 1–9, E09 10–13, E13 14–18, E23 19–22): this
catalogue *consolidates and extends* those vectors for the distribution
surface, and each entry cites the vectors and decisions it builds on.

Every entry carries six fields:

- **Attacker position** — one or more of the seven canonical positions
  below (the consistency test enforces the vocabulary);
- **Description** — what the attacker does;
- **Impact** — what they gain if no mitigation holds;
- **Existing mitigation** — the exact E13–E24 mechanism, by name:
  verification step, refusal code, schema closure, entitlement gate,
  registry decision;
- **Residual risk** — what remains true even with every mitigation in
  force;
- **Abuse-case test** — the given/when/then test(s) the implementation
  must ship, fixture-level only: ephemeral keys, temp directories, no
  hosted calls, no production key material — drillable exactly like the
  E18 incident drill. Test ids (`ABT-NNx`) are defined in the test plan.

## Attacker positions

| Position | Means and limits |
| --- | --- |
| malicious publisher | Holds a legitimate, trusted signing key and publisher authorization; can mint validly signed bundles/channels/assignments within their namespace. |
| compromised key | An attacker holds a stolen issuer/owner private key but NOT the publisher's account, infrastructure, or the members' trust stores. |
| malicious registry | The hosted carrier itself is hostile or compromised: can withhold, reorder, replay, or refuse files, and can lie in everything it serves. |
| network MitM | Controls the transport between client and registry (or the team's git remote / shared drive): observe, replay, substitute bytes in flight. |
| malicious teammate | An authenticated, entitled member of some org/team — can call consumer endpoints, request support bundles, and receive files legitimately. |
| compromised client | Attacker code runs with the member's file permissions on the consumer host, short of rewriting the gateway invocation (E07 boundary). |
| insider-operator | A registry/console operator with break-glass access but no issuer signing key. |

## Signature and downgrade threats

### DT-01 — Downgrade-to-unsigned (client side)

- **Attacker position:** network MitM; malicious teammate; compromised client
- **Description:** Replace a signed channel/assignment with an unsigned
  one, strip the `signature` member, or unset the bundle/policy flags,
  hoping the client quietly falls back to unsigned routing or unsigned
  profiles (the distribution twin of E13 threat 16).
- **Impact:** Total bypass: attacker-authored routing or profiles govern
  the member without any key ever being broken.
- **Existing mitigation:** E13 decision 6 — a stripped signature under
  the signed-required policy refuses with `-32015`
  `bundle_signature_invalid`, the same code as tampering, so stripping
  gains nothing; E13 decision 8 — missing keys/backends are fail-closed
  `-32019` `bundle_key_missing`, never fallback; E23 decision 1 — the
  registered tier runs the signed-distribution policy and refuses
  unsigned channels/assignments outright; bundle-vs-raw-file loading is
  distinguishable in the `profile_loaded` audit row.
- **Residual risk:** An attacker who can edit the gateway's own
  invocation can remove the policy flag itself — host-config integrity is
  the E07 trust boundary, explicitly out of scope. The MIT local tier
  legitimately accepts unsigned routing files (E23 decision 1), so the
  protection is policy-conditional by design.
- **Abuse-case test (ABT-01a, ABT-01b):** Given a member configured with
  the signed-distribution policy and a channel (and separately an
  assignment) whose `signature` member is stripped, when routing
  resolution loads the file, then the file is refused as unsigned, no
  unsigned fallback occurs, and the refusal is audited; given a signed
  bundle whose signature is stripped under `--require-signed-profiles`,
  when verification runs, then `-32015` — never open mode.

### DT-02 — Downgrade-to-unsigned (registry side)

- **Attacker position:** malicious publisher; malicious registry; network MitM
- **Description:** Get an unsigned artifact INTO the hosted pipeline
  (upload without an inner signature) or OUT of it (serve a delivery
  without the registry envelope or without the inner signature), so a
  permissive code path somewhere accepts it.
- **Impact:** The hosted carrier becomes a laundering point for unsigned
  capability or routing files at fleet scale.
- **Existing mitigation:** E24 decision 18, layered: publish endpoints
  refuse anything lacking a valid inner signature
  (`unsigned_artifact_rejected`, HTTP 422) so nothing unsigned is ever
  stored; the registry wrap schemas make the inner `signature` member
  REQUIRED (the one stated hardening delta over the public formats), so
  an unsigned document does not validate as a deliverable envelope; every
  trust-bearing response is wrapped in the registry's Ed25519 manifest
  envelope — no unsigned response variant exists to downgrade to; clients
  on the hosted transport refuse unsigned routing files regardless of
  what the carrier serves (E23 decision 1).
- **Residual risk:** A downgrade now requires breaking an Ed25519
  signature, not finding a permissive code path. A compromised registry
  can still withhold or replay — covered by DT-04/DT-23.
- **Abuse-case test (ABT-02a, ABT-02b):** Given a fixture publish
  validation with an unsigned channel document, when upload validation
  runs, then `unsigned_artifact_rejected` and nothing is stored; given a
  registry envelope fixture whose embedded document lacks the inner
  `signature`, when the client-side envelope parser loads it, then a
  schema load error — the envelope is unrepresentable, not merely
  refused.

### DT-03 — Malicious bundle from a legitimate publisher

- **Attacker position:** malicious publisher
- **Description:** A trusted publisher (or an insider using the
  publisher's legitimate ceremony) signs and distributes a hostile but
  formally valid bundle: maximally wide profiles, deceptive profile
  names, or a capability set the team would never knowingly accept.
- **Impact:** Members activate an over-wide capability set with perfect
  signatures and clean audit rows — trust in the publisher is exercised
  as designed, against the team.
- **Existing mitigation:** The E13 invariant that a verified bundle never
  WIDENS anything — the gateway config stays the outer ceiling, and
  upstreams not in the config can never spawn; the bundle's own
  `allowed_upstream_namespaces` ceiling is reviewable as one bounded list
  and rule escapes refuse with `-32018`; E16 `rollout-plan`/`doctor`
  dry-runs the exact capability surface BEFORE activation (operator due
  diligence on any channel move); `profile_loaded` provenance (issuer
  key id, bundle sha) makes the artifact attributable; containment is the
  E15 CRL (`-32017` `bundle_revoked`) plus an E23 channel rollback;
  registry-side, every publish is audited append-only.
- **Residual risk:** Irreducible: within the gateway's configured
  upstreams, a trusted publisher key defines the profile surface. The
  mitigation is bounded blast radius and attribution, not prevention.
- **Abuse-case test (ABT-03a, ABT-03b):** Given a validly signed bundle
  whose profiles claim every namespace in its ceiling, when it is
  activated against a gateway config with a narrower upstream set, then
  the effective surface never exceeds the gateway config and no
  unconfigured upstream spawns; given the same bundle, when
  `rollout-plan` runs before activation, then the report names the full
  visible/callable surface so the width is visible pre-activation.

## Replay and freshness threats

### DT-04 — Stale or replayed channel/assignment

- **Attacker position:** network MitM; malicious registry; malicious teammate
- **Description:** Re-deliver an older, legitimately signed, since
  superseded channel or assignment document (E23 threat 20) so members
  follow last month's pointer — replay of routing rather than of
  capability.
- **Impact:** Members activate a bundle the operator already moved away
  from; at fleet scale this is the replay amplifier of E23 threat 19.
- **Existing mitigation:** Monotonic `revision` per channel identity and
  per assignment (issuer, audience): consumers refuse to move to a lower
  revision; the registry additionally refuses stale uploads with
  `revision_regression` (HTTP 409, E24 decision 18); the assignment's
  mandatory validity window (`assignment_expired` on the hosted side)
  bounds how long any routing statement may be acted on; the bundle's own
  `expires_at` (`-32016` `bundle_expired`) bounds the damage even when
  routing replay succeeds.
- **Residual risk:** Replay of the CURRENT revision is a no-op; replay of
  an older revision against a consumer with no stored watermark (fresh
  install) succeeds until the assignment or bundle expires — the
  trust-on-first-use window, bounded by mandatory expiry.
- **Abuse-case test (ABT-04a, ABT-04b):** Given a consumer that has
  applied channel revision N, when revision N−1 (validly signed) is
  offered, then it is refused and the applied state is unchanged; given a
  registry fixture holding revision N, when revision N (equal) or N−1 is
  uploaded, then `revision_regression` and the stored document is
  untouched.

### DT-05 — Revoked-bundle replay

- **Attacker position:** network MitM; malicious registry; malicious teammate
- **Description:** Re-deliver a revoked but still unexpired bundle —
  directly, or by replaying a channel revision whose `current` still
  names it — hoping routing state outranks revocation.
- **Impact:** Withdrawn capability keeps running on members that accept
  the replay.
- **Existing mitigation:** Authoritative revocation is the member-side
  E15 CRL, enforced by the real E14 verification at `library add`,
  `activate`, and gateway startup: a CRL-listed sha refuses with `-32017`
  no matter what any channel's history status claims (E23 decision 4 —
  channel statuses are routing hints, never trust inputs; no
  `--allow-revoked` exists or will be added); registry-side, a bundle
  with status revoked refuses download with the `bundle_revoked` reason
  code and the channel rollback re-points followers.
- **Residual risk:** A member whose CRL update has not yet arrived keeps
  trusting the bundle until its `expires_at` — the E13 threat 15 residual
  shape, unchanged and accepted; propagation is as fast as the team's
  transport.
- **Abuse-case test (ABT-05a, ABT-05b):** Given a CRL listing the
  bundle's sha and a channel document whose history still marks that sha
  `active`, when the member activates via the channel, then `-32017` —
  the channel's claim changes nothing; given a registry fixture with the
  bundle status revoked, when a download authorization is evaluated, then
  the `bundle_revoked` reason code and no bytes are served.

### DT-06 — Revoked-while-offline abuse

- **Attacker position:** compromised client; network MitM
- **Description:** Keep a member deliberately offline (or block its
  transport) after a revocation lands registry-side, so the revoked
  assignment/bundle keeps governing the host as long as possible.
- **Impact:** Extends the lifetime of withdrawn capability on targeted
  hosts.
- **Existing mitigation:** Bounded by construction, not by liveness: E24
  decision 12 — revocation lands at next contact (`assignment_revoked`
  from the hosted side), there is no remote kill switch, and the blast
  radius until then is the bundle's own signed `expires_at` (`-32016`),
  exactly the E23 decision 7 grace bound; if the capability itself must
  die, the operator revokes the bundle and ships the CRL update the way
  trust updates already travel, refusing with `-32017` at the next
  activation; the E18 runbook owns the recovery sequence.
- **Residual risk:** A blocked member retains the full remaining bundle
  validity window — accepted and bounded; this is why recommended
  validity is ≤ 90 days and why expiry is mandatory (E13).
- **Abuse-case test (ABT-06a, ABT-06b):** Given an activated bundle and a
  registry-side revocation that has NOT been synced, when the member
  restarts offline, then the bundle still verifies (no phantom liveness
  dependency) until an injected fixture clock passes `expires_at`, after
  which `-32016`; given the CRL update then arrives, when the member next
  activates, then `-32017`.

### DT-07 — Key-rotation race

- **Attacker position:** compromised key; network MitM
- **Description:** Exploit the rotation overlap window: use the old
  (compromised) key to mint artifacts while both keys are trusted, or
  replay old-key-signed routing documents to members that have not yet
  removed the old key.
- **Impact:** Validly verifying attacker artifacts during the overlap;
  rotation intended to EXPEL the attacker instead extends their window.
- **Existing mitigation:** E13 rotation procedure — overlap is explicit
  and operator-controlled: per-key `not_after` in the trusted-keys file
  is enforced regardless of what artifacts claim; CRL `revoked_key_ids`
  kills every bundle, channel, and assignment a stolen key ever signed
  (`-32017`, immediate, no per-artifact hunting); a key absent or past
  `not_after` is `-32019`; E23 — a re-keyed channel is accepted only when
  BOTH keys are in the member's trusted set during the overlap, channel
  freeze on owner-key revocation, and successor adoption requires an
  explicit member-side `trust import`, which the attacker does not
  control.
- **Residual risk:** Between theft and revocation, old-key artifacts
  verify (inherent to signatures — E13 threat 14 residual); the overlap
  length is an operator decision, so a sloppy long overlap is an
  organizational failure no mechanism catches.
- **Abuse-case test (ABT-07a):** Given a trust store with old and new
  keys during an overlap, when the old key is revoked mid-overlap, then
  artifacts signed by the old key refuse with `-32017` while new-key
  artifacts keep verifying — and a channel revision signed by the revoked
  old key is no longer acceptable even at a higher revision.

## Routing and audience threats

### DT-08 — Channel-name squatting

- **Attacker position:** malicious publisher; malicious teammate
- **Description:** Publish a channel named `stable` (or any operator
  vocabulary word) under a different owner key, hoping members or
  operators bind to the name alone.
- **Impact:** Members follow an attacker-owned channel that looks
  canonical.
- **Existing mitigation:** Channel identity is the PAIR (`name`,
  `owner.key_id`) — a name alone can never be squatted (E23 channel
  format); assignments carry the full identity pair (`owner_key_id`
  required), so an assignment can never be satisfied by a same-named
  channel from a different owner; a channel document is valid only when
  signed by `owner.key_id` (`owner_key_mismatch` on the hosted side, E23
  decision 2 locally); the registry binds a channel name to its owning
  namespace at first publish — unique per namespace, identity pair
  underneath (E24 decision 7) — and discovery never shows other tenants'
  channel names (E24 decision 2).
- **Residual risk:** Human confusion across namespaces (two orgs each
  legitimately own a `stable`) remains a UI/operator concern; within one
  namespace, first-publish-wins is a governance rule, not cryptography.
- **Abuse-case test (ABT-08a, ABT-08b):** Given an assignment naming
  channel (`stable`, key A) and a delivered channel document (`stable`,
  key B) signed by trusted key B, when routing resolves, then the
  assignment is NOT satisfied and nothing activates; given a registry
  namespace where (`stable`, key A) exists, when a publish of (`stable`,
  key B) arrives for the same namespace binding, then it is refused as an
  identity conflict, not silently created alongside.

### DT-09 — Audience confusion / cross-team leak

- **Attacker position:** malicious registry; malicious teammate; insider-operator
- **Description:** Deliver team A's assignment or bundle to team B
  (mis-scoped audience, hostile carrier, or a multi-team host applying
  the wrong file), or use hosted surfaces to learn another team's
  channels, audiences, or membership.
- **Impact:** Capability cross-contamination between teams without any
  forgery (E13 threat 17, E23 threat 22), or organizational metadata
  leaking across tenants.
- **Existing mitigation:** Defense in depth ending at the member: the
  bundle's signed `audience` must intersect the member's locally
  configured identifiers — `-32018` `bundle_audience_mismatch` — so a
  misrouted assignment at worst points at a bundle that refuses to
  verify; assignments bind the same `team:`/`org:`/`host:` grammar;
  registry-side, listings are audience-scoped, cross-tenant surfaces
  carry audience SCHEMES only (E24 decision 2), membership is checked per
  request (`unauthorized_install`, `audience_mismatch` reason codes), and
  the support bundle and console are metadata-only (DT-21).
- **Residual risk:** Identifier hygiene is the operator's: a host that
  legitimately carries two teams' identifiers can activate either team's
  bundle; audience identifiers themselves are visible to the carrier (by
  design, they are the routing key).
- **Abuse-case test (ABT-09a, ABT-09b):** Given an assignment whose
  audience is `team:a` delivered to a member configured only with
  `team:b`, when routing resolves, then the assignment is ignored — and
  if forced, the bundle itself refuses `-32018`; given a registry listing
  fixture with two tenants, when tenant B lists channels and assignments,
  then no tenant-A channel name, audience identifier, or membership fact
  appears in any response.

### DT-10 — Assignment conflict manipulation

- **Attacker position:** malicious teammate; compromised key
- **Description:** Inject or reorder assignments so deterministic
  conflict resolution picks the attacker's preferred route — e.g. a
  `host:`-scoped pin that outranks the team-wide follow, or a forced
  exact tie to wedge the member.
- **Impact:** Steering one host (or the whole team) to an
  attacker-chosen, still-validly-signed bundle; or denial via engineered
  ambiguity.
- **Existing mitigation:** Every assignment must be signed by a key in
  the member's trusted set (E23 decision 1, registered tier) — injecting
  one requires a trusted key, which is DT-07's problem; resolution is the
  E23 decision 6 total order (most specific scheme wins, then pin over
  follow, then highest `revision`, then latest `issued_at`), so there is
  no nondeterminism to exploit; a residual exact tie is REFUSED loudly —
  the member activates nothing new, keeps last-good, and reports both
  files, so the wedge is visible, not silent; the bundle's own audience
  check still binds underneath.
- **Residual risk:** Any trusted issuer key can issue a `host:` pin that
  legitimately outranks team routing — the issuer key set must stay
  minimal, which is organizational; the tie-refusal is a small
  operator-visible DoS by construction (chosen over guessing).
- **Abuse-case test (ABT-10a, ABT-10b):** Given conflicting signed
  assignments at every rung (scheme specificity, pin vs follow, revision,
  `issued_at`), when resolution runs, then the documented order decides
  identically on every permutation of input file order; given two
  assignments tied on all four rungs, when resolution runs, then nothing
  new activates, the last-activated bundle is kept, and both files are
  named in the refusal.

## Registry-boundary threats

### DT-11 — Registry-side body exposure attempt

- **Attacker position:** malicious teammate; insider-operator
- **Description:** Use listings, summaries, access-checks, audit views,
  console pages, or any metadata surface to extract a profile bundle's
  BODY (profile rules, tool names, server configs) without passing the
  download authorization chain.
- **Impact:** The capability surface of a team leaks to anyone with
  metadata access, defeating the body/metadata split.
- **Existing mitigation:** E24 decisions 1, 2, 14, 15, 16, 20 as one
  closure: bodies live only in the content-addressed artifact root, never
  in a DB row, listing, or backup query path; the summary manifest's
  closed schema (`additionalProperties: false`) makes body fields
  unrepresentable, not merely omitted; audit events, console views, and
  support bundles carry identifiers, shas, statuses, and reason codes
  only; the body is reachable exclusively through the download endpoint
  after the full authorization chain (E24 decision 4).
- **Residual risk:** An authorized audience member reads the bundle by
  design — bundles are authenticated, not encrypted (E13 non-goal "no
  confidentiality"); metadata (names, shas, audiences, sizes) is
  legitimately visible to the tenant's own operators.
- **Abuse-case test (ABT-11a, ABT-11b):** Given the summary,
  access-check, and audit-event schemas, when a document carrying any
  body-bearing field is validated against them, then schema rejection —
  proven at the schema level, no handler needed; given a fixture registry
  state with a stored bundle, when every metadata surface
  (listing, access-check, audit, support block) is rendered, then a
  grep-proof finds no profile rule, tool name, or body fragment in any
  output.

### DT-12 — Forbidden-field smuggling

- **Attacker position:** compromised client; malicious registry; malicious publisher
- **Description:** Smuggle prompts, queries, tool arguments/results,
  telemetry, key material, or tokens through hosted payloads — upward in
  publish/consumer requests, or downward in responses a careless client
  would store or act on.
- **Impact:** The "no hosted query/prompt upload, delivery one-way down"
  privacy stance dies quietly; the carrier becomes a data channel.
- **Existing mitigation:** E24 decision 19 — every request/response
  schema is closed and bounded, so the fields do not EXIST to fill
  (`schema_invalid`, HTTP 422, before any handler logic); E24 decision 20
  — the explicit denylist (`prompt`, `tool_arguments`, `profile_rules`,
  `private_key`, `license_token`, `local_path`, … the contract's full
  list) is enforced recursively at the boundary on top of the schemas
  (`forbidden_field_rejected`, HTTP 422), so even a carelessly added
  future field trips the check; client-side, every loader in this repo
  is strict (`additionalProperties: false`) and unknown keys are load
  errors, so a response smuggling extra fields fails to parse.
- **Residual risk:** Covert channels inside PERMITTED fields (comment
  strings, display names, identifier choices) remain — bounded lengths
  and grammars cap the bandwidth; review owns the rest.
- **Abuse-case test (ABT-12a, ABT-12b):** Given fixture payloads with a
  denylisted property at the top level, nested three deep, and inside an
  array element, when boundary validation runs, then
  `forbidden_field_rejected` (or `schema_invalid` for unknown keys)
  for every placement, before any handler; given a registry envelope
  fixture with one extra undeclared key, when the client parses it, then
  a load error — the client never stores unrecognized hosted content.

### DT-13 — Oracle probing of private channels

- **Attacker position:** malicious teammate; compromised client
- **Description:** Probe the consumer endpoints with guessed shas,
  channel names, or foreign identifiers and use response DIFFERENCES
  (codes, shapes, timing) to enumerate other tenants' artifacts.
- **Impact:** Cross-tenant catalogue reconnaissance: which bundles,
  channels, and teams exist, and when they move.
- **Existing mitigation:** E24's anti-oracle rule: "does not exist" and
  "exists but outside your scope" are deliberately the SAME answer —
  `unknown_or_unauthorized` — so listing-by-error is impossible; the
  access-check returns `ok` only for a request that would actually be
  served right now; discovery surfaces are membership-scoped and carry
  schemes-only metadata across tenants (E24 decision 2).
- **Residual risk:** Timing side channels are not addressed by the
  contract (an implementation concern to measure); within the caller's
  OWN scope, enumeration is legitimate and complete by design.
- **Abuse-case test (ABT-13a):** Given a registry fixture with a foreign
  tenant's bundle and a nonexistent sha, when the same caller requests
  both via access-check and download authorization, then both answers are
  byte-identical in code and shape (`unknown_or_unauthorized`) — and the
  test asserts the two cases are indistinguishable, not merely both
  refused.

### DT-14 — Entitlement bypass attempts

- **Attacker position:** malicious teammate; compromised client
- **Description:** Reach the hosted carrier without the entitlement —
  forged plan claims, stale cached entitlements, or confused-deputy calls
  through an entitled teammate's install; conversely, argue the client
  into running entitlement checks on LOCAL verification.
- **Impact:** Free riders on the hosted transport (revenue boundary), or
  — the inverse failure — an entitlement check leaking into local
  verification and breaking the MIT core's guarantees.
- **Existing mitigation:** E24 decisions 5 and 11 — entitlement
  (`mcp_profile_sync` feature key) is resolved per request, server-side,
  through the existing precedence chain; no client-side cache is
  authoritative, so there is nothing stale to replay
  (`no_profile_sync_entitlement` on denial, honest diagnostics for the
  registered-community tier); the invariant running the other way: the
  local consumer core NEVER gains an entitlement check — files received
  by any transport always verify on their own merits (E23 entitlement
  gate, E24 decision 6 reaffirms it as a registry-side invariant).
- **Residual risk:** An entitled member can hand files to non-entitled
  members out of band — by DESIGN, that is the local tier working as
  specified, not a bypass; seat-level enforcement is organizational.
- **Abuse-case test (ABT-14a, ABT-14b):** Given a fixture install whose
  effective entitlement lacks `mcp_profile_sync`, when each consumer
  endpoint's authorization chain is evaluated, then denial with
  `no_profile_sync_entitlement` and no artifact bytes move; given the
  same files delivered as plain local files to an unentitled member, when
  the full local verify/activate path runs, then it succeeds with no
  entitlement consultation anywhere in the code path.

### DT-15 — Device-proof replay

- **Attacker position:** network MitM
- **Description:** Capture a valid signed device proof and replay it —
  same request again, or splice the proof onto a different method, path,
  or body.
- **Impact:** Impersonating an entitled install against the carrier:
  fetching another team's routing metadata or bundles with someone else's
  identity.
- **Existing mitigation:** E24 decision 11 adopts the existing proof
  machinery by name: the proof signs METHOD / PATH / BODY-SHA256 /
  TIMESTAMP / NONCE / INSTALL-ID / KEY-THUMBPRINT, the nonce is cached
  against reuse, production mode always requires it, and failures are
  `device_proof_invalid` (HTTP 401, pre-authentication, unsigned
  response); a missing/invalid bearer token is `not_registered`. Even a
  successful impersonation yields only carrier access — the bundle still
  refuses on the real member's behalf at E14 verification (audience,
  trust store).
- **Residual risk:** Replay within the nonce/timestamp freshness window
  against an implementation that skimps on the nonce cache — which is
  exactly what the abuse test pins; proof-key theft from the install is
  the compromised-client case (E07 boundary).
- **Abuse-case test (ABT-15a):** Given a fixture proof validator and a
  previously accepted proof, when the identical proof is presented again,
  then `device_proof_invalid`; when the same proof is presented with a
  different path or body hash, then `device_proof_invalid` — both as 401
  pre-authentication denials carrying no signed envelope.

## Identity, role, and operator threats

### DT-16 — Publisher role escalation

- **Attacker position:** malicious teammate; compromised key
- **Description:** Publish without the publisher role (signature but no
  authorization), publish with the role but the wrong key (authorization
  but no signature), or publish into ANOTHER namespace's channel or
  audience scope.
- **Impact:** Unauthorized parties move a team's routing, or a legitimate
  publisher's reach silently extends across namespaces.
- **Existing mitigation:** E24 decision 7's dual gate — BOTH the
  `profile_policy` publisher role for the target namespace AND a valid
  inner signature by the registered owner/issuer key, always: role
  without signature is `unsigned_artifact_rejected` or
  `owner_key_mismatch`; signature without role is
  `publisher_not_authorized` (HTTP 403); audience identifiers in
  published assignments are constrained to the publisher's org/team
  scope; every publish and rejection is an append-only audit event.
- **Residual risk:** An insider holding both the role and the key is
  DT-03 (fully trusted publisher) — attribution and rollback, not
  prevention; `profile_policy` governance quality is organizational.
- **Abuse-case test (ABT-16a, ABT-16b):** Given a correctly signed
  channel document from a caller WITHOUT the publisher role, when publish
  validation runs, then `publisher_not_authorized` and nothing is stored;
  given a caller WITH the role whose document is signed by a key that
  does not match the channel identity's bound owner key, then
  `owner_key_mismatch` — and an assignment naming an audience outside the
  publisher's scope is refused, not narrowed silently.

### DT-17 — Break-glass abuse

- **Attacker position:** insider-operator
- **Description:** Use console break-glass powers to steer a fleet:
  re-point a channel, substitute a bundle, resurrect a revoked artifact,
  or mass-revoke to take a team down.
- **Impact:** A single operator (or stolen console credential) controls
  what teams run — the centralization failure this design exists to
  prevent.
- **Existing mitigation:** E24 decision 17's deliberate asymmetry: the
  registry can always NARROW, never STEER — break-glass actions change
  registry-side status only (revoke an assignment row, set a bundle
  revoked), which halts delivery but cannot move anyone to a different
  bundle, because movement requires a channel republication signed by a
  key members trust, which the registry does not hold (the registry holds
  no private key material — E24 security invariants); console actions sit
  behind the double flag + admin key + explicit confirm + reason +
  request id regime and land in the audit stream as
  `mcp_profile_admin_override`; clients verify everything locally, so a
  steering attempt without a valid inner signature dies at `-32015`.
- **Residual risk:** Availability: an insider CAN mass-revoke (audited,
  reversible by status); they cannot escalate capability. Console
  credential hygiene is operational.
- **Abuse-case test (ABT-17a):** Given the full set of break-glass
  operations in the admin contract, when each is enumerated against the
  fixture state, then every reachable post-state is a NARROWING of
  delivery (fewer artifacts served, never different ones) — and no
  operation exists that alters a stored channel document's bytes,
  `current` pointer, or serves a sha the signed channel does not name.

## Operations and recovery threats

### DT-18 — CRL outage exploitation

- **Attacker position:** compromised client; malicious teammate
- **Description:** Make the declared CRL unreadable (delete, corrupt,
  permission-break) at the exact moment a revoked bundle is replayed —
  revocation silently stops working while everything else verifies (E13
  threat 18); or use the outage purely as denial.
- **Impact:** Revoked capability runs again, or the team is wedged.
- **Existing mitigation:** Fail-closed by decision: a
  declared-but-unreadable CRL refuses with `-32017` — "cannot prove
  not-revoked" never degrades to "trusted"; the E18 drill scenario
  rehearses exactly this (`crl_outage`) including the recovery — rebuild
  the CRL from the append-only revocation history in the store metadata
  (never hand-edit), `trust doctor` confirms, restart; store writes are
  atomic; deleting the bundle's `revocation` member instead is a
  signature break (`-32015`), the wrong fix by construction.
- **Residual risk:** The outage is a DoS until repaired (chosen over the
  alternative); a bundle issued with NO `revocation` member never
  consults a CRL — its freshness rests on mandatory expiry alone (opt-in
  v1 revocation, E13).
- **Abuse-case test (ABT-18a):** Given a bundle declaring a CRL and a
  revoked sha in it, when the CRL file is made unreadable and the revoked
  bundle is replayed, then `-32017` (fail-closed, NOT a pass); when the
  CRL is rebuilt from the metadata history via the documented recovery,
  then the good bundle verifies again AND the revoked sha still refuses.

### DT-19 — Last-good poisoning

- **Attacker position:** compromised client; malicious teammate
- **Description:** Corrupt the member's "keep last-good" safety net:
  tamper with the library's `active.bundle.json` pointer copy, swap a
  content-addressed entry, or steer `rollback` onto an attacker-chosen or
  since-revoked history entry.
- **Impact:** The fallback everyone trusts during incidents becomes the
  attack vehicle — fail-closed states recover INTO a poisoned bundle.
- **Existing mitigation:** The pointer grants nothing by itself: the
  gateway re-verifies the active bundle ITSELF at every startup (E20 +
  E14), so a tampered pointer copy is `-32015` at next start, not a
  silent activation; library storage is immutable and content-addressed —
  swapped bytes no longer match their sha; `add`, `activate`, AND
  `rollback` each re-run the full verification at action time precisely
  because keys and the CRL may have changed — a rollback target that has
  since been revoked refuses `-32017` instead of activating; the
  activation history is append-only.
- **Residual risk:** Full local write access (rewriting the library AND
  the trust store AND the invocation together) is the E07 host boundary —
  out of scope by standing decision.
- **Abuse-case test (ABT-19a, ABT-19b):** Given a library whose active
  pointer copy is tampered after activation, when the gateway starts,
  then `-32015` fail-closed refuse-all, never the tampered content; given
  a rollback target revoked after it was first activated, when `rollback`
  selects it, then `-32017` and the rollback does not complete.

### DT-20 — Retention-expiry denial

- **Attacker position:** malicious registry; insider-operator
- **Description:** Exploit retention to destroy recovery options: age
  out or garbage-collect the prior-good bundle so a channel rollback has
  no fetchable target (`retention_expired`), or stall an incident until
  the window lapses.
- **Impact:** During an incident, the team cannot move BACK — rollback
  exists on paper but the bytes are gone.
- **Existing mitigation:** E24 decision 13's retention guarantee: a
  bundle body stays downloadable while referenced by ANY record of any
  stored channel history (history is append-only, bounded at 256) or any
  unexpired assignment pin, plus a 90-day grace after the last reference
  disappears — so a rollback target named by history is retained by
  construction; revoked bundles are retained (not served) for audit;
  independently, the member's own E20 library holds last-good locally, so
  recovery never REQUIRES the carrier (E23 offline-first).
- **Residual risk:** A sha outside every history and pin does expire from
  the carrier after grace — re-fetch impossible, local copies are the
  only source; hosted retention is a guarantee the future implementation
  must actually enforce, hence the test.
- **Abuse-case test (ABT-20a, ABT-20b):** Given a fixture retention
  evaluator, when shas are (a) referenced by a stored history record, (b)
  pinned by an unexpired assignment, (c) unreferenced with grace elapsed,
  then (a) and (b) remain downloadable and (c) refuses with
  `retention_expired`; given a member with a populated local library and
  NO reachable carrier, when the E18-style rollback recovery runs, then
  it completes entirely from local state.

### DT-21 — Support-bundle leak

- **Attacker position:** malicious teammate; insider-operator
- **Description:** Use the support/diagnostics path as exfiltration:
  request a support bundle (or coax a member into sharing one) hoping it
  embeds bundle bodies, profile rules, tokens, keys, or local paths.
- **Impact:** The escape hatch built for debugging quietly becomes the
  widest data channel in the design.
- **Existing mitigation:** E24 decision 16: the support block carries
  ONLY aggregate counts, identifiers, content addresses, statuses, reason
  codes, and the redacted entitlement decision shape, with explicit
  redaction flags proving exclusion; bodies, rules, tool names/arguments/
  results, prompts, tokens, proofs, key material, env values, and local
  paths are excluded BY SCHEMA, and the decision 20 denylist applies to
  the support payload like every other payload; the same stance the E11
  audit redaction floor already enforces client-side.
- **Residual risk:** The metadata itself (channel names, key ids, shas,
  denial codes) is visible to whoever holds the support bundle — that is
  its purpose; handling discipline for support artifacts is
  organizational.
- **Abuse-case test (ABT-21a):** Given a fixture state rich in would-leak
  content (profiles with distinctive rule strings, fake tokens, fake key
  material, local paths), when the `mcp_profiles` support block is
  generated, then a leak-grep over the rendered output finds none of the
  planted markers, every redaction flag is present, and the block still
  answers the operator question (counts, pointers, last denial codes).

## Evolution and consistency threats

### DT-22 — Schema-evolution downgrade

- **Attacker position:** malicious registry; network MitM; malicious publisher
- **Description:** Exploit format evolution: present a document or
  envelope with an unexpected `channel_version`/`assignment_version`/
  envelope `schema_version` (older, newer, or absent), or skew the
  vendored copy of the public formats, hoping some parser is permissive
  across versions and drops a check.
- **Impact:** A "version-flexible" parser becomes the downgrade path that
  decision-level mitigations never see.
- **Existing mitigation:** Version pinning by `const`: the public formats
  pin `channel_version: 1` and `assignment_version: 1`, the registry
  envelopes pin `schema_version: 1` — any other value fails schema
  validation (client: `-32014` `profile_invalid` for a malformed bundle
  artifact, load error for routing files; registry: `schema_invalid`);
  the E24 pre-v0.6 policy requires owner approval plus a consistency-test
  re-run for ANY field addition or semantic change, and the private repo
  must re-vendor and re-review the hardening delta when the public
  formats rev; after v0.6, new majors get NEW manifest types instead of
  in-place mutation, so old parsers refuse rather than misread.
- **Residual risk:** Pre-v0.6 best-effort compatibility means a
  coordinated rev can still ship a mistake — the gate is review plus the
  consistency tests, not cryptography; version refusal is an availability
  cost taken deliberately (fail-closed over fail-flexible).
- **Abuse-case test (ABT-22a, ABT-22b):** Given channel and assignment
  documents identical to valid fixtures except `*_version: 2` (and
  separately a missing version member), when the client loads them, then
  load errors — no field of the document is honored; given a registry
  envelope with an unexpected `schema_version`, when boundary validation
  runs, then `schema_invalid` before any handler logic.

### DT-23 — Monotonicity bypass

- **Attacker position:** malicious registry; network MitM; compromised client
- **Description:** Defeat the anti-replay watermark itself rather than
  replaying old files: wipe or reset the client's stored
  highest-revision-seen state, abuse a fresh install's empty watermark,
  publish two different documents at the SAME revision, or confuse
  watermarks across channel identities (same name, different owner).
- **Impact:** The monotonic `revision` defense of DT-04 silently stops
  binding, reopening routing replay at fleet scale.
- **Existing mitigation:** Two independent enforcement points: the
  registry refuses any upload whose `revision` is not STRICTLY greater
  than the stored revision for the same identity — equal is refused, so
  two same-revision documents cannot both be stored
  (`revision_regression`, E24 decision 18, closing the E23 deferred
  anti-rollback question server-side); the client tracks its watermark
  PER channel identity pair and per assignment (issuer, audience), so
  same-name-different-owner channels cannot cross-contaminate; even a
  fully bypassed watermark is bounded by the assignment validity window
  and the bundle's `expires_at` — replay never outlives the signed
  clocks.
- **Residual risk:** A fresh client (no watermark) accepts the highest
  currently valid revision it is shown — trust-on-first-use, bounded by
  expiry; client watermark state is local file state, so a compromised
  client can wipe its OWN protection (E07 boundary, self-harm only —
  other members' watermarks are unaffected).
- **Abuse-case test (ABT-23a, ABT-23b):** Given a registry fixture
  holding (identity, revision 5), when uploads arrive at revision 5 and
  revision 4, then both refuse `revision_regression` and the stored
  document is byte-identical to before; given a client that applied
  revision 5 of (`stable`, key A), when offered revision 3 of (`stable`,
  key A) and revision 1 of (`stable`, key B), then the first is refused
  as regression while the second is evaluated as a DIFFERENT channel
  identity — watermarks never collide across owners.

## Highest residual risks (ranked)

The mitigations above leave five risks that no mechanism in E13–E24
removes; the implementation and its operators must carry them knowingly:

1. **Trusted-publisher betrayal (DT-03, DT-16):** a legitimate key plus a
   legitimate role IS the capability — everything else only bounds blast
   radius (gateway-config ceiling, expiry, attribution, rollback).
2. **Compromise-to-revocation window (DT-07, DT-05, DT-06):** between key
   theft and CRL propagation, attacker artifacts verify everywhere; the
   only hard bound is mandatory bundle expiry — keep validity short.
3. **Offline staleness as a feature (DT-06, DT-23):** no remote kill
   switch and no liveness timer means a deliberately isolated host runs
   withdrawn capability until the signed clocks expire — accepted by
   design, and invisible to the registry (no activation telemetry).
4. **Host-local trust boundary (DT-01, DT-19, DT-23):** every client-side
   defense assumes the gateway invocation, trust store, and library are
   not attacker-writable; full local compromise defeats the scheme by
   standing E07 decision, not by oversight.
5. **Operator availability power (DT-17, DT-20):** the registry can
   always narrow — an insider or a hostile carrier can deny a fleet
   (mass-revoke, withhold, retention games) even though they can never
   steer it; the recovery story is local last-good plus the E18 runbook.

## Non-goals

- No implementation: no test code beyond the docs-consistency gate, no
  verifier change, no schema change, no new refusal codes reserved.
- No re-statement of the gateway-internal threat models (E07 vectors 1–9,
  E09 10–13) — they hold unchanged underneath.
- No production keys, hosted calls, or network access in any abuse test
  this catalogue demands: every test is fixture-level by construction.
- No quantitative risk scoring — ordering in "Highest residual risks" is
  by argued severity, not a numeric methodology.

## See also

- [mcp-distribution-abuse-test-plan.md](mcp-distribution-abuse-test-plan.md)
  — the consolidated test plan: test ids, fixtures, pass criteria,
  owners, and the threat→mitigation→test→owner traceability table.
- [mcp-bundle-distribution.md](mcp-bundle-distribution.md) — the E23
  client-side design this catalogue covers.
- [mcp-signed-profile-bundles.md](mcp-signed-profile-bundles.md) — the
  E13 bundle threat model (vectors 14–18) this catalogue extends.
- [mcp-incident-runbook.md](mcp-incident-runbook.md) — the E18 drill
  machinery the abuse tests reuse.
