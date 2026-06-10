# Eval Release Gates

Eval release gates are the registry-side SkillOps release boundary used by `v0.4.0-alpha` E02. The public repository records only the client-facing contract and integration evidence; registry implementation and private catalog data stay in the private registry.

## Contract

- Gate outcomes: `pass`, `pass_with_warning`, `block_release`, `require_override`, `rollback_recommended`, and `manual_review_required`.
- Score bands: `A`, `B`, `C`, `D`, `F`, and `blocked`.
- Required checks include eval coverage, signed metadata, capability compatibility, improvement backlog status, and feedback severity.
- Overrides require a release owner, reason, scope, expiry, risk acceptance, and signed evidence reference.
- Rollback recommendations are metadata for human operators. They do not trigger automatic production rollback.

## v0.4.0-alpha Boundary

- The release owner decides promotion.
- The operator workflow prepares evidence only.
- No production rollout.
- No auto-publish.
- No live billing.
- No production signing keys in tests.
- No prompt, task text, skill body, private-pack body, token, proof, private key, local path, repository path, or search query is included in public release evidence.
