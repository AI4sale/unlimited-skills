# Privacy and Telemetry

Unlimited Skills is local-first.

By default, skills, prompts, source code, local file paths, repository names, customer names, tokens, and secrets stay on the user's machine.

## What the hosted update client may send

When a registered installation checks the hosted catalog, hosted adapted collection updates, local enhancement script metadata, or community catalog list/search metadata, the client sends only a minimal request:

- local install id;
- public device key and key thumbprint;
- client name and version;
- collection version metadata;
- collection source label;
- skill count bucket;
- compatible agent filter, tags, and query string for community search when supplied by the user.

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

Community publishing is different: when a user runs `community submit`, the selected skill or pack is intentionally uploaded for review/publication. Before upload, the client writes a local preview, prints the selected file list, metadata, byte counts, and warnings, and requires explicit confirmation. This is separate from telemetry, search, update checks, installed listing, preview, install-plan checks, or local enhancement.

`community installed` is local-only unless `--refresh` is passed.

Team operations may send:

- install id;
- team id;
- display name supplied during `team join`;
- client version;
- agent surfaces supplied during `team join`;
- collection versions and source labels;
- sync status.

Team operations must not send:

- local skill bodies;
- prompts or conversation history;
- source code;
- full local paths;
- repository paths;
- customer names;
- environment variables;
- tokens or secrets;
- device private keys.

Team sync fetches approved hosted/team collection manifests. It does not upload local skills by default. Local team audit logs are redacted and must not include tokens, auth headers, device private keys, or sensitive download URLs.

## Service diagnostics

Service onboarding diagnostics are privacy-safe support commands:

```bash
unlimited-skills service status
unlimited-skills service doctor
unlimited-skills service verify-trust
unlimited-skills service test-registration --dry-run
unlimited-skills service test-proof
```

`service status` is local-only unless `--refresh` is passed. `service doctor` contacts only `GET /health`, optional `GET /ready`, and `GET /v1/public-keys`, and prints the exact endpoint list. `service verify-trust` contacts only `GET /v1/public-keys`. `service test-registration --dry-run` and `service test-proof` send nothing.

Service diagnostics must not upload skill bodies, skill names, prompts, search queries, local paths, repository paths, environment variable values, tokens, or private keys. Diagnostic output uses presence markers for hosted credentials and device keys.

Managed Enterprise Skill Lock sync sends install id, client version, and a local policy summary to `/v1/policy/sync`. It must not upload skill bodies, prompts, source code, local paths, repository paths, search queries, environment variable values, tokens, secrets, or device private keys. The response must be a signed `enterprise-policy` assignment manifest before the client applies any local policy change.

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
