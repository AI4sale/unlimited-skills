# Hub Allowlist Sync

Local Skill Hub launches only from a validated allowlist. The private registry audit verdict is `YES_WITH_ALLOWLIST`, so full catalog distribution is disabled.

## Local Layout

Hub state lives under:

```text
~/.unlimited-skills/hub/
  hub.json
  allowlist.v1.json
  allowlist.meta.json
  clients.json
  logs/
```

`hub.json` stores local hub id and token hashes. `allowlist.v1.json` is the validated cached allowlist. `allowlist.meta.json` records source, SHA256, audit verdict, and policy summary.

## Bootstrap

For offline/dev fixtures:

```bash
unlimited-skills hub init --allowlist examples/hub/allowlist-fixture.v1.json
unlimited-skills hub status --json
```

This does not require hosted registration because the operator explicitly provided a local allowlist file. The file is validated before caching.

For registered hosted refresh:

```bash
unlimited-skills hub sync --dry-run --json
unlimited-skills hub sync
```

`hub sync` calls the registered hosted contract:

```text
POST /v1/hub/allowlist
```

The request sends install id, client version, current cached allowlist SHA256, and local hub id. It does not send local skill bodies, prompts, source code, or local paths.

If the installation is not registered, sync fails with:

```text
Registration is required for Local Skill Hub allowlist sync. The MIT local core still works offline.
```

## Validation

Cached allowlists must preserve:

- `schema_version=1`
- `requires_registration=true`
- `full_catalog_distribution_allowed=false`
- `free_active_client_instance_limit=100`
- `hub_executes_skills=false`
- `hosted_registry_receives_search_queries_by_default=false`

Distributable allowlist entries must include `name`, `collection`, `sha256`, and `hub_behavior`. Blocked, local-only, and needs-review skills are rejected if they appear in the distributable allowlist.

The public repo may include schemas, docs, sanitized examples, and fake fixture allowlists. It must not include private registered skill bodies, customer data, secrets, private repository paths, or a real private allowlist unless explicitly intended for publication.

## Startup

After bootstrap:

```bash
unlimited-skills hub serve
```

If no explicit `--allowlist` is provided, the server uses:

```text
~/.unlimited-skills/hub/allowlist.v1.json
```

If no cached allowlist exists, startup fails clearly and does not fall back to full catalog distribution.
