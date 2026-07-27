# FCP-007: Claude Code Enterprise Fleet Adapter

Status: implemented for a three-instance real-topology pilot. Production
rollout evidence is still required before any Business or Enterprise-ready
claim.

## Supported boundary

This adapter manages one registered Claude Code `agent_instance` per isolated
managed root. It supports:

- signed Fleet Wire desired state;
- signed private-pack manifest verification and release-bound download;
- immutable side-by-side revisions;
- activation and higher-epoch rollback;
- drift detection and repair;
- runtime attestation from a real Claude Code `SessionStart`;
- receipt spooling and upload through the Fleet agent client.

It does not manage Codex, OpenClaw, Hermes, or another vendor runtime. It does
not provide remote shell, arbitrary commands, package execution, automatic
rollback, percentage rollout, selectors, or scheduler behavior.

## Runtime proof

Each agent has a separate:

```text
<managed-root>/
  managed-root.json
  releases/
  state/
  runtime/
    .claude/
      settings.json
      skills/
  runtime-history/
  control/
```

`runtime/.claude` is the exact `CLAUDE_CONFIG_DIR` for that Claude process.
The adapter provisions a `SessionStart` hook inside the same configuration
directory. The hook must observe `startup` or `resume`, the exact managed
configuration directory, the exact installation-bound root, current
activation marker, and current skills tree before a runtime attestation is
accepted.

An ordinary Claude session, a different profile, a different managed root, a
missing hook, a changed activation, or a drifted skills tree cannot create a
verified runtime receipt.

## Local commands

Prepare and run one control-loop iteration:

```powershell
unlimited-skills fleet run-once `
  --managed-root <agent-root> `
  --public-keys <fleet-public-keys.json> `
  --organization-id <server-org-id> `
  --auto-activate `
  --json
```

Launch the corresponding real Claude Code runtime:

```powershell
unlimited-skills fleet claude-launch `
  --managed-root <agent-root> `
  -- `
  <claude-arguments>
```

The launcher resolves a real Claude executable and starts it without a shell.
It sets only the exact managed `CLAUDE_CONFIG_DIR` and managed-root binding.
`--dry-run --json` provisions and validates the profile without starting
Claude.

The control loop requires an existing Unlimited Skills registration,
Enterprise fleet entitlement, an organization binding, and explicitly
provisioned active Ed25519 Fleet desired-state public keys. There is no TOFU.

## Pack security

Private packs are downloaded only after existing registration,
authentication, and entitlement checks. The request binds the exact
`pack_id`, deterministic `release_id`, and expected archive SHA-256 to the
currently authorized manifest.

Archives are bounded by compressed size, expanded size, and member count.
Extraction rejects absolute paths, traversal, backslashes, case collisions,
duplicate paths, Windows reserved names, trailing spaces or dots, control
characters, symlinks, special files, and payloads without a valid skills
root.

Installed payloads remain immutable. Activation copies a verified payload
into the adapter-owned Claude skills root. Rollback reuses the immutable older
revision but issues a new activation marker, nonce, runtime generation, and
receipt chain.

## Privacy

Adapter evidence excludes:

- registry tokens and device private keys;
- raw Claude session IDs;
- prompts and task text;
- transcript and working-directory paths;
- environment values;
- private skill bodies.

Only a hash of the Claude session ID, bounded process identifiers, pack and
release identities, activation binding, tree and inventory digests, adapter
version, and server timestamps are retained.

## Required real-topology proof

The pilot is accepted only after all of the following are captured from three
real Claude Code instances spanning local and `clawd02`:

1. independent registered identities, managed roots, and runtime generations;
2. signed pack A verified on 3/3;
3. signed pack B observed at exactly 1 verified, 1 activation pending, and
   1 offline or retryable;
4. recovery to B at 3/3;
5. independent drift on one instance and receipt-backed recovery;
6. rollback to A as a new higher-epoch rollout, first 0/3 and then 3/3 with
   three fresh runtime attestations;
7. matching HTML, JSON, projection, ledger, snapshot, and rebuild truth;
8. trusted-admin-transport smoke with no credential or proof exposure.

Until that evidence exists, the only accurate status is:
`FCP-007 implementation complete; real-topology pilot pending`.
