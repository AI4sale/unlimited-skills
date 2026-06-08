# Team Skill Sync

Status: Team Free client workflow implemented for registered installations. Encrypted private team publishing remains roadmap.

Team Skill Sync keeps approved registered team instances aligned with hosted team collection assignments.

The local MIT core remains unchanged. Without registration, every instance keeps using local skills as-is. With registration, a team can attach instances to a shared team identity and synchronize catalog collections through the official registry.

## Implemented Client Commands

```bash
unlimited-skills team create --name "My Team"
unlimited-skills team join <join-code> --display-name "Hermes laptop"
unlimited-skills team status --json
unlimited-skills team members
unlimited-skills team pending
unlimited-skills team approve <install-id>
unlimited-skills team reject <install-id> --reason "not recognized"
unlimited-skills team revoke <install-id> --reason "old machine" --yes
unlimited-skills team mode manual
unlimited-skills team mode auto --duration 24h
unlimited-skills team collections
unlimited-skills team sync --dry-run
unlimited-skills team sync --yes
unlimited-skills team leave --yes
```

## Rules

1. The first registered instance that runs `team create` becomes the team master.
2. `team create` returns a join code.
3. Other registered instances run `team join <join-code>`.
4. A join code alone does not grant sync access.
5. Default team mode is manual.
6. Pending instances require `team approve <install-id>` from a master/admin.
7. Approved instances can run `team sync`.
8. Team Free auto approval is capped at 24 hours.
9. Team Free supports up to 10 approved instances when enforced server-side.

## Privacy

Team sync sends install id, team id, client version, agent surfaces when supplied, collection versions/source labels, and sync status. It must not upload local skill bodies, prompts, source code, full local paths, repository paths, customer names, environment variables, tokens, secrets, or device private keys.

## Audit

The client writes local redacted audit events to:

```text
~/.unlimited-skills/.learning/team-events.jsonl
```

Events include create, join request, approve, reject, revoke, mode change, dry-run sync, applied sync, leave, and errors. Audit events must not contain hosted tokens, auth headers, device private keys, or sensitive download URLs.

## Roadmap

Encrypted private team-pack publishing, private registries, Enterprise Skill Lock, SSO, signed policy enforcement, on-prem/VPC options, and enterprise key management are planned paid/business features. They are not implemented by the public Team Free client.
