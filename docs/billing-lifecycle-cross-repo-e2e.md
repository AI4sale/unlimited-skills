# Billing Lifecycle Cross-Repo E2E

This E2E verifies the public client billing diagnostics against the private registry sandbox billing ledger without calling production hosted services.

Fixture mode:

```bash
python scripts/run-billing-lifecycle-cross-repo-e2e.py --fixture-mode --temp-home --json
```

The fixture runner:

- loads the private registry checkout from `UNLIMITED_SKILLS_REGISTRY_REPO` or `D:\git\unlimited-skills-registry`;
- starts a localhost registry fixture with signed artifacts and device proof registration;
- exposes a test-only `/v1/hub/billing-status` endpoint backed by the registry sandbox billing tables;
- registers a temporary public client installation;
- simulates `subscription_active`, `payment_failed`, and `subscription_canceled`;
- verifies `billing refresh`, `billing doctor`, and `plan refresh` through the public CLI;
- verifies no production hosted calls are required.

External local registry mode:

```bash
python scripts/run-billing-lifecycle-cross-repo-e2e.py --registry-url http://127.0.0.1:8765 --temp-home --json
```

`--registry-url` is restricted to localhost, `127.0.0.1`, or `::1`. It is for checking an already-running local registry implementation. The runner refuses non-local URLs.

Expected lifecycle mapping:

- `subscription_active` -> billing status `active`, business entitlement active;
- `payment_failed` -> billing status `past_due`, existing business entitlement preserved;
- `subscription_canceled` -> billing denial reason `suspended`.

Privacy boundary:

The runner fails if public CLI output includes registration tokens, device private keys, device proof headers, checkout URLs, payment links, invoice URLs, card data, bank data, private skill bodies, or `SKILL.md` content.
