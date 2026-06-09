# Production Registry Onboarding

This alpha client keeps the local MIT core available without registration. Service onboarding is only for registered hosted features such as official adapted catalog metadata, collection updates, community catalog access, Team Free sync, and Local Skill Hub allowlist sync.

## Configure the service URL

```bash
unlimited-skills service configure --url https://unlimited.ai4.sale
```

The URL is stored in private local service configuration. HTTPS is required for non-local services. Local fixture diagnostics may use localhost HTTP only with an explicit flag:

```bash
unlimited-skills service configure --url http://127.0.0.1:8765 --allow-insecure-localhost
```

## Check local state

```bash
unlimited-skills service status
```

`service status` is local-only by default. It reads service configuration, registration state, and local trust records. It does not contact the hosted registry unless `--refresh` is passed.

```bash
unlimited-skills service status --refresh
```

## Diagnose the configured service

```bash
unlimited-skills service doctor
```

`service doctor` prints the exact endpoints it contacts:

- `GET /health`
- `GET /ready` when available; a 404 is reported as optional not available
- `GET /v1/public-keys`

It checks service reachability, key scopes, local trust compatibility, registration state, signed-manifest compatibility, and local device-proof generation. It does not upload skill bodies, skill names, prompts, search queries, local paths, repo paths, environment values, tokens, or private keys.

## Verify trust

```bash
unlimited-skills service verify-trust
```

This fetches `/v1/public-keys` and compares remote key ids/scopes with bundled, local, and environment-provided trust records. It does not import trust automatically. Trust import stays explicit through the `trust import` command.

## Registration dry run

```bash
unlimited-skills service test-registration --dry-run --agent codex
```

This builds the registration payload shape and prints a redacted preview. It sends nothing. The public device key value is replaced with a presence marker in output.

## Device proof dry run

```bash
unlimited-skills service test-proof
```

This uses existing local registration state to generate a proof header against a fake diagnostic path. The proof value is redacted; the command reports only whether proof generation works.

## Local commands stay local

Local MIT commands remain unregistered: `search`, `list`, `view`, `where`, `use`, `feedback`, `reindex`, `vector-reindex`, `serve`, local adapters, installers, migration scripts, native sync, and public self-update.

## Enterprise policy interaction

Enterprise Skill Lock can restrict production registry onboarding when a policy is installed:

- `service configure` refuses unapproved registry origins in enforce mode;
- hosted registration/catalog/update/team/hub requests use the same approved-registry check;
- release channels and manifest signing keys must match the installed policy when configured;
- audit mode records policy mismatches without blocking.

No policy means the onboarding flow behaves as normal Community Core plus registered hosted-service setup.
