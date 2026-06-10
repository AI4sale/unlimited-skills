# Policy-Aware Recommendations

Policy-aware recommendations are a v0.4 preview contract for deciding whether a catalog item may be shown, installed, updated, warned, or refused. The public v0.3.9-alpha follow-up defined the fixture-backed decision table and refusal-code vocabulary. The v0.4 runtime preview layer adds a public-safe preview command that combines signed catalog metadata, signed quality metadata when available, signed improvement metadata when available, local entitlement summary, and local enterprise policy summary.

The runtime preview still does not install, update, remove, rewrite, publish, or reindex skills. It only explains the decision and the next command a user or operator may run explicitly.

## Non-Goals

This contract does not:

- install, update, remove, rewrite, or reindex skills automatically;
- send telemetry automatically;
- forward hosted queries by default;
- distribute the full catalog;
- include skill bodies, prompts, task text, local paths, repo paths, customer data, tokens, proofs, or private keys;
- publish private team-pack content in the public repository.

## Outcomes

All outcomes are preview or decision-only. No recommendation command applies an install, update, or remove operation automatically; future commands that act on an outcome must require explicit user confirmation and their own policy checks.

The public outcome vocabulary is:

- `allow_preview`: metadata can be shown without claiming install eligibility.
- `allow_install`: signed metadata says install may be offered, but the user must still confirm any future install command.
- `allow_update_preview`: update advice may be shown as a preview only.
- `warn_before_install`: the item may be visible, but clients must show a warning before any explicit install command.
- `deny_install`: install advice is refused.
- `deny_update`: update advice is refused.
- `require_registration`: registration must happen before hosted recommendation advice.
- `require_entitlement`: an organization or team entitlement is required.
- `require_policy_override`: an enterprise policy owner must approve an override.
- `local_only`: local MIT skills remain available offline but have no hosted recommendation action.
- `unsupported`: the channel, agent, or metadata shape is unsupported by this client.

## Refusal Codes

Every denial outcome must include a refusal code, human-readable reason, next command, owner, action, and fallback. The v1 refusal codes are:

- `registration_required`
- `entitlement_denied`
- `policy_denied`
- `blocked_item`
- `retired_item`
- `low_score`
- `wrong_channel`
- `wrong_agent`
- `unsigned_metadata`
- `local_only`

The public schemas are:

- `schemas/recommendation-decision.schema.json`
- `schemas/recommendation-refusal.schema.json`

Public examples live in `examples/recommendations/`.

## Runtime Preview

The runtime preview contract is emitted by:

```bash
unlimited-skills catalog recommendation-preview <item_id> --json
```

For deterministic tests and reviewer checks, use:

```bash
unlimited-skills catalog recommendation-preview --fixture-case policy_denied --json
```

The payload shape is:

- `manifest_type: policy-aware-recommendation-preview`;
- top-level safety flags copied from the recommendation policy contract;
- `fixture_only: false` for live runtime previews and `fixture_only: true` for deterministic fixture previews;
- one `decision` object with outcome, reason, next command, optional refusal details, and all write flags set to false;
- `signals.catalog_metadata`;
- `signals.quality_status`;
- `signals.improvement_status`;
- `signals.entitlement`;
- `signals.policy`.

The public schema is `schemas/policy-aware-recommendation-preview.schema.json`. The example payload is `examples/recommendations/runtime-preview.example.json`.

Live preview mode requires registration because it reads signed hosted catalog metadata by item id. Unregistered clients can still produce a registration-required decision without making hosted calls. Supplemental quality and improvement metadata are best-effort by default so an unavailable supplemental endpoint cannot break the base signed catalog preview; `--strict-supplemental` makes those failures explicit for operator checks.

Runtime previews never include skill bodies, prompts, task text, local paths, repo paths, customer data, tokens, proofs, private keys, or private pack contents. Private team-pack items may appear only by metadata/reference and still require entitlement.

## Registry Inputs

The public client consumes existing registered contracts; this preview layer does not require a new registry endpoint:

- signed catalog browser `list`, `search`, `item`, `preview`, and `filters` metadata;
- signed catalog quality blocks on browser items and signed quality/eval status where available;
- signed SkillOps aggregate summaries for improvement and maintainer state;
- redacted private-pack `list`, `preview`, and `access-check` metadata for team/private items;
- signed managed Enterprise policy assignment through policy sync;
- local redacted plan/entitlement and policy summaries.

Raw maintainer backlog records, private team-pack skill bodies, local paths, prompts, proofs, tokens, and private keys are never recommendation-preview inputs or outputs.

## Fixture Coverage

The fixture table in `unlimited_skills/recommendation_policy.py` covers:

- local MIT skill;
- hosted official catalog item;
- community catalog item;
- private team pack item by reference only;
- deprecated;
- retired;
- blocked;
- low-score;
- fixed-pending-eval;
- policy-denied;
- entitlement-denied;
- registration-required;
- wrong channel;
- wrong agent;
- unsigned metadata;
- stale installed version.

The table is intentionally deterministic. It is a contract fixture for tests and client/server integration, not a ranking algorithm and not an install plan. Runtime preview uses the same outcome and refusal vocabulary.

## v0.4 B-02 Closure Boundary

B-02 is closed for public readiness by the public recommendation contract and refusal-code coverage. This closure does not approve v0.4 implementation until the final go/no-go review passes.

Hosted recommendation metadata that affects install or update advice must be signed before the client treats it as trusted. Unsigned metadata remains refused or display-only fixture data. MIT local core remains registration-free: local search, list, view, where, use, feedback, reindex, vector reindex, serve, and public self-update behavior do not require hosted registration.
