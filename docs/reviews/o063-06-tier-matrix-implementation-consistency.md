# O063-06 - Tier Matrix / Implementation Consistency Review (v0.6.3)

**Reviewer:** Claude Opus. **Inputs:** PR #174 tier docs vs merged main
`7b7ea27` (C063-02). **Goal:** prove tier-matrix claims are bounded by the
actual v0.6.3 implementation - no fake hosted/paid functionality.

## Per-claim classification

| Tier | Claim in #174 | Status | Action |
| --- | --- | --- | --- |
| Free | `improvement-candidates`, `apply-candidate --dry-run`, `learning doctor` | **implemented** | Commands are on main after #173 |
| Free | verdict `missed` / `wrong` | **reconciled** | Shipped public literal is **`wrong`** |
| Free | candidate shows opaque `skill_label` | **reconciled** | Examples avoid plain skill names |
| Free | "turn feedback into reviewable local improvements" | **implemented** (review/preview) | OK; must NOT imply auto-improvement |
| Registered | "registered-ready candidate report" artifact | **docs-only future-compatible** | Not in code; keep marked future; no submit verb |
| Team | "team review packet" + manual approval flow | **docs-only future-compatible** | Not in code; keep future-compatible |
| Business | "Business Learning Backlog Export" | **docs-only future-compatible** | Not in code; keep future; "future dashboard could import" |
| Enterprise | "Evidence Pack" + "No-Auto-Apply Governance Contract" | **docs-only future-compatible** + **partly implemented invariant** | The no-auto-apply guarantee is true in code (apply is dry-run-only); the export artifact is future |
| All | "no telemetry / no upload / no auto-apply / dry-run non-mutating" | **implemented** | Verified in `learning_loop.py` (`_privacy_flags`, `assert_privacy_safe`, dry-run) |
| All | "SHA256, not signed" | **consistent** | No signing in C063-02; keep `signature: not-claimed` |

## Must-remove-from-release-notes (until built)

- Any present-tense per-tier hosted artifact (registered submit / team dashboard /
  business dashboard / enterprise hosted audit log).
- "actually improves skills" (O063-05: CLAIM_BLOCKED).
- Plain skill names in candidate output examples.

## Required #174 doc fixes (remediation)

1. `wrong-skill` -> `wrong` in CLI-journey literals.
2. Candidate examples use opaque `skill_label`, not raw skill-name fields.
3. Keep paid-tier artifacts docs-only / future-compatible unless code implements
   them.

The Free-core bonus is **fully implemented and consistent** after the #174 scrub.
The four paid-tier bonuses are **bounded, docs-only, future-compatible**; none
fakes a live hosted/paid system. No code changes made here.
