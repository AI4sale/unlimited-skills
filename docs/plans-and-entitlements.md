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

Denial vocabulary:

- `unregistered`
- `no_entitlement`
- `plan_limit_exceeded`
- `suspended`
- `service_unavailable`
- `policy_denied`
- `unknown_feature`

Plan diagnostics must not print registration tokens, device proofs, private keys, local paths, private pack bodies, private skill names, or search queries.
