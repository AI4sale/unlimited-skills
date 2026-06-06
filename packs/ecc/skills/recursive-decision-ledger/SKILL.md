---
name: recursive-decision-ledger
description: "Use when the user asks for repeated rollouts, marked decision processes, high-dimensional search, stochastic optimization, local-optima exploration, ensemble comparison, or recursive reasoning with a visible evidence trail."
version: 1.0.0
category: ecc
tags: "[recursive-decision-ledger, user, asks, repeated, rollouts, marked, decision, processes]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\recursive-decision-ledger\SKILL.md
source_sha256: 33fa679cf4999f123521dc82ec2bb3689b0a7b65519ada0ecc0450c5faa456af
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:59Z"
---

## When to Use

Use when the user asks for repeated rollouts, marked decision processes, high-dimensional search, stochastic optimization, local-optima exploration, ensemble comparison, or recursive reasoning with a visible evidence trail.

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

## Recursive Decision Ledger

Use this skill when the user is trying to force deeper computation through
repeated rollouts or "Prime Gauss" style recursive prompting. Preserve the useful
part: repeated trials, prior memory, fresh information, and explicit marks.
Remove the unsafe part: pretending the loop proves certainty.

## Ledger Contract

Every rollout should record:

- rollout id and timestamp;
- prior accepted winner and prior watchlist;
- fresh information ingested;
- search space size;
- model families or heuristics used;
- trial count and effective trial count;
- top candidates;
- decision marks;
- coherence marks against the prior ledger;
- promotion gate result.

Prefer JSONL for append-only ledgers and Markdown for human summaries.

## Rollout Loop

1. Load the prior ledger.
2. Capture new information at time-step zero.
3. Run the bounded search.
4. Mark each candidate: accept, watch, reject, decay watch, or needs replay.
5. Compare winners against prior winners and latest marked rollout.
6. Downgrade candidates when drift, tail risk, stale data, or failed replay
   invalidates the previous mark.
7. Append artifacts before summarizing.

## Coherence Mark

Include a compact coherence mark:

```text
Ensemble matches prior winner: true
Recursive matches prior winner: false
Latest rollout match: true
Live promotion allowed: false
Reason: replay and freshness gates not satisfied
```

## Promotion Rules

For trading, capital allocation, production deploys, migrations, or destructive
ops, recursive confidence is not approval.

Default to paper, dry-run, read-only, preview, or staged mode unless the user
explicitly approves the live action and the repo/service gate supports it.

Promote only when:

- the candidate beats the prior accepted winner on the chosen metric;
- correctness and replay checks pass;
- risk limits are explicit;
- the evidence is durable;
- the user has approved the live step when needed.

## Summary Shape

Lead with the decision, not the drama:

```text
Rollout 15 complete. The prior winner still holds, but edge deteriorated 17%.
Status: watch, not live. Next gate: 20 replay fills with fresh orderbook age
below threshold.
```
