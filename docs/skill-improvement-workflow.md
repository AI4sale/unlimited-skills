# Skill Improvement Workflow

The skill improvement workflow is a maintainer-controlled remediation loop that connects explicit feedback and registry evaluations to signed public metadata. It is not an automatic skill rewriting or publishing system.

## Flow

1. Registry skill evals produce metadata-only quality results.
2. Explicit catalog feedback can create low-quality, compatibility, missing-capability, documentation, or security issue signals.
3. The private registry generates an improvement backlog from those signals.
4. Maintainers triage candidates, assign owners, accept or reject remediation work, and mark accepted candidates fixed pending eval.
5. The registry catalog quality report includes a public-safe skill improvement section.
6. The public client displays signed improvement status, known issues, deprecation or retirement warnings, and preview-only update recommendations.

## Maintainer Control

Candidates require maintainer review before they affect public recommendations. The backlog can track `new`, `accepted`, `fixed_pending_eval`, `fixed`, `wont_fix`, `deprecated`, `duplicate`, and security-escalated states, but those states are metadata. They do not mutate catalog artifacts by themselves.

## Public Client Surface

The public client can show:

- `catalog improvement-status <item_id>`;
- `catalog known-issues <item_id>`;
- `catalog update-recommendations`;
- `catalog update-preview <item_id>`;
- `catalog deprecation-status <item_id>`.

All update recommendations are preview-only. The client rejects recommendation payloads that claim automatic install, update, remove, rewrite, publish, sign, or channel promotion behavior.

## Security And Privacy

- No automatic skill rewriting.
- No auto-publish.
- No untrusted script execution.
- No prompt upload.
- No task text upload.
- No user telemetry.
- No production hosted calls in public tests.
- No private skill bodies in the public repo.
- No tokens, device proofs, private keys, local paths, repo paths, search queries, or customer data in logs.

Support bundles include only aggregate skill improvement summary counts.
