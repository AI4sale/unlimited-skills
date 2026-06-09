# Local Skill Hub Plan Heartbeat

Registered Local Skill Hub instances can refresh plan and entitlement metadata from the hosted registry without sending local task content.

## Commands

```bash
unlimited-skills hub license status
unlimited-skills hub license refresh
unlimited-skills hub heartbeat --dry-run
unlimited-skills hub heartbeat --json
```

`hub heartbeat --dry-run` prints the exact request payload and does not contact the hosted service. Heartbeat and license refresh require registration. MIT local core commands such as `list`, `search`, `view`, `reindex`, `vector-reindex`, `serve`, and `self-update` remain unregistered local commands.

## Privacy Contract

Heartbeat payloads include only:

- `install_id`;
- `hub_id`;
- Unlimited Skills client name and version;
- current plan label;
- active client count and count bucket;
- active client limit;
- cached allowlist presence and SHA256;
- `allowlist_only` distribution mode;
- feature flags;
- coarse OS bucket;
- status summary buckets.

Heartbeat payloads must not include:

- search queries or prompts;
- skill bodies, skill names, or skill lists;
- full local paths or repository paths;
- customer names or project names;
- environment variable values;
- raw tokens, license tokens, secrets, or private keys.

Hosted query forwarding remains disabled by default.

## Endpoint Contract

The public client uses fake services in tests. Production service behavior should match this contract:

```http
POST /v1/hub/heartbeat
POST /v1/hub/entitlements
```

The request schema is `schemas/hub-heartbeat-request.schema.json`. The response schema is `schemas/hub-heartbeat-response.schema.json`.

## Entitlement Effects

Plan refresh can update cached Local Skill Hub feature flags:

- `local_skill_hub`;
- `max_hub_clients`;
- `hub_distribution_mode`;
- `signed_manifests_required`;
- `team_sync_enabled`.

The default community limit remains 100 active hub clients unless a refreshed entitlement says otherwise.

## Offline Grace

Successful refresh stores `offline_grace_until` in the local hub entitlement cache. Existing hub operation can continue while grace is active. When grace expires, status reports `offline_grace_status=expired`; operators should refresh registration before relying on hosted entitlements.

## Downgrades

Downgrades do not delete clients or skills. If the refreshed `max_hub_clients` is lower than the current active client count, existing clients remain in the local client cache, but new clients are rejected until active usage falls below the refreshed limit or the plan is refreshed again.

## Security Notes

- Heartbeat and entitlement refresh require registration.
- Tests must use fake services or localhost only.
- Production hosted calls must not happen in tests.
- Raw tokens and private keys must not be printed or cached in heartbeat artifacts.
- Full catalog distribution remains disabled; hub distribution stays allowlist-only.
