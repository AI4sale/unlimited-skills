# Hosted Registry API v1

This is the public client-facing contract for registered Unlimited Skills hosted services. The public MIT repository contains the local client/core, schemas, sanitized examples, and contract tests. It does not contain the private hosted registry backend or private registered skill bodies.

Base URL:

```text
https://unlimited.ai4.sale
```

Client overrides:

- `UNLIMITED_SKILLS_SERVICE_URL`
- `unlimited-skills register --server-url <url>`

## Authentication

`POST /v1/installations/register` does not require `Authorization`.

Registered endpoints require:

```http
Authorization: Bearer <license_token>
X-ULS-Proof: <base64url encoded signed proof>
```

The proof is a base64url-encoded JSON object signed by the local Ed25519 device key. The private key stays on the device and is never sent to the registry.

Proof message fields, joined with newlines in this order:

1. `method`
2. `path`
3. `body_sha256`
4. `timestamp`
5. `nonce`
6. `install_id`
7. `key_thumbprint`

The proof JSON contains:

- `install_id`
- `key_thumbprint`
- `timestamp`
- `nonce`
- `body_sha256`
- `signature`

## Common Request Fields

- `schema_version`: currently `1`
- `install_id`: local installation id
- `client.name`: `unlimited-skills`
- `client.version`: client version
- `collections`: local collection state for catalog/update/team sync requests

Catalog and update checks must not include user local skill names or local paths.

Community list/search requests may include a user-supplied query, tags, compatible-agent filter, client metadata, install id, and collection version state. They must not include local skill bodies.

## Common Response Fields

Hosted responses may include:

- `schema_version`
- `request_id`
- `server_time`
- `plan`
- `features_enabled`

Current clients tolerate missing optional common fields where older endpoints do not return them yet.

## Endpoints

### `POST /v1/installations/register`

Registers one local installation/device. Request sends public key, key thumbprint, client metadata, optional agent label, skill-count bucket, and telemetry preference. Response returns a hosted-service token and registration metadata.

### `POST /v1/catalog`

Returns registered hosted catalog metadata for this installation. The official adapted-skill catalog is registration-gated, early-access, and already populated. Exact catalog contents are delivered only to registered installs. Public examples are sanitized and do not include `SKILL.md` bodies.

### `POST /v1/collections/updates`

Returns hosted collection updates for local collection versions. Update archives use `skill-collection-zip-v1`. Hosted update responses must include a valid signed manifest envelope. The client verifies `manifest_signature` against a key trusted for the `catalog-updates` scope and registry origin, then enforces archive SHA256 verification and safe zip extraction before installing.

### `POST /v1/enhancement/script`

Returns metadata and a download URL for the registered local enhancement script. The script is SHA256-verified before execution and runs locally.

### `POST /v1/community/list`

Returns registered community catalog item metadata. This is a hosted metadata call only; it must not receive local skill bodies.

### `POST /v1/community/search`

Searches registered community catalog item metadata by user-supplied query, tags, and compatible-agent filters. This endpoint must not receive local skill bodies.

### `POST /v1/community/preview`

Returns sanitized item metadata, manifest summary, included skill names from hosted public metadata, release notes, required capabilities, install plan summary, and warnings. Preview does not require or expose full skill bodies.

### `POST /v1/community/install`

Returns a community install plan for a catalog item. The plan includes target collection, version, archive URL, SHA256, skill count, and warnings. The client downloads the archive, verifies SHA256, rejects path traversal, installs locally, and rebuilds the lexical index.

### `POST /v1/community/submit`

Uploads only the selected skill or pack after local validation, preview generation, and explicit user confirmation. This is the only community flow that sends selected skill content to the registry for maintainer review.

### `POST /v1/community/submission-status`

Returns one submission status when `submission_id` is supplied, or recent submissions for the installation when omitted. Public client responses expose reviewer notes when provided, but not private review internals.

### `POST /v1/teams`

Creates a registered team. The first node becomes the master/owner.

### `POST /v1/teams/join`

Requests to join a team with a join code. Manual approval is the default mode.

### `POST /v1/teams/{team_id}/status`

Returns redacted team status, approval mode, member counts, pending counts, and server-side limits for the registered installation.

### `POST /v1/teams/{team_id}/members`

Lists approved members by default. The client may request all statuses or pending-only members.

### `POST /v1/teams/{team_id}/sync`

Returns team-assigned collection manifests. The client supports the richer Team Free sync manifest and remains compatible with the legacy `updates` array shape. Hosted team sync responses must include a valid signed manifest envelope. The client verifies `manifest_signature` against a key trusted for the `team-sync-manifest` scope and registry origin, then enforces SHA256 verification and safe extraction before installing archives.

### `POST /v1/private-packs/list`

Returns redacted private team pack metadata authorized for the registered installation. The request must not include local skill bodies. The response must not include private skill bodies, tokens, join codes, device proofs, or private keys.

### `POST /v1/private-packs/preview`

Returns redacted metadata for one private team pack. The response includes pack id, team id, namespace, version, revocation state, archive hash, and archive size. It does not include private skill bodies.

### `POST /v1/private-packs/manifest`

Returns the signed `private-team-pack` manifest for one authorized private pack. The client verifies `manifest_signature` with scope `private-team-pack` and the registry origin before attempting download or install.

### `POST /v1/private-packs/access-check`

Returns the current installation's authorization status for a private pack without exposing raw tokens or device proof material.

### `POST /v1/private-packs/download`

Streams the authorized zip archive only after bearer token, device proof, manifest signature, revocation, agent/channel/install policy, path boundary, and SHA256 checks pass server-side. The client checks SHA256 again before safe extraction and installs only under `registry/private/<pack_id>`.

### `POST /v1/policy/sync`

Returns a managed Enterprise Skill Lock policy assignment for a registered installation. This endpoint is registration-gated and must require the hosted-service token plus signed device proof.

Request fields:

- `install_id`;
- `client` with client name and version;
- `current_policy`, a local policy summary only.

The request must not include skill bodies, prompts, source code, local paths, repository paths, search queries, environment variable values, tokens, secrets, or device private keys.

Response shape:

```json
{
  "schema_version": 1,
  "manifest_type": "enterprise-policy-assignment",
  "assignment_id": "assign_...",
  "install_id": "uls_inst_...",
  "action": "install|update|remove|none",
  "assigned_at": "2026-06-09T00:00:00Z",
  "policy": {
    "schema_version": 1,
    "policy_id": "enterprise-skill-lock-default",
    "mode": "audit",
    "policy_sha256": "..."
  },
  "manifest_signature": {
    "schema_version": 1,
    "algorithm": "ed25519",
    "key_id": "registry-alpha-2026-06",
    "signed_payload_sha256": "...",
    "signature": "..."
  }
}
```

The client verifies the response with scope `enterprise-policy` and the registry origin, verifies the policy payload itself, and only then installs, updates, or removes local policy state. `action=none` makes no local change.

### `POST /v1/teams/{team_id}/members/pending`

Lists pending join requests for the master instance.

### `POST /v1/teams/{team_id}/members/{member_install_id}/approve`

Approves a pending member from the master instance.

### `POST /v1/teams/{team_id}/members/{member_install_id}/reject`

Rejects a pending member from the master/admin instance.

### `POST /v1/teams/{team_id}/members/{member_install_id}/revoke`

Revokes hosted team access for a previously approved member. This does not delete that member's local files.

### `POST /v1/teams/{team_id}/approval-mode`

Sets team join approval mode. Community plans are capped server-side; business/enterprise enforcement is outside the public MIT client.

### `POST /v1/teams/{team_id}/collections`

Lists team-assigned collections and local installed-version metadata for this team.

### `POST /v1/teams/{team_id}/leave`

Marks the current installation as left. The public client keeps local skills in place and marks local team state as left.

## Error Format

```json
{
  "schema_version": 1,
  "error": {
    "code": "registration_required",
    "message": "Registration is required for hosted registry access.",
    "retry_after_seconds": 0
  },
  "request_id": "req_example"
}
```

Known error codes:

- `registration_required`
- `invalid_proof`
- `forbidden`
- `team_not_found`
- `not_team_admin`
- `pending_approval`
- `member_limit_reached`
- `auto_approval_window_too_long`
- `plan_required`
- `not_found`
- `rate_limited`
- `server_error`

## Privacy Boundary

Hosted catalog/update checks do not upload:

- skill bodies;
- prompts or conversation history;
- source code;
- skill names from local private libraries;
- full local paths;
- repository paths;
- customer names;
- environment variables;
- tokens, secrets, or credentials;
- device private keys.

Community submissions are different: they require explicit upload confirmation for the selected skill or pack.

Hosted catalog/update checks do not upload local skill bodies.

No registration, no official hosted skill updates; the local MIT core continues to work.
