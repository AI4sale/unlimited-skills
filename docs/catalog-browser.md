# Catalog Browser

The catalog browser is the registered, signed metadata surface for discovering reviewed skill packs across official, community, and private-visible sources.

It is not local RAG and it is not a hosted prompt proxy. The client asks the hosted registry for reviewed metadata, verifies the signed response, filters out unsafe statuses, and only then shows or installs eligible items.

## Commands

```bash
unlimited-skills catalog browse --source community --compatible-agent codex --json
unlimited-skills catalog search "browser qa" --source community --json
unlimited-skills catalog filters
unlimited-skills catalog preview community:browser-qa-pack:0.1.0
unlimited-skills catalog install community:browser-qa-pack:0.1.0 --dry-run
unlimited-skills catalog install community:browser-qa-pack:0.1.0 --yes
unlimited-skills catalog feedback community:browser-qa-pack:0.1.0 --type install_failure --dry-run
unlimited-skills catalog feedback-status community:browser-qa-pack:0.1.0 --json
```

`catalog list` remains the official collection/update metadata command. `catalog browse`, `catalog search`, `catalog filters`, `catalog preview`, `catalog install`, `catalog feedback`, and `catalog feedback-status` are the user-facing discovery and quality-signal commands.

## Registration Boundary

Catalog browser operations require a registered installation. Without registration, local MIT commands still work:

- `search`;
- `list`;
- `view`;
- `where`;
- `reindex`;
- `vector-reindex`;
- `serve`;
- `adapt`;
- agent installers;
- public `self-update`.

The registration-gated browser sends only registration/device proof metadata, client version, filters, query text for search, and current collection version summaries. It must not upload skill bodies, prompts, source code, full local paths, repository paths, customer names, environment variable values, tokens, secrets, or device private keys.

## Safety Rules

The client enforces these rules before showing or installing items:

- hosted browser responses must be signed by a trusted manifest key;
- visible results include only `approved` or `published` items by default;
- `pending_review`, `rejected`, and `withdrawn` items are hidden even if the server accidentally returns them;
- deprecated or retired items are hidden unless `--include-deprecated` is explicitly requested;
- install requires signed approved or published metadata;
- install refuses metadata that includes skill bodies;
- dry-run install verifies metadata and writes nothing;
- non-dry-run install currently delegates write operations only for community-source items.

Preview and search responses are metadata-only. They are intended to help users decide what to install without loading skill bodies into the model context or exposing private packs.

## Install Behavior

For community-source items, `catalog install <item-id> --yes` delegates the final write path to the existing Community Skills install flow after the signed browser metadata check passes. That flow requests the install plan, verifies signed approved/published metadata, downloads the archive over HTTPS, checks SHA256, safely extracts the archive, writes under `registry/<collection>/`, records local installed metadata, and reindexes unless skipped.

Official and private-visible catalog browser items are metadata/dry-run only until their dedicated install-plan capability checks are implemented.

## Feedback

`catalog feedback` submits explicit, redacted feedback for one catalog item. It requires `--yes` unless `--dry-run` is used. `catalog feedback-status` returns aggregate status for an item. Feedback commands must not send prompts, task text, skill bodies, local paths, repo paths, customer data, tokens, proofs, private keys, archive URLs, checkout URLs, or payment links.

## Support Bundle Redaction

`unlimited-skills support bundle` reports only a redacted catalog browser summary:

- registered browser operation flag;
- metadata-only flag;
- no search queries;
- no item names;
- no skill bodies;
- no private paths.

See `schemas/catalog-browser-client-state.schema.json` and `examples/catalog-browser/*.example.json` for the public contract shape.
