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

For catalog browser diagnostics, the support manifest includes only a redacted metadata summary:

- registered browser operation flag;
- metadata-only flag;
- query inclusion flag, always false;
- item-name inclusion flag, always false;
- skill-body inclusion flag, always false;
- private-path inclusion flag, always false.

For catalog feedback diagnostics, the support manifest includes only the feedback boundary flags. It does not include raw feedback payloads, item names, prompts, skill bodies, local paths, tokens, proofs, or private keys.

For catalog quality diagnostics, the support manifest includes summary counts only:

- known quality status count;
- blocked count;
- warning count;
- deprecated or retired count;
- feedback issue category count.

It does not include catalog item ids, item names, raw quality records, raw feedback, prompts, skill bodies, local paths, repo paths, customer data, tokens, proofs, or private keys.

For skill improvement diagnostics, the support manifest includes summary counts only:

- known item count;
- open issue count;
- critical or high issue count;
- update recommendation count;
- remove recommendation count;
- deprecated or retired count;
- stale installed count.

It does not include catalog item ids, item names, issue titles, raw recommendations, prompts, skill bodies, local paths, repo paths, customer data, tokens, proofs, or private keys.

For maintainer queue diagnostics, the support manifest includes only queue status counts and issue categories:

- total queued count;
- queue status counts;
- severity summary counts;
- fixed-pending-eval count;
- blocked eval gate count;
- public-safe issue categories.

It does not include catalog item ids, item names, prompts, task text, skill bodies, maintainer private notes, local paths, repo paths, customer data, tokens, proofs, or private keys.

For SkillOps usage snapshot diagnostics, the support manifest includes counts only:

- physical skill file count;
- official, community, private, and local skill counts;
- index record count;
- recommendation outcome counts;
- quality warning counts;
- update recommendation counts;
- maintainer queue counts.

It does not include snapshot details, private pack names, private skill names, skill bodies, prompts, task text, search queries, local paths, repo paths, customer data, tokens, proofs, or private keys.

For v0.4 blocker-closure reports, support diagnostics remain counts, booleans, status strings, and redacted summaries only. No prompt or task content, skill content, local or repository locations, customer data, tokens, device proofs, private keys, or search terms may appear in the report payload.

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
- private keys;
- catalog browser search queries;
- catalog browser item names;
- raw catalog feedback payloads.
- raw catalog quality or evaluation records.
- raw skill improvement records or update recommendations.
- raw maintainer queue records.
- raw SkillOps usage snapshot details.

The support manifest is a local diagnostic artifact. Users decide whether to share it with support.

Registry-side private-pack entitlement denials are represented as error codes such as `no_private_pack_entitlement`. The bundle does not include the denied pack name by default.
