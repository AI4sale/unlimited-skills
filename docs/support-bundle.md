# Support Diagnostic Bundle

`unlimited-skills support bundle` creates a redacted support archive for debugging local installation state.

The bundle is designed for support handoff, issue reports, and early-access registry debugging. It is metadata-only by default.

## Commands

```bash
unlimited-skills support bundle
unlimited-skills support bundle --out support-bundle.zip
unlimited-skills support bundle --json
unlimited-skills support bundle --dry-run
unlimited-skills support bundle --include-paths
```

`--dry-run` builds the same redacted diagnostics and manifest without writing a zip file.

`--json` prints the redacted manifest. It does not print `diagnostics.json` to stdout because diagnostics can be verbose.

`--include-paths` allows local paths in the diagnostics. Leave it off for public issue reports and shared logs.

## Archive Contents

The zip contains:

- `manifest.json`: bundle metadata, privacy flags, file list, and summary counts;
- `diagnostics.json`: redacted local diagnostic metadata;
- `README.txt`: short support note explaining the privacy boundary.

## Included

- Unlimited Skills client version;
- OS/Python platform metadata;
- local library counts;
- index/vector presence;
- registration status with credentials reduced to presence markers;
- local service/trust status without hosted calls;
- Local Skill Hub allowlist/token count/remote config metadata;
- Enterprise Skill Lock policy summary and managed policy status;
- existing `doctor` diagnostics after redaction.

## Excluded

The bundle must not include:

- `SKILL.md` bodies;
- prompts;
- search queries;
- environment variable values;
- hosted tokens;
- hub tokens;
- auth headers;
- device private keys;
- private local skill names;
- raw device proofs;
- local paths unless `--include-paths` is passed.

The command does not contact hosted services. It reads local files only and does not run skills.

## JSON Contract

The manifest follows [support-bundle.schema.json](../schemas/support-bundle.schema.json).

Example: [support-bundle-manifest.example.json](../examples/support/support-bundle-manifest.example.json).
