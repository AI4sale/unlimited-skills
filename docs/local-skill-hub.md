# Local Skill Hub

Local Skill Hub is a registered local/LAN service for shared skill storage and retrieval across many agent instances.

It exists because 10, 100, or 1,000 agent runtimes should not each maintain separate skill libraries, indexes, and update state. A registered hub centralizes retrieval/storage locally, while each client still decides whether it can use a selected skill.

## Product Boundary

- Existing `unlimited-skills serve` remains the free MIT local daemon and does not require registration.
- New `unlimited-skills hub serve` is the registered Local Skill Hub and requires registration.
- Local CLI commands such as `search`, `list`, `view`, `reindex`, `adapt`, and `serve` continue to work offline without registration.

Registered users can use Local Skill Hub for free up to 100 active client instances. An active client instance is a registered agent/runtime client that contacted the hub within the last 30 days.

## Catalog Readiness

The private registry audit scanned 315 skills and returned `YES_WITH_ALLOWLIST`.

That verdict means Local Skill Hub must use allowlist-only distribution. Full catalog distribution is disabled. The hub may distribute only skills that the private registry allowlist marks as hub-safe.

## Architecture

```text
hosted registry -> registered local hub -> agent clients
```

The hosted registry provides approved catalog metadata and allowlisted collection updates to registered hubs. The local hub stores and retrieves skills for local/LAN clients. Agent clients request relevant skill metadata or selected skill bodies from the hub.

The hub does not execute skills. It does not run downloaded scripts. Tool, platform, OS-specific, and package requirements remain client-side and must be verified by the client before use.

Local search queries are not sent to the hosted registry by default. Hosted registry calls are for registration, allowlisted catalog/update metadata, and explicitly requested hosted actions.

## Runtime MVP v1

Bootstrap local hub state:

```bash
unlimited-skills setup --hub --dry-run
```

The setup wizard checks registration, service trust, cached allowlist metadata, hub token presence, and remote client configuration without serving the hub or contacting hosted services.

```bash
unlimited-skills hub init
unlimited-skills hub init --allowlist examples/hub/allowlist-fixture.v1.json
unlimited-skills hub sync --dry-run
unlimited-skills hub sync
```

`hub init` creates:

```text
~/.unlimited-skills/hub/
  hub.json
  allowlist.v1.json
  allowlist.meta.json
  clients.json
  logs/
```

`hub init --allowlist <file>` is the offline/dev fixture path and does not require hosted registration. `hub sync` is the registered hosted refresh path and requires registration. See [hub-allowlist-sync.md](hub-allowlist-sync.md).

Start from the cached allowlist:

```bash
unlimited-skills hub serve
```

Or pass an explicit fixture path:

```bash
unlimited-skills hub serve --allowlist ./examples/hub/allowlist-fixture.v1.json
```

If neither an explicit allowlist nor a cached allowlist exists, startup fails clearly. The hub never falls back to full catalog distribution.

MVP endpoints:

- `GET /health`
- `GET /v1/hub/status`
- `GET /v1/hub/metrics`
- `POST /v1/clients/register`
- `POST /v1/clients/heartbeat`
- `GET /v1/clients`
- `POST /v1/clients/{client_id}/deactivate`
- `POST /v1/skills/search`
- `POST /v1/skills/resolve`
- `GET /v1/skills/{name}`
- `GET /v1/skills/{name}/manifest`
- `POST /v1/skills/use`
- `POST /v1/skills/feedback`

Authentication:

- `GET /health` is open.
- All `/v1/...` endpoints require a valid hub client token.
- Tokens are created with `unlimited-skills hub token create --label <label>`.
- Tokens can be listed and revoked with `hub token list` and `hub token revoke <token_id>`.
- Token values are stored as hashes and are printed only once when created.

Client lifecycle and observability:

- Registered clients are persisted in `~/.unlimited-skills/hub/clients.json`.
- The active-client quota counts non-deactivated clients seen within the last 30 days.
- `POST /v1/clients/{client_id}/deactivate` removes a client from the active quota without deleting its audit trail.
- `GET /v1/hub/metrics` exposes local counters for uptime, request events, client quota, and skill totals.
- Hub audit events are written to `~/.unlimited-skills/hub/logs/audit.jsonl`.
- Audit events record event names, client/token ids, skill names, and query SHA256 values; raw hub tokens and raw search text are not logged.

Plan heartbeat and entitlements:

```bash
unlimited-skills hub license status
unlimited-skills hub license refresh
unlimited-skills hub heartbeat --dry-run
unlimited-skills hub heartbeat --json
```

Heartbeat and entitlement refresh require registration and contact only the configured registration service. `hub heartbeat --dry-run` prints the exact privacy-safe payload without sending it. The payload excludes search queries, prompts, skill bodies, skill names, full local paths, repository paths, customer names, environment values, tokens, secrets, and private keys. See [hub-plan-heartbeat.md](hub-plan-heartbeat.md).

Remote client:

```bash
unlimited-skills remote configure --url http://127.0.0.1:8766 --token-env ULS_HUB_TOKEN --fallback local_allowed
unlimited-skills remote status
unlimited-skills remote search "browser QA"
unlimited-skills remote resolve "browser QA" --agent codex
unlimited-skills remote view browser-qa
```

`remote search`, `remote resolve`, and `remote view` call only the configured Local Skill Hub. They do not call the hosted registry and they do not forward local search queries to AI4sale hosted services by default. The client sends the hub token in `Authorization: Bearer <token>` and `X-ULS-Hub-Token` for compatibility.

Install a remote-first router after the hub is configured:

```bash
export ULS_HUB_TOKEN="<hub_client_token>"
./scripts/install-codex.sh --remote-first --remote-hub-url http://127.0.0.1:8766 --hub-token-env ULS_HUB_TOKEN --remote-fallback local_allowed
./scripts/install-claude-code.sh --remote-first --remote-hub-url http://127.0.0.1:8766 --hub-token-env ULS_HUB_TOKEN --remote-fallback local_allowed
./scripts/install-hermes.sh --mode evacuate-visible-skills --remote-first --remote-hub-url http://127.0.0.1:8766 --hub-token-env ULS_HUB_TOKEN --remote-fallback hub_required --apply
./scripts/install-openclaw.sh --remote-first --remote-hub-url http://127.0.0.1:8766 --hub-token-env ULS_HUB_TOKEN --remote-fallback local_allowed
```

Remote-first installers render router instructions that prefer `remote resolve` before local search. Raw hub tokens are never written into visible router files; prefer token-env configuration for shared machines.

Capability-aware install plans:

```bash
unlimited-skills remote capabilities --agent codex --json
unlimited-skills remote install-plan browser-automation --dry-run
```

Retrieval can be centralized, but dependencies and capabilities remain local. The hub never executes skills or install commands. Install plans are dry-run metadata in this release, and secrets stay client-side.

Launch policy:

- Full catalog: no.
- Allowlist-only: yes.
- Local install plan skills: metadata/resolution with dry-run capability warnings.
- Blocked, local-only, and needs-review skills: excluded.
- No skill execution.
- No hosted query forwarding.
- Local fallback must be explicit in the client/router policy.
- Default bind is `127.0.0.1`.
- LAN bind requires explicit `--allow-lan` and at least one active hub token.
- For serious LAN deployment, use reverse proxy/TLS and normal network access controls.

Traceability:

- Local Skill Hub MVP runtime was tracked in [PR #6](https://github.com/AI4sale/unlimited-skills/pull/6). The PR is closed; this document is the release traceability note for the alpha MVP surface.

Correct launch wording:

> We can launch Registered Local Skill Hub with an allowlisted subset of the 315-skill private catalog. Full catalog distribution remains disabled until the blocked/local-only/review/tool-dependency classes are resolved.
