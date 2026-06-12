# Product state: skill invocation red flag (A0)

- **date:** 2026-06-12
- **status:** resolved by A0 (PR #117); guarded by the frozen effectiveness gate

## Why

The product's core funnel — an agent actually searching, viewing, and using a
skill during real work — had silently died while engineering quality kept
improving. The library grew to 267+ bundled skills, search got faster, the MCP
gateway shipped, yet none of it mattered if models never invoked the router.

## Evidence

Measured on real usage logs and agent transcripts (diagnosis report,
`docs/adoption/a0-invocation-diagnosis.md`):

- the full search → view → use loop executed **0 times** after 2026-06-08;
- ~25% of ordinary sessions touched the library at all (mostly bare searches);
- **0 of 99** subagent transcripts used the library;
- 83% of recorded usage events came from a single dogfooding burst, not organic work.

Root causes: no deterministic trigger in production (plugin hook not enabled,
legacy installs had no hooks, a PATH gate broke the hook that did exist), a
generic un-costed router instruction, and an expensive probe (hybrid search at
~9.9 s per call).

## Changed state

A0 (PR #117) made invocation a property of infrastructure instead of model
discipline: the `suggest` deterministic probe (cold p90 well under 1.5 s), a
rewritten router block in every emitter, hook delivery with a resolver
fallback chain, and tiered ambient injection (silence / hint / high-confidence
skill card). Measured after: top-1 0.933, top-3 0.967, FP 0.000, injection
precision 1.000, negatives injected 0.

## Next rule

Any "is the product actually used" property must be encoded as a cheap,
frozen, periodically-forced eval with explicit thresholds and a cadence gate
(see `knowledge/decisions/frozen-skill-effectiveness-gate.md`). A funnel
without a recurring measured check is assumed dead until proven otherwise.
