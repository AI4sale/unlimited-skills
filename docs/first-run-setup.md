# First-Run Setup

`unlimited-skills setup` is the guided onboarding command for a new or repaired installation. It reports what is ready, what is blocked, and the exact next commands to run.

The setup wizard is intentionally local-first:

- it does not contact hosted services;
- it does not print tokens, private keys, auth headers, prompts, skill bodies, or raw hub tokens;
- `--dry-run` performs no writes;
- normal local-only setup may create the missing local library directory;
- it never deletes existing skills, indexes, registry packs, or local library content.

## Commands

Overview diagnostics:

```bash
unlimited-skills setup
unlimited-skills setup doctor
```

Local-only Community Core:

```bash
unlimited-skills setup --local-only
unlimited-skills setup --local-only --dry-run
unlimited-skills setup --local-only --json
```

Registered hosted-service readiness:

```bash
unlimited-skills setup --registered
unlimited-skills setup --registered --dry-run --json
```

Local Skill Hub readiness:

```bash
unlimited-skills setup --hub
unlimited-skills setup --hub --dry-run --json
```

Enterprise Skill Lock status:

```bash
unlimited-skills setup --enterprise
unlimited-skills setup --enterprise --dry-run --json
```

Hosted private team pack readiness:

```bash
unlimited-skills setup --private-packs
unlimited-skills setup --private-packs --dry-run --json
```

## Modes

### Local-Only

`--local-only` checks the local library root, `local/skills`, and the lexical index. It is the default mode for people who want Community Core without registration.

When not using `--dry-run`, the command may create the missing `local/skills` directory. It does not migrate, overwrite, sync, or delete skills.

### Registered

`--registered` explains the registration boundary for hosted catalog, hosted updates, community catalog, Team Free sync, registered local enhancement scripts, Local Skill Hub allowlist sync, and managed Enterprise policy sync.

It reports local registration state and the shared service diagnostics v2 snapshot for service/trust/device-proof readiness without calling the hosted registry. If blocked, it prints the next safe commands:

```bash
unlimited-skills service test-registration --dry-run --agent codex
unlimited-skills register --agent codex
```

### Hub

`--hub` checks the registered Local Skill Hub path:

- registration status;
- local service and trust state;
- service diagnostics v2 snapshot with registration, hosted credential, device identity, trust compatibility, and network-refresh status;
- cached allowlist metadata;
- hub client token count;
- remote client configuration.

It never serves the hub, creates a token, or syncs the allowlist automatically. It only prints the next commands.

### Enterprise

`--enterprise` checks local Enterprise Skill Lock policy status and managed policy sync state. No policy means Community Core behavior is unchanged.

The command does not install, remove, or sync policy. It points to:

```bash
unlimited-skills policy status
unlimited-skills policy explain
unlimited-skills policy managed-status --json
unlimited-skills policy sync --dry-run --json
```

### Private Packs

`--private-packs` checks hosted private team pack readiness without downloading,
installing, syncing, or uploading anything. It reports:

- registration state;
- hosted credential presence marker;
- trusted manifest key availability for `private-team-pack`;
- installed private-pack count;
- revoked count;
- stale count;
- last private-pack error codes.

The setup report does not include private pack names, private skill names, skill
bodies, archive URLs, device proofs, raw tokens, private keys, or local
filesystem paths.

## JSON Contract

Machine-readable output uses [setup-report.schema.json](../schemas/setup-report.schema.json).

Examples:

- [local-only.example.json](../examples/setup/local-only.example.json)
- [registered.example.json](../examples/setup/registered.example.json)
- [hub.example.json](../examples/setup/hub.example.json)
- [enterprise.example.json](../examples/setup/enterprise.example.json)

Important fields:

- `hosted_calls_performed`: always `false` for setup reports;
- `destructive_changes`: always `false`;
- `writes_performed`: `true` only when local-only setup creates missing local directories;
- `summary.status`: `ok`, `needs_action`, or `blocked`;
- `next_commands`: exact next commands for the selected path;
- `privacy`: confirms that tokens and private keys are redacted.

## Recommended First Run

```bash
unlimited-skills setup --local-only --dry-run
unlimited-skills setup --local-only
unlimited-skills --root ~/.codex/.unlimited-skills/library reindex --no-native-sync
unlimited-skills search "security review" --mode hybrid --limit 8 --no-native-sync
```

For registered features, run:

```bash
unlimited-skills setup --registered --dry-run
unlimited-skills service test-registration --dry-run --agent codex
unlimited-skills register --agent codex
```
