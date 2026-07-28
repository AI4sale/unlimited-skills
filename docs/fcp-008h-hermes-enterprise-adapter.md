# FCP-008H: Hermes Enterprise Fleet Adapter

Status: public adapter and local contract tests implemented. Production
readiness still requires receipt-backed proof from the approved real fleet.

## Wire compatibility

Fleet Wire Contract v1 remains frozen. Its runtime vendor and adapter fields
are bounded identifiers rather than a closed enum, so adding `hermes` does not
change any schema, signing rule, state transition, or receipt authority.

The adapter reports:

- runtime vendor `hermes`;
- adapter ID `hermes`;
- adapter version `hermes-fleet/1.0.0`;
- capability `hermes-session-start-attestation-v1`.

## Ownership boundary

One `HermesFleetAdapter` binds one registered Fleet identity to one exact
Hermes home. It owns only:

```text
<fleet-managed-root>/
  managed-root.json
  releases/
  state/
  runtime-history/
  control/

<hermes-home>/
  plugins/
    unlimited-skills-fleet/
  skills/
    unlimited-skills-fleet-managed/
```

Personal skills elsewhere under `<hermes-home>/skills`, model credentials,
configuration, memory, sessions, channels, and tools remain unmanaged. The
adapter rejects a delivered skill name that collides with a personal skill.
It never replaces the complete Hermes skills directory.

## Runtime proof

Provision and explicitly enable the lifecycle plugin:

```bash
unlimited-skills fleet hermes-provision \
  --managed-root <fleet-root-for-hermes> \
  --hermes-home <hermes-home> \
  --json
```

Run one control-loop iteration:

```bash
unlimited-skills fleet run-once \
  --runtime-vendor hermes \
  --managed-root <fleet-root-for-hermes> \
  --hermes-home <hermes-home> \
  --public-keys <fleet-public-keys.json> \
  --organization-id <server-org-id> \
  --auto-activate \
  --json
```

Start the bound runtime:

```bash
unlimited-skills fleet hermes-launch \
  --managed-root <fleet-root-for-hermes> \
  --hermes-home <hermes-home> \
  -- \
  <hermes-arguments>
```

The plugin registers only `on_session_start`. It passes a bounded event name
and opaque session ID over stdin to the locally installed Unlimited Skills
client. No shell is used. The client validates the exact Hermes home, plugin
source hash, current activation marker, and current managed skills tree.
Evidence stores only a hash derived from the session ID, never the raw ID.

Installing files is not runtime proof. After activation, the correct state is
`ACTIVATION_PENDING` until a real Hermes session starts and a later
reconciliation uploads `RUNTIME_ATTESTED`.

## Security and privacy

The adapter and plugin do not read or upload:

- model or channel credentials;
- prompts, responses, tool arguments, transcripts, or memory;
- personal skill bodies;
- Hermes configuration or environment values;
- private team skill bodies.

The generated plugin command is fixed at provisioning time and bound by hash
in the managed-root marker. Server desired state cannot supply executable
commands. User plugin enablement remains explicit and auditable through
Hermes' own plugin control.

## Acceptance

FCP-008H is accepted only when the real Hermes instance:

1. registers a unique Fleet identity;
2. receives the approved multi-pack desired state;
3. remains pending before a runtime turn;
4. emits a real `on_session_start` observation;
5. reaches receipt-backed `VERIFIED_ACTIVE`;
6. participates in drift repair and higher-epoch rollback without receipt
   loss;
7. matches the dashboard, projection, ledger, and rebuild views.
