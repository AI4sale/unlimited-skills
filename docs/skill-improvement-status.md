# Skill Improvement Status

Skill improvement status is a registered, signed, metadata-only catalog surface for remediation visibility. It helps users see known issues, fix status, recommended channel/version, deprecation or retirement status, compatibility notes, and whether an installed item is stale.

The v0.3.9-alpha integration gate connects this public client surface to a maintainer-controlled private-registry workflow: feedback/evals create an improvement backlog, maintainers accept candidates, candidates can be marked fixed pending eval, and the catalog quality report exposes only a public-safe improvement summary.

## Commands

```bash
unlimited-skills catalog improvement-status community:browser-qa-pack:0.1.0
unlimited-skills catalog known-issues community:browser-qa-pack:0.1.0
unlimited-skills catalog deprecation-status community:browser-qa-pack:0.1.0
unlimited-skills catalog update-recommendations
unlimited-skills catalog update-recommendations --json
unlimited-skills catalog update-preview community:browser-qa-pack:0.1.0
```

## Registration And Trust

Hosted improvement status requires registration. Responses must be signed by a trusted manifest key before the client displays them.

The public client verifies these signed manifest types:

- `skill-improvement-status`;
- `skill-known-issues`;
- `update-recommendations`;
- `update-preview`;
- `deprecation-status`.

## Preview-Only Updates

Recommendations are advisory by default. `catalog update-recommendations` and `catalog update-preview <item_id>` do not download, install, update, remove, rewrite, or reindex anything.

The response contract includes `preview_only: true`, `will_install: false`, `will_update: false`, and `will_remove: false`. The client rejects recommendation payloads that claim automatic write actions.

Deprecated or retired warnings are also metadata-only. They can point to a replacement item and recommended version/channel, but they do not auto-remove or auto-install anything.

## Privacy

Improvement status is metadata-only. It must not include skill bodies, user prompts, task text, local paths, repo paths, customer data, tokens, proofs, private keys, archive URLs, or checkout URLs.

Support bundles include only aggregate improvement counters, not item ids, issue titles, recommendations, paths, prompts, or skill bodies.

No prompt upload, search query upload, user telemetry, automatic skill rewriting, auto-publish, or production hosted calls are part of the public v0.3.9-alpha tests.
