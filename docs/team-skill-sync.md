# Team Skill Sync

Status: MVP client flow implemented for registered installations. Encrypted private team publishing remains roadmap.

Team Skill Sync is the registered team layer for keeping assigned skill collections synchronized across multiple agent instances.

The local MIT core remains unchanged. Without registration, every instance keeps using local skills as-is. With registration, a team can attach instances to a shared team identity and synchronize catalog collections through the official registry.

## Current MVP

Implemented client commands:

```bash
unlimited-skills team create "My Team"
unlimited-skills team join <join-code>
unlimited-skills team status
unlimited-skills team pending
unlimited-skills team approve <install-id>
unlimited-skills team mode manual
unlimited-skills team mode auto --hours 24
unlimited-skills team sync
```

Current behavior:

1. The first registered instance that runs `team create` becomes the team master.
2. `team create` returns a join code.
3. Other registered instances run `team join <join-code>`.
4. Default team mode is manual, so joined instances become pending.
5. The master instance runs `team pending` and `team approve <install-id>`.
6. Approved instances can run `team sync` to install team-assigned catalog updates.

## Approval Mode

Default mode is manual. A join code alone does not grant sync access.

The master can temporarily enable auto-approval:

```bash
unlimited-skills team mode auto --hours 24
```

Community plans are capped at 24 hours of auto-approval. Longer auto-approval windows require business or enterprise access. The master can return to manual mode:

```bash
unlimited-skills team mode manual
```

## Native Skill Sync

Native agent skill roots are mirrored into the local library before common commands run. This keeps newly installed Codex, Claude Code, Hermes, and OpenClaw skills searchable through Unlimited Skills:

```bash
unlimited-skills sync-native --agent hermes
unlimited-skills search "security review" --native-agent hermes
```

## Roadmap

The next team layer is encrypted private skill-pack publishing:

1. A master instance prepares a team skill pack.
2. The client encrypts the archive locally.
3. The encrypted archive is uploaded to temporary registry storage.
4. The registry stores metadata, checksums, signatures, and the encrypted archive only.
5. Child instances poll or receive the new team pack version.
6. Child instances download the encrypted archive.
7. Child instances decrypt it locally with the team key stored on each team node.
8. Child instances verify checksum/signature and install the updated skill pack.

## Security Model

- Skill contents are not uploaded by normal sync, catalog, update, or enhancement checks.
- Join requests are pending by default and require master approval.
- Auto-approval is temporary and capped at 24 hours on community plans.
- The registry must not store future private-pack decryption keys.
- Revoked instances must stop receiving future team updates.

## Free Tier

The planned free team license includes up to 10 registered team instances.

Larger teams, longer auto-approval windows, private registries, encrypted private-pack publishing, longer archive retention, audit logs, SSO, and enterprise key management are planned paid/team features.
