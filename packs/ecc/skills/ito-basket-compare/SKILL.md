---
name: ito-basket-compare
description: "Compare Itô prediction-market baskets against a user's knowledge base, portfolio notes, financial context, watchlist, or research thesis. Use for read-only basket comparison and gap analysis without investment advice or live trading."
version: 1.0.0
category: ecc
tags: "[ito-basket-compare, compare, prediction-market, baskets, against, user, knowledge, base]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\ito-basket-compare\SKILL.md
source_sha256: 1fb122cfbb92e30f70bbac4fc9d6b41f049ffe2413bc6ae3f079a34090e13489
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:57Z"
---

## When to Use

Compare Itô prediction-market baskets against a user's knowledge base, portfolio notes, financial context, watchlist, or research thesis. Use for read-only basket comparison and gap analysis without investment advice or live trading.

## When Not to Use

Not specified by the source skill.

## Required Context

Not specified by the source skill.

## Procedure

1. Read the preserved source skill body below.
2. Apply only the parts relevant to the current task.
3. Verify the result using the regression tests or project-specific checks.

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

## Itô Basket Compare

Use this skill to compare a basket, theme, or market set against a user's
knowledge base, portfolio notes, research memo, CRM context, or stated thesis.

This skill is read-only. It does not recommend trades. It helps a user inspect
fit, exposure, assumptions, and missing context before they decide what to do.

## Guardrails

- Do not provide investment advice or tell the user to buy, sell, hold, hedge,
  lever, or size a trade.
- Do not execute, prepare, or submit orders.
- Do not use private documents unless the user explicitly points to them.
- Use `ITO_API_KEY` only for read-only Itô basket/market data after explicit
  user request.
- If comparing against financials, preserve privacy and summarize only the
  fields needed for the comparison.

## Basket vs Knowledge Base

1. Identify the basket theme and underliers.
2. Retrieve the user's relevant notes, docs, or memory snippets.
3. Map each underlier to claims, sources, uncertainties, and stale assumptions.
4. Return aligned signals, conflicting signals, and missing research.

## Basket vs Portfolio Notes

1. Parse the user's watchlist, holdings summary, or exposure notes.
2. Compare themes, geographies, time horizons, and event outcomes.
3. Flag concentration, correlation, and duplicated narrative exposure.
4. Avoid recommendations; phrase output as inspection and questions.

## Basket vs Financial Context

1. Accept only user-provided or explicitly selected financial context.
2. Identify liquidity, drawdown, time-horizon, and constraint mismatches.
3. Ask for missing constraints instead of guessing.

## Output Contract

Use this structure:

1. Basket summary
2. Comparison target
3. Matches
4. Conflicts or stale assumptions
5. Missing context
6. User-action checklist

End with:

```text
This comparison is informational and not investment or trading advice.
```
