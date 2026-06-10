# Support Diagnostic Bundle

`unlimited-skills support bundle` prints a redacted local support manifest. The command does not upload the bundle.

```bash
unlimited-skills support bundle --json
```

For private team packs, the support manifest includes only:

- installed private-pack count;
- authorized count when available, otherwise `not_refreshed`;
- revoked count;
- stale count;
- missing target count;
- failed-signature count;
- SHA mismatch count;
- access-denied count;
- last private-pack error codes;
- optional hashed private-pack references when `--include-private-pack-refs` is explicitly passed.

For organization and team governance, the support manifest includes only:

- registered/local status;
- organization role/status, without private pack names;
- team joined/role/status/approval mode;
- entitlement state summaries for private packs, community catalog, and team sync.

For plans and entitlements, the support manifest includes only the redacted plan id, status, cache source, public feature flags, public limits, and offline-grace status.

For billing lifecycle diagnostics, the support manifest includes only the redacted plan id, entitlement source, subscription lifecycle status, sandbox billing mode, public feature allow/deny codes, and the normalized denial reason. It does not include checkout sessions or live payment provider payloads.

The support manifest excludes:

- private pack names by default;
- private skill names;
- private skill bodies;
- raw archive URLs;
- checkout URLs;
- payment links;
- invoice URLs;
- card data;
- bank data;
- local paths;
- auth headers;
- hosted tokens;
- device proofs;
- private keys.

The support manifest is a local diagnostic artifact. Users decide whether to share it with support.

Registry-side private-pack entitlement denials are represented as error codes such as `no_private_pack_entitlement`. The bundle does not include the denied pack name by default.
