# Staging Signed Registry E2E

This E2E runner verifies the public client against a staging-compatible signed registry.

Fixture mode is standalone and does not require the private registry checkout:

```bash
python scripts/run-staging-registry-e2e.py --fixture-mode --temp-home
```

Against a local private staging registry from `AI4sale/unlimited-skills-registry`:

```bash
cd /path/to/unlimited-skills-registry
python scripts/run-staging-registry.py --host 127.0.0.1 --port 8787

cd /path/to/unlimited-skills
python scripts/run-staging-registry-e2e.py --registry-url http://127.0.0.1:8787 --temp-home
```

The private staging runner enables dynamic archive URLs by default so the public client can download SHA256-verified packs from localhost while still verifying signed staging manifests through `/v1/public-keys`.

## Coverage

- temporary HOME and temporary skill library;
- dev registration;
- signed catalog and update manifest;
- update apply with SHA256 archive verification and safe extraction;
- signed enhancement manifest download;
- signed hub allowlist sync;
- hub token creation;
- `hub serve` with cached signed allowlist;
- `remote configure`, `remote status`, `remote search`, `remote resolve`, and `remote view`;
- unsigned, tampered, unknown-key, SHA mismatch, and path traversal rejection;
- no production hosted calls in fixture mode;
- no production hosted calls in external staging mode when the registry URL is localhost;
- raw tokens and private keys are not printed by the runner.

The runner refuses production hosts such as `unlimited.ai4.sale`, `api.github.com`, and `github.com`.
