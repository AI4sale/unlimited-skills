# MCP distribution abuse-case test plan (E25)

**Status: DESIGN (E25, docs/tests only — no implementation).** Branch
lineage: `docs/v04-e25-mcp-distribution-threat-model-abuse-cases`, based
on `docs/v04-e23-mcp-bundle-distribution-design-v1` (the E23 client-side
distribution design on the full E13–E22 local stack). This is the
consolidated test plan for the threat catalogue in
[mcp-distribution-threat-model.md](mcp-distribution-threat-model.md):
per threat class, the abuse-case test ids, the fixtures they need, the
pass criteria, and which layer owns each test. The future implementation
of hosted/team distribution (client sync AND the registry contract, E24)
MUST land these tests with the code — they are its adversarial
acceptance criteria, written first.

## How to read this plan

- **Test ids** follow `ABT-NNx`: the two digits match the threat class
  (`ABT-04a` belongs to `DT-04`), the letter distinguishes tests within
  the class. `tests/test_mcp_distribution_threat_docs.py` enforces the
  correspondence and the traceability table below.
- **Owner** is one of exactly three layers:
  - **client suite** — pytest in THIS repo, against the real E14/E15/E20
    code paths plus the future client routing-resolution module;
  - **future registry suite** — the private registry repo's fixture-mode
    tests against the E24 contract (validators, authorization-chain
    evaluators, schema gates — no endpoint code required to start);
  - **end-to-end (E21-style)** — a fixture-mode workflow script in the
    style of `scripts/run-mcp-operator-acceptance.py`, composing real
    layers in one temp-directory flow.
- **Execution rules**, non-negotiable for every test below: fixture-mode
  only — ephemeral keys generated per run and discarded, private temp
  directories, NO hosted calls, NO network, NO production key material,
  NO touching the real library root, trust store, or audit log. Exactly
  the E18 drill stance. Where real Ed25519 is unavailable the E18
  TEST-ONLY backend substitution applies unchanged.

## Fixture machinery glossary (reused, by name)

| Fixture | Source | Reused for |
| --- | --- | --- |
| `DrillIssuer` | `scripts/run-mcp-bundle-incident-drill.py` (E18) | Ephemeral keypair + signing of bundles, channels, assignments in abuse fixtures. |
| `ScenarioContext` | E18 drill | Per-scenario temp directory, trust store, CRL plumbing for inject→assert→recover flows. |
| `base_bundle` / `write_json` | E18 drill | Known-good bundle/document construction before each abuse mutation. |
| `_FakeHmacBackend` | E18 drill | TEST-ONLY signature backend when `cryptography` is absent. |
| `AcceptanceContext` / `step_*` | `scripts/run-mcp-operator-acceptance.py` (E21) | End-to-end flows: keygen → trust import → publish → library add → activate → incident → rollback. |
| `resolve_bundle_state` / `canonical_bundle_bytes` | `unlimited_skills/mcp/bundles.py` (E14/E19) | The REAL verification — abuse tests assert its codes, never reimplement it. |
| `channel_load_errors` / `assignment_load_errors` + minimal validator | `tests/test_mcp_distribution_schemas.py` (E23) | Routing-file semantic rules and closed-schema rejection checks. |
| channel/assignment examples | `examples/mcp/bundle-{channel,assignment}.example.json` (E23) | Valid baselines that each abuse fixture mutates one fact at a time. |
| registry contract fixtures | E24 private repo: envelope schemas, examples, the publish-validation and authorization-chain evaluators its consistency test already models | Registry-owned tests; named abstractly here — the contract doc is their source of truth. |

## Per-threat tests

### DT-01 — Downgrade-to-unsigned (client side)

- **Test IDs:** `ABT-01a`, `ABT-01b`
- **Fixtures:** `DrillIssuer`-signed channel + assignment with the
  `signature` member stripped post-signing; a `base_bundle` stripped
  under `--require-signed-profiles`; `ScenarioContext` trust store.
- **Pass criteria:** `ABT-01a` — stripped routing files under the
  signed-distribution policy are refused, nothing activates, refusal
  audited; `ABT-01b` — stripped bundle refuses `-32015`
  (`bundle_signature_invalid`), identical to the tampered-byte case
  (stripping gains nothing over tampering), never open mode.
- **Owner:** client suite

### DT-02 — Downgrade-to-unsigned (registry side)

- **Test IDs:** `ABT-02a`, `ABT-02b`
- **Fixtures:** unsigned channel document against the publish-validation
  evaluator; registry envelope example with the inner `signature` member
  deleted, against the E24 wrap schemas.
- **Pass criteria:** `ABT-02a` — publish validation refuses
  `unsigned_artifact_rejected`; no storage write occurs; `ABT-02b` — the
  envelope fails schema validation (inner signature is REQUIRED in the
  wrapped copies), proving unsigned delivery is unrepresentable.
- **Owner:** future registry suite (`ABT-02a`); client suite (`ABT-02b`,
  parsing the vendored envelope example)

### DT-03 — Malicious bundle from a legitimate publisher

- **Test IDs:** `ABT-03a`, `ABT-03b`
- **Fixtures:** `DrillIssuer` bundle claiming every namespace in its
  ceiling; gateway config with a strictly narrower upstream set; E16
  `rollout-plan` invocation via `AcceptanceContext`.
- **Pass criteria:** `ABT-03a` — effective visible/callable surface
  never exceeds the gateway config; no unconfigured upstream spawns;
  `ABT-03b` — `rollout-plan` reports the full surface BEFORE activation
  (the operator due-diligence hook works on a hostile-but-valid bundle).
- **Owner:** client suite (`ABT-03a`); end-to-end (E21-style)
  (`ABT-03b`)

### DT-04 — Stale or replayed channel/assignment

- **Test IDs:** `ABT-04a`, `ABT-04b`
- **Fixtures:** two signed channel revisions N−1 and N from the same
  `DrillIssuer` identity; client watermark state seeded at N; registry
  fixture store seeded at N.
- **Pass criteria:** `ABT-04a` — client refuses to move from N to N−1;
  applied state unchanged; an expired assignment (`assignment_expired`
  hosted-side analogue) directs no new activation; `ABT-04b` — registry
  publish of N−1 (and of N, equal) refuses `revision_regression`
  (HTTP 409) and the stored document is untouched.
- **Owner:** client suite (`ABT-04a`); future registry suite (`ABT-04b`)

### DT-05 — Revoked-bundle replay

- **Test IDs:** `ABT-05a`, `ABT-05b`
- **Fixtures:** E18 `scenario_revoked_bundle` machinery extended with a
  channel document whose history still marks the revoked sha `active`;
  registry fixture with bundle status revoked.
- **Pass criteria:** `ABT-05a` — activation via the lying channel
  refuses `-32017` (`bundle_revoked` client-side); the channel status is
  demonstrably never a trust input; `ABT-05b` — download authorization
  answers the `bundle_revoked` reason code; no bytes served.
- **Owner:** client suite (`ABT-05a`); future registry suite (`ABT-05b`)

### DT-06 — Revoked-while-offline abuse

- **Test IDs:** `ABT-06a`, `ABT-06b`
- **Fixtures:** `AcceptanceContext` flow with activation completed, then
  a registry-side revocation that is deliberately NOT synced; injected
  fixture clock (the E18 expiry-injection pattern).
- **Pass criteria:** `ABT-06a` — offline restarts keep verifying (no
  hidden liveness dependency) until the injected clock passes
  `expires_at`, then `-32016` (`bundle_expired`); `ABT-06b` — once the
  CRL update lands via `trust revoke`, next activation refuses `-32017`;
  hosted-side the assignment answers `assignment_revoked` at next
  contact.
- **Owner:** end-to-end (E21-style) (`ABT-06a`); client suite
  (`ABT-06b`)

### DT-07 — Key-rotation race

- **Test IDs:** `ABT-07a`
- **Fixtures:** `ScenarioContext` trust store holding old + new keys
  (the E18 rotation-overlap pattern); channel revisions signed by each;
  CRL listing the old `key_id` mid-overlap.
- **Pass criteria:** old-key artifacts (bundle AND channel AND
  assignment) refuse `-32017` after key revocation while new-key
  artifacts verify; a higher-revision channel signed by the revoked key
  is not honored; missing/expired key remains `-32019`
  (`bundle_key_missing`).
- **Owner:** client suite

### DT-08 — Channel-name squatting

- **Test IDs:** `ABT-08a`, `ABT-08b`
- **Fixtures:** assignment naming (`stable`, key A); trusted channel
  (`stable`, key B); registry namespace fixture with (`stable`, key A)
  bound at first publish.
- **Pass criteria:** `ABT-08a` — the assignment is not satisfied by the
  same-named other-owner channel; nothing activates; `ABT-08b` — a
  publish binding (`stable`, key B) into the same namespace refuses as an
  identity conflict (`owner_key_mismatch` against the bound owner key).
- **Owner:** client suite (`ABT-08a`); future registry suite (`ABT-08b`)

### DT-09 — Audience confusion / cross-team leak

- **Test IDs:** `ABT-09a`, `ABT-09b`
- **Fixtures:** assignment for `team:a` delivered to a member configured
  `team:b`; two-tenant registry listing fixture.
- **Pass criteria:** `ABT-09a` — the misrouted assignment is ignored;
  forcing the bundle anyway refuses `-32018`
  (`bundle_audience_mismatch`); `ABT-09b` — tenant B's listings,
  access-checks (`audience_mismatch`, `unauthorized_install`,
  `unknown_or_unauthorized` as applicable), and support block contain no
  tenant-A channel name, audience identifier, or membership fact.
- **Owner:** client suite (`ABT-09a`); future registry suite (`ABT-09b`)

### DT-10 — Assignment conflict manipulation

- **Test IDs:** `ABT-10a`, `ABT-10b`
- **Fixtures:** signed assignment sets exercising every rung of the E23
  decision 6 order (scheme specificity, pin vs follow, revision,
  `issued_at`), in every input-order permutation; one engineered exact
  tie.
- **Pass criteria:** `ABT-10a` — resolution is identical across input
  permutations and matches the documented total order; `ABT-10b` — the
  exact tie refuses loudly: nothing new activates, last-activated bundle
  kept, both files named in the report.
- **Owner:** client suite

### DT-11 — Registry-side body exposure attempt

- **Test IDs:** `ABT-11a`, `ABT-11b`
- **Fixtures:** the E24 summary/access-check/envelope schemas; a fixture
  registry state seeded with a bundle whose profile rules carry
  distinctive marker strings.
- **Pass criteria:** `ABT-11a` — documents carrying body-bearing fields
  fail schema validation (closed schemas, unrepresentable); `ABT-11b` —
  a leak-grep over every rendered metadata surface (listing,
  access-check, audit events, support block) finds no marker string.
- **Owner:** future registry suite

### DT-12 — Forbidden-field smuggling

- **Test IDs:** `ABT-12a`, `ABT-12b`
- **Fixtures:** request/response payloads planting each denylisted
  property name (E24 decision 20) at top level, nested, and inside array
  items; a registry envelope example with one extra undeclared key.
- **Pass criteria:** `ABT-12a` — every placement refuses
  `forbidden_field_rejected` (or `schema_invalid` for unknown keys)
  before handler logic; `ABT-12b` — the client refuses to parse an
  envelope with an undeclared key (strict loader, load error).
- **Owner:** future registry suite (`ABT-12a`); client suite
  (`ABT-12b`)

### DT-13 — Oracle probing of private channels

- **Test IDs:** `ABT-13a`
- **Fixtures:** registry fixture with a foreign tenant's bundle plus a
  truly nonexistent sha; one caller identity.
- **Pass criteria:** access-check and download authorization answer the
  two cases with byte-identical code and shape
  (`unknown_or_unauthorized`); `ok` appears only for a request that
  would actually be served.
- **Owner:** future registry suite

### DT-14 — Entitlement bypass attempts

- **Test IDs:** `ABT-14a`, `ABT-14b`
- **Fixtures:** fixture install lacking the `mcp_profile_sync` feature
  key; the same channel/assignment/bundle files delivered as plain local
  files to an unentitled member (`AcceptanceContext`).
- **Pass criteria:** `ABT-14a` — every consumer authorization chain
  denies with `no_profile_sync_entitlement`; no artifact bytes move;
  `ABT-14b` — the full local verify/activate path succeeds with zero
  entitlement consultation (the invariant that entitlement gates the
  carrier, never verification).
- **Owner:** future registry suite (`ABT-14a`); client suite
  (`ABT-14b`)

### DT-15 — Device-proof replay

- **Test IDs:** `ABT-15a`
- **Fixtures:** fixture proof validator with nonce cache; one accepted
  proof, then replays (identical; different path; different body hash).
- **Pass criteria:** every replay refuses `device_proof_invalid` as an
  HTTP 401 pre-authentication denial with no signed envelope; a missing
  bearer token refuses `not_registered`.
- **Owner:** future registry suite

### DT-16 — Publisher role escalation

- **Test IDs:** `ABT-16a`, `ABT-16b`
- **Fixtures:** `profile_policy` fixture with and without the publisher
  role; documents signed by the bound owner key and by a different
  trusted key; an assignment naming an out-of-scope audience.
- **Pass criteria:** `ABT-16a` — signature without role refuses
  `publisher_not_authorized`; nothing stored; `ABT-16b` — role with the
  wrong key refuses `owner_key_mismatch`; the out-of-scope audience
  publish is refused, never silently narrowed.
- **Owner:** future registry suite

### DT-17 — Break-glass abuse

- **Test IDs:** `ABT-17a`
- **Fixtures:** the enumerated break-glass operation set from the E24
  admin contract against a seeded fixture state.
- **Pass criteria:** every reachable post-state only narrows delivery;
  no operation mutates stored channel bytes or the `current` pointer, or
  serves a sha the signed channel does not name; each action emits its
  audit event.
- **Owner:** future registry suite

### DT-18 — CRL outage exploitation

- **Test IDs:** `ABT-18a`
- **Fixtures:** E18 `scenario_crl_outage` machinery: declared CRL made
  unreadable while a revoked sha is replayed; recovery rebuild from the
  store metadata history.
- **Pass criteria:** the replay refuses `-32017` fail-closed during the
  outage; after the documented rebuild, the good bundle verifies AND the
  revoked sha still refuses (both directions asserted, drill-style).
- **Owner:** client suite

### DT-19 — Last-good poisoning

- **Test IDs:** `ABT-19a`, `ABT-19b`
- **Fixtures:** E20 library populated via `AcceptanceContext`; tampered
  active pointer copy; a rollback target revoked after first activation.
- **Pass criteria:** `ABT-19a` — gateway startup re-verification refuses
  `-32015` on the tampered pointer copy; tampered content never governs;
  `ABT-19b` — `rollback` onto the since-revoked entry refuses `-32017`
  and does not complete.
- **Owner:** client suite

### DT-20 — Retention-expiry denial

- **Test IDs:** `ABT-20a`, `ABT-20b`
- **Fixtures:** fixture retention evaluator over (history-referenced,
  pin-referenced, unreferenced + grace elapsed) shas; a populated local
  library with the carrier unreachable.
- **Pass criteria:** `ABT-20a` — referenced shas remain downloadable;
  the unreferenced sha refuses `retention_expired`; revoked bundles are
  retained-not-served; `ABT-20b` — the E18-style rollback recovery
  completes entirely from local library state with no carrier.
- **Owner:** future registry suite (`ABT-20a`); end-to-end (E21-style)
  (`ABT-20b`)

### DT-21 — Support-bundle leak

- **Test IDs:** `ABT-21a`
- **Fixtures:** fixture state planted with distinctive markers (profile
  rule strings, fake tokens, fake key material, local paths); the
  `mcp_profiles` support block renderer.
- **Pass criteria:** leak-grep over the rendered block finds no planted
  marker; all redaction flags present; counts/pointers/last denial
  reason codes still answer the support question.
- **Owner:** future registry suite

### DT-22 — Schema-evolution downgrade

- **Test IDs:** `ABT-22a`, `ABT-22b`
- **Fixtures:** valid E23 example documents mutated to `*_version: 2`
  and to a missing version member; a registry envelope with an
  unexpected `schema_version`.
- **Pass criteria:** `ABT-22a` — the client refuses both mutations as
  load errors (no field honored); a malformed bundle artifact stays
  `-32014` (`profile_invalid`); `ABT-22b` — the envelope refuses
  `schema_invalid` at the boundary.
- **Owner:** client suite (`ABT-22a`); future registry suite
  (`ABT-22b`)

### DT-23 — Monotonicity bypass

- **Test IDs:** `ABT-23a`, `ABT-23b`
- **Fixtures:** registry fixture store at (identity, revision 5) with
  uploads at revisions 5 and 4; client watermark state for (`stable`,
  key A) at revision 5 plus a (`stable`, key B) channel at revision 1.
- **Pass criteria:** `ABT-23a` — equal and lower revisions both refuse
  `revision_regression`; stored bytes unchanged; `ABT-23b` — the client
  refuses the same-identity regression while evaluating the
  other-owner channel as a distinct identity (independent watermarks);
  a wiped-watermark fresh state is still bounded by assignment and
  bundle expiry (`-32016` under an injected clock).
- **Owner:** future registry suite (`ABT-23a`); client suite
  (`ABT-23b`)

## Traceability table

One row per threat class; the consistency test asserts this table names
every threat exactly once, that its test ids equal the section's ids,
and that every owner is one of the three layers.

| Threat | Primary mitigation (anchor) | Test IDs | Owner |
| --- | --- | --- | --- |
| DT-01 | E13 decisions 6/8 (`-32015`, `-32019`); E23 decision 1 signed-distribution policy | `ABT-01a`, `ABT-01b` | client suite |
| DT-02 | E24 decision 18 (`unsigned_artifact_rejected`; inner signature required in wrap schemas) | `ABT-02a`, `ABT-02b` | future registry suite; client suite |
| DT-03 | E13 never-widens invariant; namespace ceiling (`-32018`); E16 rollout-plan; E15 CRL (`-32017`) | `ABT-03a`, `ABT-03b` | client suite; end-to-end (E21-style) |
| DT-04 | Monotonic `revision` (E23 threat 20); `revision_regression` (E24 decision 18); expiry bounds (`-32016`) | `ABT-04a`, `ABT-04b` | client suite; future registry suite |
| DT-05 | E15 CRL authoritative (`-32017`); E23 decision 4 (statuses are hints); registry `bundle_revoked` | `ABT-05a`, `ABT-05b` | client suite; future registry suite |
| DT-06 | E24 decision 12 (no kill switch; `assignment_revoked` at contact); expiry bound (`-32016`); CRL (`-32017`) | `ABT-06a`, `ABT-06b` | end-to-end (E21-style); client suite |
| DT-07 | E13 rotation overlap + `not_after`; CRL `revoked_key_ids` (`-32017`); `-32019`; E23 channel freeze | `ABT-07a` | client suite |
| DT-08 | Channel identity pair (name, owner key); assignment `owner_key_id`; E24 decision 7 namespace binding (`owner_key_mismatch`) | `ABT-08a`, `ABT-08b` | client suite; future registry suite |
| DT-09 | Bundle audience check (`-32018`); E24 decision 2 scoped discovery (`audience_mismatch`, `unauthorized_install`) | `ABT-09a`, `ABT-09b` | client suite; future registry suite |
| DT-10 | E23 decision 6 deterministic order + loud tie refusal; signed assignments (E23 decision 1) | `ABT-10a`, `ABT-10b` | client suite |
| DT-11 | E24 decisions 1/2/14/15/16/20 (body/metadata split; closed schemas) | `ABT-11a`, `ABT-11b` | future registry suite |
| DT-12 | E24 decisions 19/20 (`schema_invalid`, `forbidden_field_rejected`); strict client loaders | `ABT-12a`, `ABT-12b` | future registry suite; client suite |
| DT-13 | Anti-oracle `unknown_or_unauthorized`; E24 decision 2 scoped listing | `ABT-13a` | future registry suite |
| DT-14 | E24 decisions 5/11 per-request entitlement (`no_profile_sync_entitlement`); decision 6 carrier-only gate | `ABT-14a`, `ABT-14b` | future registry suite; client suite |
| DT-15 | E24 decision 11 device proof + nonce cache (`device_proof_invalid`, `not_registered`) | `ABT-15a` | future registry suite |
| DT-16 | E24 decision 7 dual gate (`publisher_not_authorized`, `owner_key_mismatch`, `unsigned_artifact_rejected`) | `ABT-16a`, `ABT-16b` | future registry suite |
| DT-17 | E24 decision 17 narrow-never-steer asymmetry; no registry key material; audited break-glass | `ABT-17a` | future registry suite |
| DT-18 | Fail-closed unreadable CRL (`-32017`, E13 threat 18); E18 drill recovery | `ABT-18a` | client suite |
| DT-19 | E20 re-verification at startup/activate/rollback (`-32015`, `-32017`); content-addressed immutable store | `ABT-19a`, `ABT-19b` | client suite |
| DT-20 | E24 decision 13 retention guarantee (`retention_expired`); local last-good (E20/E23 offline-first) | `ABT-20a`, `ABT-20b` | future registry suite; end-to-end (E21-style) |
| DT-21 | E24 decision 16 redacted support block + decision 20 denylist | `ABT-21a` | future registry suite |
| DT-22 | Const-pinned versions (`-32014`, `schema_invalid`); E24 pre-v0.6 evolution policy | `ABT-22a`, `ABT-22b` | client suite; future registry suite |
| DT-23 | Server-side strict monotonicity (`revision_regression`); per-identity client watermarks; expiry bounds (`-32016`) | `ABT-23a`, `ABT-23b` | future registry suite; client suite |

## Refusal-code coverage

Every refusal/reason code cited anywhere in the threat model or this
plan, with its family. The consistency test asserts: every numeric code
is inside the implemented/reserved client family (`-32001`…`-32019`),
every name below is a known client code name or a known E24 registry
reason code, and no code cited in either document is missing from this
table.

| Code | Family | Cited by |
| --- | --- | --- |
| `-32014` (`profile_invalid`) | client (E09/E13) | DT-22 |
| `-32015` (`bundle_signature_invalid`) | client (E13/E14) | DT-01, DT-02 (context), DT-17, DT-18, DT-19 |
| `-32016` (`bundle_expired`) | client (E13/E14) | DT-04, DT-06, DT-23 |
| `-32017` (`bundle_revoked`) | client (E13/E14) | DT-03, DT-05, DT-06, DT-07, DT-18, DT-19 |
| `-32018` (`bundle_audience_mismatch`) | client (E13/E14) | DT-03, DT-09 |
| `-32019` (`bundle_key_missing`) | client (E13/E14) | DT-01, DT-07 |
| `ok` | registry (E24) | DT-13 |
| `not_registered` | registry (E24) | DT-15 |
| `device_proof_invalid` | registry (E24) | DT-15 |
| `no_profile_sync_entitlement` | registry (E24) | DT-14 |
| `unauthorized_install` | registry (E24) | DT-09 |
| `audience_mismatch` | registry (E24) | DT-09 |
| `assignment_expired` | registry (E24) | DT-04 |
| `assignment_revoked` | registry (E24) | DT-06 |
| `bundle_revoked` | registry (E24) | DT-05 |
| `retention_expired` | registry (E24) | DT-20 |
| `unknown_or_unauthorized` | registry (E24) | DT-09, DT-13 |
| `publisher_not_authorized` | registry (E24) | DT-16 |
| `unsigned_artifact_rejected` | registry (E24) | DT-02, DT-16 |
| `owner_key_mismatch` | registry (E24) | DT-08, DT-16 |
| `schema_invalid` | registry (E24) | DT-12, DT-22 |
| `forbidden_field_rejected` | registry (E24) | DT-12 |
| `revision_regression` | registry (E24) | DT-04, DT-23 |

Client refusal codes are minted only by the member's local E14
verification; registry reason codes answer only "will the carrier serve
you" — the two families never proxy each other (E24 contract), and no
new code is reserved by E25.

## Non-goals

- No test implementation in this change beyond
  `tests/test_mcp_distribution_threat_docs.py` (the docs-consistency
  gate). The `ABT-*` tests land WITH the future implementation, each in
  its owning layer.
- No hosted calls, no network, no production keys in any `ABT-*` test —
  the execution rules above are part of each test's pass criteria.
- No new refusal codes, schemas, or formats.

## See also

- [mcp-distribution-threat-model.md](mcp-distribution-threat-model.md)
  — the threat catalogue these tests trace to.
- [mcp-incident-runbook.md](mcp-incident-runbook.md) — the E18 drill
  whose fixture machinery and inject→assert→recover style every client
  abuse test reuses.
- [mcp-operator-acceptance.md](mcp-operator-acceptance.md) — the
  E21-style end-to-end harness the `end-to-end` owner extends.
