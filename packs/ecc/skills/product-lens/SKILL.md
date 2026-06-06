---
name: product-lens
description: "Use this skill to validate the \"why\" before building, run product diagnostics, and pressure-test product direction before the request becomes an implementation contract."
version: 1.0.0
category: ecc
tags: "[product-lens, this, validate, why, before, building, run, product]"
status: published
confidence: 0.8
source: imported
source_pack: ecc
source_repo: "https://github.com/affaan-m/ECC"
source_path: skills\product-lens\SKILL.md
source_sha256: 8eaea4af3b14018b4c8ef180419556b9cab4a8b931133dfdaedc70c787b56165
unlimited_skills_adapter: odysseus-action-schema-v1
created: "2026-06-06T06:14:58Z"
---

## When to Use

- Before starting any feature — validate the "why"
- Weekly product review — are we building the right thing?
- When stuck choosing between features
- Before a launch — sanity check the user journey
- When converting a vague idea into a product brief before engineering planning starts

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

## Product Lens — Think Before You Build

This lane owns product diagnosis, not implementation-ready specification writing.

If the user needs a durable PRD-to-SRS or capability-contract artifact, hand off to `product-capability`.

## Mode 1: Product Diagnostic

Like YC office hours but automated. Asks the hard questions:

```
1. Who is this for? (specific person, not "developers")
2. What's the pain? (quantify: how often, how bad, what do they do today?)
3. Why now? (what changed that makes this possible/necessary?)
4. What's the 10-star version? (if money/time were unlimited)
5. What's the MVP? (smallest thing that proves the thesis)
6. What's the anti-goal? (what are you explicitly NOT building?)
7. How do you know it's working? (metric, not vibes)
```

Output: a `PRODUCT-BRIEF.md` with answers, risks, and a go/no-go recommendation.

If the result is "yes, build this," the next lane is `product-capability`, not more founder-theater.

## Mode 2: Founder Review

Reviews your current project through a founder lens:

```
1. Read README, CLAUDE.md, package.json, recent commits
2. Infer: what is this trying to be?
3. Score: product-market fit signals (0-10)
   - Usage growth trajectory
   - Retention indicators (repeat contributors, return users)
   - Revenue signals (pricing page, billing code, Stripe integration)
   - Competitive moat (what's hard to copy?)
4. Identify: the one thing that would 10x this
5. Flag: things you're building that don't matter
```

## Mode 3: User Journey Audit

Maps the actual user experience:

```
1. Clone/install the product as a new user
2. Document every friction point (confusing steps, errors, missing docs)
3. Time each step
4. Compare to competitor onboarding
5. Score: time-to-value (how long until the user gets their first win?)
6. Recommend: top 3 fixes for onboarding
```

## Mode 4: Feature Prioritization

When you have 10 ideas and need to pick 2:

```
1. List all candidate features
2. Score each on: impact (1-5) × confidence (1-5) ÷ effort (1-5)
3. Rank by ICE score
4. Apply constraints: runway, team size, dependencies
5. Output: prioritized roadmap with rationale
```

## Output

All modes output actionable docs, not essays. Every recommendation has a specific next step.

## Integration

Pair with:
- `/browser-qa` to verify the user journey audit findings
- `/design-system audit` for visual polish assessment
- `/canary-watch` for post-launch monitoring
- `product-capability` when the product brief needs to become an implementation-ready capability plan
