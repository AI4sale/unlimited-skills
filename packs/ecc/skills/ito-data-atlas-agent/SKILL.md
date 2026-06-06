---
name: ito-data-atlas-agent
description: "Design background Data Atlas style agents for Itô basket research, market discovery, parameter drafting, and human-in-the-loop editing. Use for architecture and workflow planning, not live order execution."
version: 1.0.0
category: ecc
tags: "[ito-data-atlas-agent, design, background, data, atlas, style, agents, basket]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\ito-data-atlas-agent\SKILL.md
source_sha256: 966251df53ecf7ca74b07373e44860ecab7a6def4a75e2d141341e13d92ad6e8
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:57Z"
---

## When to Use

Design background Data Atlas style agents for Itô basket research, market discovery, parameter drafting, and human-in-the-loop editing. Use for architecture and workflow planning, not live order execution.

## When Not to Use

Not specified by the source skill.

## Required Context

Not specified by the source skill.

## Procedure

1. Define the user objective and excluded actions.
2. List data sources and access requirements.
3. Draft a basket spec with provenance for every underlier.
4. Produce editable parameters rather than executable orders.
5. Store an audit trail: inputs, model output, sources, and human decision.

## Tools

Not specified by the source skill.

## Expected Output

Not specified by the source skill.

## Known Traps

Not specified by the source skill.

## Examples of Successful Execution

Not specified by the source skill.

## Regression Tests

Not specified by the source skill.

## Original Skill Body

## Itô Data Atlas Agent

Use this skill to design an agent that watches data sources, builds candidate
prediction-market baskets, drafts parameter changes, and hands the result to a
human for review.

This skill describes architecture and workflow. It does not run live trading.

## Guardrails

- Keep all execution behind explicit human approval.
- Require `ITO_API_KEY` only for read-only Itô data access unless a separate
  private implementation explicitly adds execution controls.
- Do not persist private user data unless the target repo already has a storage
  contract and the user asks for it.
- Do not expose private strategy logic, venue credentials, or local paths in
  public docs.

## Architecture Pattern

Use four lanes:

1. Research collector: public web, X, GitHub, venue docs, API metadata, and
   Itô read endpoints when gated access exists.
2. Basket drafter: turns sources into candidate underliers, weights, rules, and
   questions.
3. Risk reviewer: checks data freshness, venue limits, resolution ambiguity,
   compliance notes, and prompt-injection exposure.
4. Human editor: opens a chat or UI state where the user can approve, reject,
   adjust, or ask for more research.

## Useful Skill Chains

- `deep-research` for source collection.
- `x-api` for current social/event signal.
- `ito-market-intelligence` for venue and underlier context.
- `ito-basket-compare` for user knowledge-base matching.
- `prediction-market-risk-review` before any execution-capable integration.

## Output Contract

Return an implementation-ready workflow spec with:

- data sources
- access gates
- agent roles
- human approval points
- storage/audit boundary
- non-goals
