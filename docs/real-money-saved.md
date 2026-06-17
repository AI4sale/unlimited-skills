# Real Money Saved (v0.6.4.post1)

Real Money Saved replaces the v0.6.4 proxy "Money Saved Meter" (which kept dollars
disabled and estimated tokens from bytes) with a model-bound, cache-aware,
event-counted measurement denominated in **API-equivalent dollars**.

> **Claim boundary.** The figure is an *API-equivalent estimate* — what the same
> context would cost at published API prices. It is **not** a provider-invoice
> reconciliation and **not** a guaranteed bill reduction. It applies even on a
> subscription, because a subscription still consumes usage limits / context
> budget. The forbidden claim is "your bill was reduced by $X."

## Value model

```
estimated_money_saved_usd = total_tokens_saved / 1_000_000 * price_per_1m_input_tokens
total_tokens_saved        = skills_tokens_saved + mcp_tokens_saved   (kept separate, then summed)
```

- **Skills** — baseline = the Level-1 (name + description) descriptor of *every*
  visible skill; progressive disclosure collapses that to one router descriptor.
  `skills_tokens_saved = all_skill_level1_descriptor_tokens - router_descriptor_tokens`.
- **MCP** — baseline = the full upstream `tools/list` of all configured servers;
  the gateway collapses that to 3 meta-tools.
  `mcp_tokens_saved = upstream_tools_list_tokens - gateway_tools_list_tokens`.

Both halves are counted with the **same** token counter so the subtraction is
apples-to-apples.

## Token counting

- **Primary (Claude):** Anthropic `count_tokens` — exact for the bound model.
- **Fallback:** `bytes_divided_by_4` — flagged `release_acceptable: false`. It
  systematically *undercounts* Claude context (Opus 4.7+ can emit ~35% more
  tokens than the byte heuristic), so it **cannot** close the release for a
  Claude model.
- **Privacy:** exact counting sends only Level-1 descriptors / tool schemas to the
  provider — never raw prompts or skill bodies. Disclosed in every report's
  `token_count_privacy`.

## Model binding

Per-event, never global. Cascade: explicit `--model` → runtime self-report →
env metadata → the agent's documented assumption profile → unknown. For a
*supported* agent, "no binding" is an integration bug (diagnostic, exit 2), not a
money dead-end. If the runtime hides the model, the agent's baseline profile is
used and the row is marked `assumed`.

## Events and cache

Standing context re-enters the cache on `session_start`, `compaction`,
`context_rebuild`, `agent_restart`, and a manual reindex-reload. Each is an event.
Default cache price class is `cache_write_5m` (standing-context re-write); the
first session with no warm cache uses `base_input`.

Storage is **compact, not an infinite log**: a rolling `summary.json` bucketed by
the 8-field money-basis tuple (`provider, model, model_source, currency,
price_class, price_source_date, token_counter_method, money_model_version`) plus a
`recent-events.jsonl` tail capped at 200 lines. The basis key is also the
Team/Business "sum only when the basis matches" rule.

## Commands

```
unlimited-skills money-saved model-detect [--model provider:model] --json
unlimited-skills money-saved prices list --json
unlimited-skills money-saved prices show --model anthropic:claude-opus-4.8 --json
unlimited-skills money-saved meter --model anthropic:claude-opus-4.8 \
    --include-skills --include-mcp --token-counter anthropic --json
unlimited-skills money-saved registered-export --model … --alias NAME --out reg.json
unlimited-skills money-saved team-rollup --input reg1.json --input reg2.json --out team.json
unlimited-skills money-saved admin-export --input team.json --csv admin.csv --json admin.json
unlimited-skills money-saved evidence-pack --input admin.json --out evidence/
unlimited-skills money-saved verify-evidence-pack --input evidence/   # exit 0 valid / 1 tampered / 2 bad input
unlimited-skills money-saved events inspect --json
```

The tier commands auto-route to v2 when the input carries a v2 schema; legacy
v0.6.4 proxy reports are rejected as money-tier input.

## Tier ladder

- **Registered** — wraps a meter report; money non-null, skills/MCP separate,
  full basis travels with it; no raw prompts/bodies/paths, no install/machine/
  account id; produced locally and stays local.
- **Team** — sums money only within a single compatible basis; incompatible bases
  are reported as separate groups, never falsely summed; duplicates de-duped;
  `contains_assumptions` surfaced.
- **Business** — flat per-member CSV/JSON with money columns and
  `money_basis_compatible`.
- **Enterprise** — a 13-file evidence pack and a verifier that recomputes the
  money from first principles (re-resolving each price from the live DB) and
  fails (exit 1) on any tamper.

## Release gate

`scripts/verify-v064post1-real-money-saved-smoke.py` runs 11 checks across BOTH
the exact-model path and the hidden-runtime assumption path: model-detect, prices,
Free meter (skills + MCP + non-null money), Registered basis, Team aggregate,
Business CSV money columns, Enterprise verify ok, tamper model/price/total →
ok=false, and legacy proxy rejected. The release fails if money is null, either
savings half is missing, the model binding / pricing source / token-counter
method / money formula is missing, the Business CSV lacks money columns, the
Enterprise verifier does not recompute, or any allowed claim asserts exact money,
bill reduction, or invoice reconciliation. For a Claude model the gate additionally
requires the Anthropic `count_tokens` path (the byte fallback is not
release-acceptable).
