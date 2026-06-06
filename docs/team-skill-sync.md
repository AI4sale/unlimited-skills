# Team Skill Sync

Status: planned, not implemented yet.

Team Skill Sync is the planned team layer for synchronized private skill packs across many registered agent instances.

The local MIT core remains unchanged. Without registration, every instance keeps using local skills as-is. With team registration, a master instance can publish encrypted team skill packs, and child instances can receive the same signed update through the official registry.

## Use Case

A team may run:

- 1,000 OpenClaw instances;
- multiple Codex, Hermes, Claude Code, or OpenClaw workstations;
- many private `special-skills`;
- shared operational procedures that must stay synchronized.

Instead of manually copying skills to every machine, the team publishes one encrypted skill-pack update from a master instance. All registered child nodes receive the update, download the encrypted archive, decrypt it locally, and install it into their local library.

## Planned Flow

1. Team owner registers a team.
2. Team owner enrolls instances into that team.
3. A master instance prepares a team skill pack.
4. The client encrypts the archive locally.
5. The encrypted archive is uploaded to temporary registry storage.
6. The registry stores metadata, checksums, signatures, and the encrypted archive only.
7. Child instances poll or receive the new team pack version.
8. Child instances download the encrypted archive.
9. Child instances decrypt it locally with the team key stored on each team node.
10. Child instances verify checksum/signature and install the updated skill pack.

## Security Model

- Skill contents are encrypted before upload.
- The registry must not store the team decryption key.
- Team nodes store the decryption key locally.
- Registry storage is temporary for uploaded encrypted archives.
- Published packs are versioned and signed.
- Child nodes install only packs matching their team id, channel, signature, and checksum.
- Revoked instances stop receiving future team updates.

## Free Tier

The planned free team license includes up to 10 registered team instances.

Larger teams, private registries, longer archive retention, audit logs, SSO, and enterprise key management are planned paid/team features.

## Planned Commands

```bash
unlimited-skills team register
unlimited-skills team enroll
unlimited-skills team publish --collection special-skills
unlimited-skills team sync
unlimited-skills team status
```

The exact command names may change during implementation.
