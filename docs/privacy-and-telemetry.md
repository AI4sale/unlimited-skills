# Privacy and Telemetry

Unlimited Skills is local-first.

By default, skills, prompts, source code, local file paths, repository names, customer names, tokens, and secrets stay on the user's machine.

## What the hosted update client may send

When a registered installation checks the hosted catalog, hosted adapted collection updates, or local enhancement script metadata, the client sends only a minimal request:

- local install id;
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
- tokens or secrets.

The local enhancement script is downloaded from the registry, but it runs on the user's machine. Skill contents are not uploaded for enhancement.

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

## Registration email

If an email is passed during registration, the CLI stores only a SHA256 hash locally. The server may receive the registration key and account details needed to issue a hosted-service token, but the local registration file does not store the raw email.
