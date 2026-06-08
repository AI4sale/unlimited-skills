# Team Free

Status: registered client workflow implemented; limits are enforced by the hosted service.

Team Free is the small-team synchronization layer for approved registered instances. It is not enterprise governance and it does not implement private encrypted packs, SSO, on-prem registries, Enterprise Skill Lock, or signed policy enforcement.

## Boundary

- Local Community Core remains MIT and works without registration.
- Team Free requires registration because it uses hosted team sync.
- First registered instance that runs `team create` becomes the master/admin.
- A join code alone does not grant sync access.
- Manual approval is the default.
- Auto approval is capped at 24 hours for Team Free.
- Team Free supports up to 10 approved instances when enforced server-side.
- Team sync fetches hosted team collection manifests and archives.
- Team sync does not upload local skill bodies.

## Workflow

Create a team:

```bash
unlimited-skills team create --name "Acme Agents"
```

Join from another instance:

```bash
unlimited-skills team join <join-code> --display-name "Hermes laptop" --agent-surface hermes
```

Approve:

```bash
unlimited-skills team pending
unlimited-skills team approve <install-id>
```

Sync:

```bash
unlimited-skills team sync --dry-run
unlimited-skills team sync --yes
```

Switch approval mode:

```bash
unlimited-skills team mode manual
unlimited-skills team mode auto --duration 6h
```

Revoke an old instance:

```bash
unlimited-skills team revoke <install-id> --reason "old machine" --yes
```

## Commands

- `team status --json`: local status with redacted auth state.
- `team members`: approved members by default.
- `team members --all`: all statuses.
- `team pending`: pending join requests.
- `team approve <install-id>`: approve pending member.
- `team reject <install-id> --reason <reason>`: reject pending member.
- `team revoke <install-id> --reason <reason> --yes`: revoke hosted team access.
- `team collections`: team-assigned hosted collections.
- `team leave --yes`: leave the team without deleting local skills.

## Limits

Team Free limit errors are displayed with explicit local guidance:

- member limit: Team Free supports up to 10 approved instances.
- pending approval: ask a team admin to run `unlimited-skills team approve <install_id>`.
- auto approval over 24 hours: paid team/business feature.

The public client documents and handles these errors. The hosted backend enforces the actual limits.
