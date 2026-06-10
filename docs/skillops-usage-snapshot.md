# SkillOps Usage Snapshot

`unlimited-skills skillops usage-snapshot` builds a local-only usage snapshot for future SkillOps recommendation context. It is designed for diagnostics and recommendation planning, not telemetry.

The command reads local metadata and cached redacted summaries only. It does not call hosted services, upload data, forward queries, install skills, update skills, remove skills, rewrite skills, reindex, or publish anything.

## Commands

```bash
unlimited-skills skillops usage-snapshot
unlimited-skills skillops usage-snapshot --json
unlimited-skills skillops usage-snapshot --out usage-snapshot.json
unlimited-skills skillops usage-snapshot --dry-run
unlimited-skills skillops usage-snapshot explain
```

`--out` writes the JSON snapshot to a local file. `--dry-run` builds and prints the snapshot but skips the output write.

## Included Data

The snapshot may include:

- client version;
- OS bucket: `windows`, `macos`, `linux`, or `other`;
- installed official, community, private, and local skill counts;
- local library counts and index presence;
- enabled release channel;
- registration and plan status as redacted feature flags;
- local policy mode and governance summary availability;
- recommendation outcome counts from the local policy table;
- catalog quality warning counts;
- maintainer queue status counts;
- update recommendation counts;
- support-bundle availability for counts-only inclusion.

## Excluded Data

The snapshot excludes by default:

- prompts;
- task text;
- skill bodies;
- search queries;
- local paths;
- repository paths;
- customer data;
- environment values;
- tokens;
- proofs;
- private keys;
- private pack names;
- private skill names.

The schema is `schemas/skillops-usage-snapshot.schema.json`. A static example is available at `examples/skillops/usage-snapshot.example.json`.

## Support Bundle Behavior

Support bundles may include usage snapshot counts only. They do not include snapshot detail, local paths, names, skill bodies, prompts, search queries, tokens, proofs, or private keys.
