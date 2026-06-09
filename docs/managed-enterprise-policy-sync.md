# Managed Enterprise Skill Lock Sync

Status: v0.3.0-alpha development.

Managed policy sync lets a registered Unlimited Skills instance fetch a signed Enterprise Skill Lock assignment from the configured registry:

```bash
unlimited-skills policy sync --dry-run
unlimited-skills policy sync
unlimited-skills policy managed-status
```

The local MIT core remains usable without registration. Managed sync is only for registered Enterprise or team-controlled policy delivery.

## Safety Boundary

`policy sync` is not a remote shell for `policy remove --yes`.

When the registry returns `action=remove`, the client removes the local policy only when the installed policy is owned by managed sync:

- `managed-policy-state.json` has `managed: true`;
- the managed state has `installed_by: managed-sync`;
- the managed state's `policy_id` matches the installed policy;
- the managed state's `policy_sha256` matches the installed policy summary.

If any check fails, the client refuses removal and leaves the local policy installed. The result includes:

```json
{
  "remove_allowed": false,
  "removal_refused": true,
  "refusal_reason": "installed_policy_not_managed",
  "message": "Registry requested managed policy removal, but the installed policy is not managed by registry sync."
}
```

Non-dry-run refusals write a redacted audit event:

```json
{
  "event_type": "managed_policy_remove_refused",
  "reason": "installed_policy_not_managed",
  "redacted": true
}
```

Dry-run performs the same verification and writes nothing.

## State

Managed sync state is stored under:

```text
~/.unlimited-skills/policy/managed-policy-state.json
```

For installed managed policies, state records:

- `managed`;
- `policy_id`;
- `policy_sha256`;
- `assignment_id`;
- `installed_by`;
- `last_sync_at`.

The state must not contain hosted tokens, device private keys, prompts, skill bodies, or source code.

## Request Privacy

The client sends only registration metadata and the current policy summary to `/v1/policy/sync`.

The request must not include skill bodies, prompts, source code, local paths, repository paths, search queries, environment variable values, hosted tokens, secrets, or device private keys.

## Non-Goals

- No hosted billing or dashboard behavior.
- No Enterprise Skill Lock requirement for Community users.
- No full catalog distribution.
- No weakening of signed assignment or policy payload verification.
