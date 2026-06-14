# O063-06 — Tier Matrix ↔ Implementation Consistency Review (v0.6.3)

**Reviewer:** Claude Opus. **Inputs:** PR #174 tier docs vs merged main `7b7ea27`
(C063-02). **Goal:** prove tier-matrix claims are bounded by the actual v0.6.3
implementation — no fake hosted/paid functionality.

## Per-claim classification

| Tier | Claim in #174 | Status | Action |
| --- | --- | --- | --- |
| Free | `improvement-candidates`, `apply-candidate --dry-run`, `learning doctor` | **implemented** | drop `[needs code verification]` markers post-#174-merge |
| Free | verdict `missed` / `wrong-skill` | **must reconcile** | shipped literal is **`wrong`**; change `wrong-skill` → `wrong` in CLI-journey docs |
| Free | candidate shows `affected_skill: python-reviewer` (plain) | **must reconcile** | impl emits hashed `skill_label` (`skill-<sha256>`); update examples |
| Free | "turn feedback into reviewable local improvements" | **implemented** (review/preview) | OK; must NOT imply auto-improvement |
| Registered | "registered-ready candidate report" artifact | **docs-only future-compatible** | not in code; keep marked future; no submit verb |
| Team | "team review packet" + manual approval flow | **docs-only future-compatible** | not in code; keep future-compatible |
| Business | "Business Learning Backlog Export" | **docs-only future-compatible** | not in code; keep future; "future dashboard could import" |
| Enterprise | "Evidence Pack" + "No-Auto-Apply Governance Contract" | **docs-only future-compatible** + **partly implemented invariant** | the no-auto-apply guarantee IS true in code (apply is dry-run-only); the export artifact is future |
| All | "no telemetry / no upload / no auto-apply / dry-run non-mutating" | **implemented** | verified in `learning_loop.py` (`_privacy_flags`, `assert_privacy_safe`, dry-run) |
| All | "SHA256, not signed" | **consistent** | no signing in C063-02; keep `signature: not-claimed` |

## Must-remove-from-release-notes (until built)

- Any present-tense per-tier hosted artifact (registered submit / team dashboard /
  business dashboard / enterprise hosted audit log).
- "actually improves skills" (O063-05: CLAIM_BLOCKED).
- Plain skill names in candidate output examples (impl hashes them).

## Required #174 doc fixes (remediation)

1. `wrong-skill` → `wrong` in CLI-journey literals (Free story; tier matrix noted).
2. Candidate examples: `affected_skill: <name>` → hashed `skill_label`.
3. Drop `[needs code verification]` on the three commands once #174 merges (they
   are now on main).

The Free-core bonus is **fully implemented and consistent** once (1)-(2) are
applied. The four paid-tier bonuses are **bounded, docs-only, future-compatible**
— none fakes a live hosted/paid system. No code changes made here.
