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

The support manifest excludes:

- private pack names by default;
- private skill names;
- private skill bodies;
- raw archive URLs;
- local paths;
- auth headers;
- hosted tokens;
- device proofs;
- private keys.

The support manifest is a local diagnostic artifact. Users decide whether to share it with support.
