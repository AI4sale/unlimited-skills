# Production Registry Contract E2E

This runner verifies the public client against a production-shaped registered registry API contract without calling the hosted production service.

Fixture mode is standalone and does not require the private registry checkout:

```bash
python scripts/run-production-registry-contract-e2e.py --fixture-mode --temp-home
```

Against a local private production registry from `AI4sale/unlimited-skills-registry`:

```bash
cd /path/to/unlimited-skills-registry
python scripts/run-production-registry.py --host 127.0.0.1 --port 8788

cd /path/to/unlimited-skills
python scripts/run-production-registry-contract-e2e.py --registry-url http://127.0.0.1:8788 --temp-home
```

The external mode fetches trusted manifest keys from `/v1/public-keys`. Fixture mode generates a temporary Ed25519 registry key and exports it only through the temporary test environment.

## Coverage

- temporary HOME and temporary skill library;
- registered installation with generated device key material;
- bearer token plus `X-ULS-Proof` on protected registry calls;
- missing, invalid, and replayed device proof rejection;
- signed catalog and collection update manifest verification;
- update apply with SHA256 archive verification and safe extraction;
- signed enhancement manifest download;
- signed hub allowlist sync;
- hub heartbeat and entitlement refresh;
- team create and signed team sync dry-run;
- no production hosted calls in fixture mode;
- raw tokens and private keys are not printed by the runner.

The runner refuses production hosts such as `unlimited.ai4.sale`, `api.github.com`, and `github.com`.

## Client Resilience

The public client uses one shared service request path for hosted JSON POST calls. Safe, idempotent hosted reads can opt into bounded retries:

- catalog;
- collection update checks;
- enhancement manifest lookup;
- hub allowlist sync;
- hub heartbeat and entitlement refresh;
- team service reads and sync planning.

Registration itself does not retry by default. Authentication, authorization, signature, and validation failures are not retried.

Successful catalog and collection update responses are cached under `registry-cache/`. If the registry is unreachable later, `catalog list` and `updates check` can fall back to the cached signed response. Manifest verification still runs after fallback, so unsigned, tampered, unknown-key, revoked-key, wrong-scope, and wrong-origin responses are not masked by offline cache.
