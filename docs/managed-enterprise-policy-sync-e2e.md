# Managed Enterprise Policy Sync E2E

Status: v0.3.0-alpha development.

This E2E verifies the public client side of managed Enterprise Skill Lock delivery:

```bash
python scripts/run-managed-policy-sync-e2e.py --fixture-mode --temp-home
```

External local registry mode:

```bash
python scripts/run-managed-policy-sync-e2e.py \
  --registry-url http://127.0.0.1:8788 \
  --temp-home
```

Do not point this test at production. The runner refuses known production hosts.

## Fixture Coverage

- registration;
- bearer token and signed device proof;
- missing, invalid, and replayed proof rejection;
- signed `enterprise-policy` assignment install;
- signed update;
- signed managed remove;
- unmanaged local policy remove refusal;
- enforcement refusals for disallowed registry, release channel, community install, and local fallback;
- tampered assignment rejection;
- unknown-key assignment rejection;
- forbidden-field request scan;
- audit redaction for token and device private key material.

The fixture does not require the private registry checkout. It simulates the `/v1/policy/sync` contract with local signed assignments.

## External Mode

External mode expects a local private registry API that:

- serves `GET /v1/public-keys` with an active `enterprise-policy` Ed25519 key;
- supports `POST /v1/installations/register`;
- supports `POST /v1/policy/sync`;
- has a compatible policy assignment prepared for the test install.

The runner still uses an isolated temp HOME and does not upload skill bodies, prompts, source code, local paths, search queries, hosted tokens, secrets, or device private keys.
