# Maintainer Queue Status

Maintainer queue status is a registered, signed, read-only diagnostic surface for public-safe remediation state. It is consumed from the hosted private registry but the public client displays only sanitized metadata.

## Commands

```bash
unlimited-skills catalog maintainer-status community:browser-qa-pack:0.1.0
unlimited-skills catalog maintainer-status community:browser-qa-pack:0.1.0 --json
unlimited-skills catalog maintainer-queue-summary
unlimited-skills catalog fixed-pending-eval community:browser-qa-pack:0.1.0
unlimited-skills catalog improvement-status community:browser-qa-pack:0.1.0 --include-queue
unlimited-skills catalog update-recommendations --include-queue
```

## Trust Boundary

Hosted maintainer queue status requires registration. The local MIT core remains registration-free for search, list, view, where, reindex, vector-reindex, and other local-only commands.

The client calls `/v1/skillops/maintainer-queue/*` endpoints and verifies signed `maintainer-queue-runtime-status`, `maintainer-queue-runtime-summary`, and `maintainer-queue-fixed-pending-eval` responses before display. Tests use fake services and fixture signing keys only.

## Public Fields

Queue status output includes:

- queue status;
- severity summary;
- public-safe maintainer state;
- fixed-pending-eval evidence reference;
- eval gate reference;
- issue categories;
- recommended user action.

Queue summary output includes only counts and categories. It does not include item ids or private queue records.

## Privacy And Mutation Boundary

Maintainer queue diagnostics are metadata-only. They must not include prompts, task text, skill bodies, maintainer private notes, local paths, repo paths, customer data, tokens, proofs, private keys, archive URLs, or checkout URLs.

`catalog update-recommendations --include-queue` remains preview-only. It does not install, update, remove, download, rewrite, reindex, or publish anything.
