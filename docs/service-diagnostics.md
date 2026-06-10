# Service Diagnostics

Service diagnostics are an onboarding and support surface for registered hosted services. They are intentionally narrower than catalog/update commands.

## Commands

```bash
unlimited-skills service configure --url <url>
unlimited-skills service status
unlimited-skills service status --refresh
unlimited-skills service doctor
unlimited-skills service verify-trust
unlimited-skills service test-registration --dry-run
unlimited-skills service test-proof
```

## Network behavior

`service status` is local-only unless `--refresh` is passed.

Setup reports and support bundles use the same service diagnostics v2 snapshot as `service status` without refresh. The shared snapshot reports local registration, hosted credential presence, local device identity presence, compatible trust keys, next diagnostic commands, and whether any network refresh was performed.

`service doctor` may contact only:

- `GET <service-url>/health`
- `GET <service-url>/ready`
- `GET <service-url>/v1/public-keys`

`service verify-trust` may contact only:

- `GET <service-url>/v1/public-keys`

`service test-registration --dry-run` and `service test-proof` do not contact the service.

Tests must use fixture/local mode by default and must not call production hosted services.

`service_health_snapshot` is the shared internal contract for setup and support flows. By default it does not contact the service. Network checks require explicit refresh through `service status --refresh` or `service doctor`.

## Privacy boundary

Diagnostics must not upload:

- skill bodies;
- skill names;
- prompts;
- search queries;
- local paths;
- repository paths;
- environment variable values;
- tokens;
- private keys.

Diagnostic output uses presence markers for credentials and device key material. Errors are passed through the shared redactor before printing.

Use `unlimited-skills plan doctor` for cached plan and entitlement diagnostics. It follows the same redaction boundary and excludes private skill names, local paths, private pack bodies, tokens, device proofs, and private keys.

## Trust checks

Trust verification compares remote `/v1/public-keys` records against bundled, local, and environment trust records. A service is compatible when at least one remote key is locally trusted for the required signed-manifest scopes:

- `hub-allowlist`
- `catalog-updates`
- `enhancement-manifest`
- `team-sync-manifest`
- `release-channels`
- `private-team-pack`

The command does not import or mutate trust. Operators must use explicit `trust import`/`trust revoke` commands for local trust-store changes.

## Private Team Packs

`service status` and `service doctor` include local private-pack diagnostic counters. These counters are local metadata only and do not call private-pack list, preview, manifest, download, or access-check endpoints.

The private-pack diagnostic block includes installed count, revoked count, stale count, failed-signature count, SHA mismatch count, access-denied count, and last error codes. It excludes private pack names by default, private skill names, private skill bodies, raw archive URLs, local paths, tokens, proofs, and private keys.

Hosted private-pack operations can fail with registry-side entitlement denials such as `no_private_pack_entitlement`. Diagnostics report those as error codes only; they do not retry privileged hosted operations or include private pack identifiers by default.

Use `unlimited-skills private-packs access-check <pack_id> --json` for an explicit hosted entitlement check. The command reports normalized denial reasons such as `no_entitlement`, `not_team_member`, `wrong_agent`, `wrong_channel`, `revoked`, `policy_denied`, and `service_unavailable`.
