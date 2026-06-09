# Plans and Entitlements

`unlimited-skills plan` is the local UX for registered plan visibility. It does not change the MIT local core: local search, local indexing, and router usage continue to work without registration.

Commands:

```bash
unlimited-skills plan status
unlimited-skills plan status --json
unlimited-skills plan refresh
unlimited-skills plan explain private_team_packs
unlimited-skills plan doctor
```

`plan status` is cache-only and performs no network call. `plan refresh` requires registration and contacts `/v1/hub/entitlements` with the existing device proof flow.

Billing lifecycle visibility is exposed through a separate read-only command group:

```bash
unlimited-skills billing status
unlimited-skills billing status --json
unlimited-skills billing refresh
unlimited-skills billing doctor
```

`billing status` is cache-only. `billing refresh` requires registration and contacts `/v1/hub/billing-status`. The public client does not create checkout sessions, collect payment data, or enable live payment providers.

Denial vocabulary:

- `unregistered`
- `no_entitlement`
- `plan_limit_exceeded`
- `past_due`
- `suspended`
- `expired`
- `service_unavailable`
- `policy_denied`
- `unknown_feature`

Plan and billing diagnostics must not print registration tokens, device proofs, private keys, local paths, private pack bodies, private skill names, search queries, checkout URLs, payment links, invoice URLs, card data, or bank data.
