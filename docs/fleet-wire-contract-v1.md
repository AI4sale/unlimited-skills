# Fleet Wire Contract v1

Status: FCP-002 frozen contract plus the FCP-003 public registered-agent
client. This document does not claim that Business fleet delivery, the
Enterprise control plane, the dashboard, receipt ingestion, or a production
SLA is complete.

## Authority

The public `unlimited-skills` repository is the sole authority for the
versioned Fleet Wire Contract and golden interoperability fixtures.

The private registry remains the authority for tenant data, rollout policy,
signing operations, persistence, projections, audit and administration.
Private database rows are not wire messages.

The contract bundle is under:

```text
contracts/fleet/v1/
```

It contains:

- agent registration request and response schemas;
- heartbeat request and response schemas;
- the signed desired-state schema;
- receipt event, batch and response schemas;
- lifecycle states and authority assignments;
- allowlisted reason codes;
- signing and versioning rules;
- positive and negative golden fixtures;
- `contract-manifest.json`, which pins every JSON schema and fixture by SHA-256.

## Identity boundary

An installation is the authenticated reconciler/device identity.

An agent instance is a server-issued identity bound to an installation and
tenant. The registration request carries a local instance identifier and
self-reported capabilities. It cannot set:

- `agent_id`;
- operator labels;
- role;
- environment.

Those fields are server/operator managed and must not be used from
self-reported client metadata for authorization.

## Signing boundary

Desired state uses Ed25519 with the dedicated role:

```text
fleet-desired-state-signing
```

This role is separate from:

```text
pack-release-signing
```

The signature covers the UTF-8 canonical JSON representation of the complete
desired-state object except `desired_state_signature`. Floats are forbidden.
Keys are sorted and JSON is emitted without insignificant whitespace.

The `desired_state_digest` covers the desired-state object excluding both
`desired_state_digest` and `desired_state_signature`. This provides a stable
chain through `previous_digest` without a self-referential hash.

The known-answer public key, expected digest and signed fixture are recorded in
`signing-contract.json`.

## Delivery truth

Client-reportable progress is:

```text
DESIRED_SEEN
MANIFEST_VERIFIED
ARTIFACT_VERIFIED
INSTALL_COMMITTED
ACTIVATION_PENDING
RUNTIME_ATTESTED
```

`ARTIFACT_DOWNLOADED` is informational.

Each signed desired-state item includes the server-issued `attempt_id` that
must appear unchanged in every receipt for that item. Clients never invent or
substitute delivery-attempt identity.

Only the server may create:

```text
TARGETED
VERIFIED_ACTIVE
```

A client receipt with either server-authority state is invalid. Runtime
attestation is evidence for the server. It is not itself `VERIFIED_ACTIVE`.

## Rollback

Rollback is a new signed desired state and rollout:

- the control epoch must be higher;
- the desired item points to an older valid revision;
- the new document is signed normally;
- the old desired-state document is never replayed;
- lower epochs fail closed.

## Compatibility

Within v1, a producer may add an optional field with no new required semantic.
An older consumer may ignore unknown optional diagnostics.

The following require v2:

- removing a required field;
- changing an existing field's meaning;
- changing canonical signed bytes;
- changing state transitions;
- changing `verified_active` authority or meaning;
- changing `control_epoch` or rollback semantics.

Unknown actions and unknown required semantics fail closed.

## Local reconciler

`unlimited_skills.fleet.FleetReconciler`:

- verifies the desired-state signature and expiry;
- enforces monotonic control epochs;
- invokes a finite vendor adapter interface;
- creates allowlisted milestone receipts;
- writes receipts to an atomic offline spool;
- never emits `VERIFIED_ACTIVE`.

Automatic activation defaults off. Operators opt in explicitly:

```text
UNLIMITED_SKILLS_FLEET_AUTO_ACTIVATE=1
```

The global client kill switch is:

```text
UNLIMITED_SKILLS_FLEET_DISABLE=1
```

The kill switch blocks new reconciliation. It does not erase the local receipt
spool.

## Registered agent client

`unlimited_skills.fleet.FleetAgentClient` is the public FCP-003 client library.
It composes the registered installation identity, a vendor adapter, a
persisted agent identity, the signed desired-state trust set, the reconciler
state and the receipt spool.

The client:

- creates a random canonical UUIDv4 before its first network registration;
- persists that UUID atomically and reuses it for the life of the local agent
  instance;
- binds the server-issued `agent_id` to that UUID and installation;
- repeats registration idempotently on each control-loop start so runtime and
  adapter metadata can be refreshed;
- signs every registration and heartbeat HTTP request with the existing
  installation device key and an exact body hash;
- creates a fresh proof nonce for every network retry;
- sends only runtime generation and an inventory digest in heartbeat;
- validates registration and heartbeat responses against Fleet Wire Contract
  v1;
- verifies desired-state expiry, digest, key role and Ed25519 signature before
  handing the document to the reconciler;
- caps a fleet HTTP response at the contract limit of 256 KiB;
- never trusts an agent identity supplied only by a caller. Heartbeat must use
  the identity currently persisted by the configured identity store.

Example composition:

```python
from pathlib import Path

from unlimited_skills import __version__
from unlimited_skills.fleet import (
    FleetAgentClient,
    FleetAgentIdentityStore,
    ReceiptSpool,
)
from unlimited_skills.registration import load_registration

agent_root = Path.home() / ".unlimited-skills" / "fleet" / "codex-primary"
client = FleetAgentClient(
    registration=load_registration(),
    runtime_vendor="codex",
    adapter=adapter,
    identity_store=FleetAgentIdentityStore(
        agent_root / "agent-identity.json"
    ),
    public_keys=provisioned_fleet_public_keys,
    reconcile_state_path=agent_root / "reconcile-state.json",
    spool=ReceiptSpool(agent_root / "receipts"),
    client_version=__version__,
    reported_capabilities=(
        "desired-state-v1",
        "receipt-spool-v1",
        "runtime-attestation",
    ),
    organization_id="org_server_assigned",
)
result = client.run_once()
```

`adapter` and `provisioned_fleet_public_keys` are explicit integration inputs.
The client does not implement trust-on-first-use. An HTTPS
`/v1/fleet/public-keys` response is discovery metadata, not by itself a trust
anchor. Business and Enterprise deployments must provision the dedicated
fleet desired-state public keys through an authenticated administrative
channel and rotate them under change control.

The client library does not schedule itself and does not upload receipt events
in FCP-003. Receipt upload and the server truth engine are FCP-004 scope.
Therefore a successful FCP-003 run may spool `RUNTIME_ATTESTED` locally while
the server correctly remains `TARGETED` with `verified_active=false`.

Registration and heartbeat do not contain skill bodies, prompts, local paths,
environment values, stdout, stderr, tracebacks, secrets, access tokens or
device private keys.

## Verification

Run:

```powershell
python scripts/generate-fleet-contract-fixtures.py
python scripts/generate-fleet-contract-manifest.py
python scripts/verify-fleet-wire-contract.py
python -m pytest tests/test_fleet_contract.py tests/test_fleet_reconciler.py tests/test_fleet_agent_client.py -q
```

The generators run in check mode by default. Use `--write` only when
intentionally updating the frozen bundle.
