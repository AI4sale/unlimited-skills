# Local Skill Hub Security

Local Skill Hub is designed as a local-first service. The default bind address is `127.0.0.1`.

LAN mode must be explicit:

```bash
unlimited-skills hub serve --host 0.0.0.0 --port 8766
```

LAN mode requires client tokens. For network exposure, use a reverse proxy with TLS and normal access logging controls.

## Safety Rules

- The hub does not execute skills or scripts.
- The hub must not store secrets in logs.
- Tokens and device proof material must be redacted in status output, errors, and audit logs.
- Registration tokens and device private keys are local private state under `~/.unlimited-skills/registration.json`.
- Local search queries are not forwarded to the hosted service by default.
- Hub logs and learning data should stay under `~/.unlimited-skills/.learning/` or `~/.unlimited-skills/hub/`.

## Hosted Collection Sync

When the hub syncs hosted collections, archive extraction must be path-safe and SHA256-verified before installation. Cryptographic signature verification is planned and must not be claimed as implemented until the client enforces it.

Skill archives must not contain secrets, private customer context, private repository paths, or blocked assets. Tool/platform skills require local capability checks before use.
