# Policy-Aware Recommendations

Policy-aware recommendations are a v0.4 preview contract for deciding whether a catalog item may be shown, installed, updated, warned, or refused. The public v0.3.9-alpha follow-up only defines a fixture-backed decision table and refusal-code vocabulary. It does not implement a live recommendation engine.

## Non-Goals

This contract does not:

- install, update, remove, rewrite, or reindex skills automatically;
- send telemetry automatically;
- forward hosted queries by default;
- distribute the full catalog;
- include skill bodies, prompts, task text, local paths, repo paths, customer data, tokens, proofs, or private keys;
- publish private team-pack content in the public repository.

## Outcomes

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

The table is intentionally deterministic. It is a contract fixture for tests and future client/server integration, not a ranking algorithm and not an install plan.
