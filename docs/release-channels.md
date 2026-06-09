# Release Channels and Update Rollback

Registered clients can pin hosted registry updates to a signed release channel.

Supported channels:

- `stable`
- `beta`
- `canary`

The default is `stable`.

## Inspect Channels

```bash
unlimited-skills release status
unlimited-skills release status --json
```

The command fetches `POST /v1/channels/status` and verifies the signed `release-channels` manifest before printing channel metadata.

## Pin A Channel

```bash
unlimited-skills release pin beta
```

The pin is stored in local Unlimited Skills state. Future hosted catalog and update checks include that channel:

```bash
unlimited-skills catalog list
unlimited-skills updates check
unlimited-skills updates apply --skip-reindex
```

Use a one-off override without changing the pin:

```bash
unlimited-skills updates check --channel canary
unlimited-skills catalog list --channel stable
```

## Rollback A Collection

`updates apply` saves the replaced collection under `registry/.rollbacks/<collection>/` before installing the new one.

Rollback restores the latest saved snapshot:

```bash
unlimited-skills updates rollback ecc --yes
```

Rollback changes local files only. It does not contact the hosted registry and does not delete the rolled-forward collection; that collection is moved into the same rollback area for auditability.

## Security Boundary

- Release channel status is signed and verified with scope `release-channels`.
- Channel-pinned catalog and update manifests are still signed and verified with scope `catalog-updates`.
- Archive downloads still require HTTPS or localhost, SHA256 verification, and safe zip extraction.
- Offline cache can be used only after a signed response was previously accepted.
