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

Returns hosted collection updates for local collection versions. Update archives use `skill-collection-zip-v1`. The client enforces SHA256 verification and safe zip extraction. Cryptographic signature verification is planned but not currently enforced.

### `POST /v1/enhancement/script`

Returns metadata and a download URL for the registered local enhancement script. The script is SHA256-verified before execution and runs locally.

### `POST /v1/teams`

Creates a registered team. The first node becomes the master/owner.

### `POST /v1/teams/join`

Requests to join a team with a join code. Manual approval is the default mode.

### `POST /v1/teams/{team_id}/sync`

Returns team-assigned collection updates. Team sync uses the same update item format as `/v1/collections/updates`.

### `POST /v1/teams/{team_id}/members/pending`

Lists pending join requests for the master instance.

### `POST /v1/teams/{team_id}/members/{member_install_id}/approve`

Approves a pending member from the master instance.

### `POST /v1/teams/{team_id}/approval-mode`

Sets team join approval mode. Community plans are capped server-side; business/enterprise enforcement is outside the public MIT client.

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
