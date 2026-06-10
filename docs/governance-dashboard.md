# Governance Dashboard

The v0.4 SkillOps governance dashboard is read-only signed metadata for registered installations. It summarizes queue health, eval gates, entitlements, policies, private-pack status, and support diagnostics without exposing private catalog bodies or customer data.

## Public Contract

- Manifest scope: `skillops:governance-dashboard:v1`.
- Manifest types include queue health, eval gates, entitlements, policies, private packs, dashboard summary, and support diagnostics.
- Payloads are signed metadata only.
- Admin console output is read-only.
- Support diagnostics are counts, state names, policy modes, gate outcomes, and redacted status strings only.

## Boundary

- No queue mutation.
- No policy mutation.
- No private-pack mutation.
- No automatic install, update, or remove.
- No automatic rewriting.
- No auto-publish.
- No live billing.
- No production hosted calls in tests.
- No prompt, task text, skill body, private-pack body, token, proof, private key, local path, repository path, or search query appears in public evidence.

The public core only verifies the signed metadata contract and displays redacted summaries. Private registry implementation and private catalog content are not shipped in this repository.
