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

The first runtime MVP starts from a local `hub-allowlist.v1.json` input:

```bash
unlimited-skills hub serve --allowlist ~/.unlimited-skills/hub/hub-allowlist.v1.json
```

MVP endpoints:

- `GET /health`
- `GET /v1/hub/status`
- `POST /v1/clients/register`
- `POST /v1/clients/heartbeat`
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

Remote client:

```bash
unlimited-skills remote configure --url http://127.0.0.1:8766 --token-env ULS_HUB_TOKEN --fallback local_allowed
unlimited-skills remote status
unlimited-skills remote search "browser QA"
unlimited-skills remote resolve "browser QA" --agent codex
unlimited-skills remote view browser-qa
```

`remote search`, `remote resolve`, and `remote view` call only the configured Local Skill Hub. They do not call the hosted registry and they do not forward local search queries to AI4sale hosted services by default. The client sends the hub token in `Authorization: Bearer <token>` and `X-ULS-Hub-Token` for compatibility.

Launch policy:

- Full catalog: no.
- Allowlist-only: yes.
- Local install plan skills: metadata/resolution only until client capability checks are implemented.
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
