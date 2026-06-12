# Decision: frozen skill-effectiveness gate with a forced cadence

- **date:** 2026-06-12
- **status:** active; release-blocking

## Why

A one-time fix to the invocation funnel decays silently: library growth,
ranking tweaks, router edits, and hook changes can each re-kill it without
any test failing. The owner's standing directive — a standard test that
re-checks skill effectiveness at least every 10 releases — turns "is the
funnel alive" into a release-gated, measured property instead of a hope.

## Evidence

The funnel had already died once while the full test suite stayed green (see
`knowledge/product-state/skill-invocation-red-flag.md`). Nothing in CI
measured whether suggestions were correct, fast, private, or injected
precisely; the regression had no failing signal by construction.

## Changed state

Shipped in #116/#117 and tightened post-review:

- frozen eval set `evals/invocation-scenarios.json` (30 positive + 12
  negative scenarios; queries are never tuned to fix misses — ranking or the
  library is fixed instead);
- `scripts/check-skill-effectiveness.py` (CI) and
  `unlimited-skills skills check-effectiveness` (user), recording
  `evals/last-effectiveness-run.json`;
- `scripts/verify-skill-effectiveness-gate.py` with two profiles —
  A0 merge gate: top-1 >= 0.70, top-3 >= 0.85, FP <= 0.10, injection
  precision >= 0.90, negatives injected = 0 (hard), p90 <= 1500 ms,
  p95 <= 2500 ms, privacy invariants all true;
  v0.5 release gate: top-1 >= 0.80, top-3 >= 0.90, injection precision
  >= 0.95, p90 <= 1200 ms, p95 <= 2000 ms;
- cadence gate: a recorded run is REQUIRED at least every 10 releases
  (`--cadence-check` fails closed), on every public/adoption release gate,
  after any search/ranking/router/hook/indexing change, and before any
  PyPI/marketplace publication.

## Next rule

top-3 below 0.90 after A0 is a release blocker. top-1 below 0.80 is a warning
on dev PRs and a blocker for public releases. Threshold changes require a
review verdict recorded in this file's history — they are never adjusted
inside a feature PR to make it pass.
