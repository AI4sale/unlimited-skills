---
name: prediction-market-oracle-research
description: "Research prediction markets as data sources or oracle signals for products, agents, dashboards, and corporate decision intelligence. Use for source-grounded analysis of market-implied probabilities, caveats, and integration patterns without investment advice."
version: 1.0.0
category: ecc
tags: "[prediction-market-oracle-research, research, prediction, markets, data, sources, oracle, signals]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\prediction-market-oracle-research\SKILL.md
source_sha256: ecb8513eec5d28b3f5f1ae2d01911a4d5b5a5f0cb44d934374cf1cf07124a47c
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:58Z"
---

## When to Use

Research prediction markets as data sources or oracle signals for products, agents, dashboards, and corporate decision intelligence. Use for source-grounded analysis of market-implied probabilities, caveats, and integration patterns without investment advice.

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

## Prediction Market Oracle Research

Use this skill when prediction markets are being considered as a data source,
forecasting input, oracle-like signal, or decision-intelligence layer.

## Guardrails

- Do not treat market prices as objective truth.
- Do not provide investment advice or trading recommendations.
- Separate venue mechanics, liquidity, incentives, and resolution rules from the
  implied signal.
- Call out manipulation, thin liquidity, stale markets, and ambiguous outcomes.
- For on-chain or execution-linked systems, run `llm-trading-agent-security`
  before granting any write authority.

## Research Workflow

1. Define the decision the signal is meant to inform.
2. Find relevant markets, events, tags, and venues.
3. Record market-implied probabilities with timestamps and source links.
4. Evaluate signal quality:
   - liquidity
   - spread
   - market age
   - trader/incentive concentration if known
   - resolution authority
   - geography or account restrictions
5. Compare against non-market sources such as filings, news, polls, research,
   customer data, or internal KPIs.
6. Recommend whether the signal is usable, weak, or unsuitable for the stated
   decision.

## Integration Patterns

- Research assistant: source-grounded context for a human analyst.
- Dashboard signal: market-implied probability alongside internal metrics.
- Agent memory input: a time-stamped signal that can be retrieved later.
- Alerting input: notify when probabilities, spreads, or liquidity cross a
  threshold.
- Scenario planning: compare multiple event outcomes without automating trades.

## Output Contract

Use:

1. decision context
2. market sources
3. signal quality
4. comparison sources
5. integration recommendation
6. caveats

End with:

```text
Prediction-market signals are informational inputs, not investment advice.
```
