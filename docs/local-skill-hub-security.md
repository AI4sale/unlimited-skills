# Local Skill Hub Security

Local Skill Hub is designed as a local-first service. The default bind address is `127.0.0.1`.

LAN mode must be explicit and requires at least one active hub client token:

```bash
unlimited-skills hub token create --label "office-laptop"
unlimited-skills hub serve --host 0.0.0.0 --port 8766 --allow-lan
```

Without `--allow-lan`, or without an active token, the hub refuses to bind to non-localhost addresses. For serious LAN deployment, use a reverse proxy or network control with TLS, authentication, access logging, and IP allowlisting.

Protected hub APIs require one of:

```text
Authorization: Bearer <hub_client_token>
X-ULS-Hub-Token: <hub_client_token>
```

`GET /health` remains unauthenticated for local liveness checks. Other `/v1/...` hub endpoints require a valid, non-revoked hub token.

Client records are persisted in the local hub state and count against the active-client quota only while non-deactivated and recently seen. Operators can inspect clients, deactivate stale clients, and inspect metrics without exposing raw hub tokens.

Audit logs are local JSONL files under `~/.unlimited-skills/hub/logs/`. They intentionally avoid raw query text, raw tokens, secrets, and skill bodies.

The remote client sends both headers for compatibility. Configure it with an environment variable when possible:

```bash
export ULS_HUB_TOKEN="<hub_client_token>"
unlimited-skills remote configure --url http://127.0.0.1:8766 --token-env ULS_HUB_TOKEN
```

`unlimited-skills remote configure --token <hub_client_token>` is available for local convenience, but it stores the raw token in `~/.unlimited-skills/remote.json`. The file is written with private permissions on POSIX systems and through the same private JSON writer on Windows, but an environment-backed token is safer for shared machines.

## Safety Rules

- The hub does not execute skills or scripts.
- The hub must not store secrets in logs.
- Tokens and device proof material must be redacted in status output, errors, and audit logs.
- Hub client tokens are stored as SHA256 hashes in `~/.unlimited-skills/hub/hub.json`; raw token values are shown only once during creation.
- Remote client file-backed tokens, if explicitly configured with `--token`, are raw client credentials and must never be committed, logged, or shared.
- Registration tokens and device private keys are local private state under `~/.unlimited-skills/registration.json`.
- Local search queries are not forwarded to the hosted service by default.
- Hub logs and learning data should stay under `~/.unlimited-skills/.learning/` or `~/.unlimited-skills/hub/`.
- Local install plan skills are metadata/resolution only until client capability checks are implemented.

## Hosted Collection Sync

When the hub syncs hosted allowlists or collections, signed manifest envelopes are required and Ed25519-verified against trusted manifest public keys. The explicit local fixture path remains unsigned. Archive extraction must still be path-safe and SHA256-verified before installation.

Skill archives must not contain secrets, private customer context, private repository paths, or blocked assets. Tool/platform skills require local capability checks before use.

## Allowlist Sync

`hub sync` calls the registered hosted allowlist endpoint and caches only validated allowlist/catalog metadata under `~/.unlimited-skills/hub/`. It must not upload local skill bodies, prompts, source code, full local paths, environment values, tokens, secrets, or device private keys.

Cached allowlists are rejected if they enable full catalog distribution, remove registration requirements, allow hub-side skill execution, include blocked/local-only/needs-review skills in the distributable list, embed full `SKILL.md` bodies, or contain obvious secret fields.

## Enterprise Skill Lock

When Enterprise Skill Lock is installed, Local Skill Hub behavior can be constrained by policy:

- local fallback can be denied when `hub.remote_required=true` and `hub.local_fallback_allowed=false`;
- explicit local allowlists can be rejected when they are unsigned and `hub.unsigned_local_allowlist_allowed=false`;
- future client-limit overrides are allowed only when `hub.max_client_instances_override_allowed=true`;
- policy refusals are written to the redacted local policy audit log.

No policy means existing Local Skill Hub behavior is unchanged.
