# Enterprise Skill Lock

Status: MVP alpha.

Enterprise Skill Lock is a local policy layer for governed Unlimited Skills installations. It does not turn Community Core into a paid feature. When no policy is installed, local MIT behavior is unchanged.

When a policy is installed, the client can audit or enforce controls for approved registries, release channels, signing keys, local roots, community flows, Local Skill Hub allowlists, and remote fallback behavior.

## Commands

```bash
unlimited-skills policy status
unlimited-skills policy verify enterprise-policy.json
unlimited-skills policy install enterprise-policy.json
unlimited-skills policy sync --dry-run
unlimited-skills policy sync
unlimited-skills policy managed-status
unlimited-skills policy explain
unlimited-skills policy remove --yes
```

Policies must be signed or hash-pinned. The MVP accepts either a valid `manifest_signature` / `signature_envelope` verified by local trust configuration, or a `policy_sha256` that matches the canonical policy payload excluding signature/hash fields.

Managed policy sync is registration-gated. `policy sync` posts local registration metadata and the current policy summary to `/v1/policy/sync`, verifies the signed `enterprise-policy` assignment manifest, verifies the policy payload itself, and only then installs or updates the local policy. `action=remove` is guarded: the client removes only a policy that was previously installed by managed sync and whose `policy_id` plus `policy_sha256` still match local managed state. If a registry asks to remove an unmanaged local policy, the client refuses removal, leaves the policy installed, and writes a redacted audit event. `policy sync --dry-run` performs the same verification without writing local policy state. `policy managed-status` reads only local sync state and does not contact the hosted registry. See [Managed Enterprise Skill Lock Sync](managed-enterprise-policy-sync.md).

## Modes

- `audit`: warn by writing a redacted policy refusal event, then allow the action.
- `enforce`: write the redacted refusal event and reject the action.

Example refusal in enforce mode:

```text
This instance is managed by Enterprise Skill Lock.
Action blocked: community install.
Reason: community installs are denied by policy.
Remediation: Ask your corporate Unlimited Skills administrator to publish the skill through an approved registry.
```

## Policy Shape

See [schemas/enterprise-skill-lock-policy.schema.json](../schemas/enterprise-skill-lock-policy.schema.json) and [examples/policy/enterprise-skill-lock-policy.example.json](../examples/policy/enterprise-skill-lock-policy.example.json).

```json
{
  "schema_version": 1,
  "policy_id": "policy_example",
  "mode": "audit|enforce",
  "allowed_registries": ["https://registry.example.com"],
  "allowed_release_channels": ["stable"],
  "required_manifest_signatures": true,
  "allowed_key_ids": ["ai4sale-registry-prod-2026-01"],
  "allowed_local_roots": [],
  "community": {
    "install_allowed": false,
    "submit_allowed": false
  },
  "hub": {
    "remote_required": true,
    "local_fallback_allowed": false,
    "unsigned_local_allowlist_allowed": false
  },
  "audit": {
    "log_refusals": true
  },
  "policy_sha256": "<canonical hash or use manifest_signature>"
}
```

## Enforcement Points

MVP enforcement covers:

- `service configure` and hosted registry requests;
- registration, catalog, updates, community, team, hub sync, and release-channel clients through the shared hosted request path;
- signed manifest verification for unknown key IDs and disallowed scopes;
- release channel pinning and registered update channel selection;
- explicit local Hub allowlists when unsigned local allowlists are denied;
- remote hub local fallback when remote hub is required;
- community install and submit;
- local search/list/view/reindex roots when `allowed_local_roots` is configured.

## Audit Logs

Policy refusals are written to:

```text
~/.unlimited-skills/policy/refusals.jsonl
```

Managed sync state is written to:

```text
~/.unlimited-skills/policy/managed-policy-state.json
```

Audit events are redacted. They must not include hosted tokens, auth headers, device private keys, prompts, or skill bodies.

Managed sync removal refusals are written as `managed_policy_remove_refused` events when the installed policy is not owned by registry sync. These events intentionally omit hosted tokens, private keys, and local filesystem paths.

## Why This Exists

Skills change agent behavior. For a business, uncontrolled skill delivery is a governance and supply-chain risk.

Enterprise Skill Lock is intended to help with:

- controlled rollouts;
- approved skill sources;
- auditability;
- separation between community, team, and enterprise skills;
- preventing accidental or malicious skill injection;
- enforcing business policy across many agent instances.

## Planned Policy Controls

- allowed registries;
- allowed pack signatures;
- required update channels;
- denied community submissions;
- denied local ad hoc installs;
- approved local library roots;
- admin override flow.

## Limitations

- This is local client enforcement, not a hosted enterprise dashboard.
- SSO, SCIM, billing, and organization management are not implemented here.
- A local policy cannot prevent a user with filesystem access from editing source code. Enterprise deployments should pair policy with managed installation, OS controls, and private registry governance.
- Full catalog distribution remains disabled for the alpha registered stack.
