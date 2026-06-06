# Privacy and Telemetry

Unlimited Skills is local-first.

By default, skills, prompts, source code, local file paths, repository names, customer names, tokens, and secrets stay on the user's machine.

## What the hosted update client may send

When a registered installation checks the hosted catalog, hosted adapted collection updates, or local enhancement script metadata, the client sends only a minimal request:

- local install id;
- public device key and key thumbprint;
- client name and version;
- collection version metadata;
- collection source label;
- skill count bucket.

The update client does not send:

- `SKILL.md` contents;
- prompts or conversation history;
- source code;
- skill names;
- full local paths;
- repository paths;
- customer names;
- filenames from private projects;
- environment variables;
- device private keys;
- tokens or secrets.

The local enhancement script is downloaded from the registry, but it runs on the user's machine. Skill contents are not uploaded for enhancement.

Community publishing is different: when a user submits or pushes a skill to the hosted `community-skills` catalog, the selected skill or pack is intentionally uploaded for review/publication. The client must show that explicit upload action separately from telemetry, search, update checks, or local enhancement.

## Telemetry

Telemetry is off by default.

Check status:

```bash
unlimited-skills telemetry status
```

Opt in:

```bash
unlimited-skills telemetry on
```

Opt out:

```bash
unlimited-skills telemetry off
```

Telemetry preference is stored locally in `~/.unlimited-skills/registration.json`.

## Registration credential

Community registration in v0.1 does not require an email address. The CLI creates a local install id and Ed25519 device key, sends only the public key and key thumbprint to the registry, and stores the private key plus hosted-service token in `~/.unlimited-skills/registration.json`.

Email-bound device registration is planned for v0.2.
