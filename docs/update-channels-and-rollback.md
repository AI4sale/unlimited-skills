# Update Channels And Rollback

Registered hosted collection updates remain explicit write operations under `unlimited-skills updates apply`. The catalog improvement commands added for skill recommendations are read-only advisory commands.

## Preview-Only Recommendation Commands

```bash
unlimited-skills catalog update-recommendations
unlimited-skills catalog update-recommendations --json
unlimited-skills catalog update-preview community:browser-qa-pack:0.1.0
```

These commands require registration, verify signed hosted metadata, and show recommended action, channel, version, issue counts, severity summary, fix status, compatibility notes, and stale installed-version status.

They do not:

- download archives;
- install or update skills;
- remove skills;
- rewrite skill bodies;
- change release-channel pins;
- rebuild indexes;
- perform rollback.

## Apply And Rollback Remain Separate

Use `unlimited-skills updates check` to inspect hosted collection updates and `unlimited-skills updates apply --yes` only when the user explicitly wants a write operation. Use `unlimited-skills updates rollback <collection> --yes` only for the existing rollback flow.

Catalog recommendations may suggest `update`, `remove`, `pin`, `review`, or `none`, but they are never an implicit approval to mutate local files.
