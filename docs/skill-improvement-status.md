# Skill Improvement Status

Skill improvement status is a registered, signed, metadata-only catalog surface for remediation visibility. It helps users see known issues, fix status, recommended channel/version, deprecation or retirement status, compatibility notes, and whether an installed item is stale.

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

## Privacy

Improvement status is metadata-only. It must not include skill bodies, user prompts, task text, local paths, repo paths, customer data, tokens, proofs, private keys, archive URLs, or checkout URLs.

Support bundles include only aggregate improvement counters, not item ids, issue titles, recommendations, paths, prompts, or skill bodies.
