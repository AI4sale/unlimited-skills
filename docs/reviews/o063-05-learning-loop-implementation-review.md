# O063-05 — Independent Implementation Review after C063-02 (v0.6.3)

**Reviewer:** Claude Opus (independent lane). **Code reviewed:** merged main
`7b7ea27` (C063-02 PR #173 + hardening `21fed14`). Verified code, not docs.
**Question:** does the implemented Learning Loop support the v0.6.3 user claim?

## Claim classification

| Candidate release claim | Verdict | Evidence on main |
| --- | --- | --- |
| "inspect local Learning Loop diagnostics" (`learning doctor`) | **CLAIM_ALLOWED** | `learning_loop.py:learning_doctor` emits counts/flags/candidate ids only; `cli.py:574` |
| "review privacy-safe improvement candidates from wrong/missed/rejected feedback" | **CLAIM_ALLOWED** | `build_improvement_candidates` groups `ACTIONABLE_OUTCOMES={rejected,missed,wrong}`; hashed `skill_label`; `assert_privacy_safe` gate |
| "preview changes with a non-mutating dry-run" | **CLAIM_ALLOWED** | `dry_run_candidate` returns `written:false, mutated_files:[]`; test `test_v063_apply_candidate_dry_run_is_non_mutating` |
| "users can run `learning doctor` / `improvement-candidates` / `apply-candidate --dry-run`" | **CLAIM_ALLOWED** | commands present `cli.py:572-584` |
| "v0.6.3 records missed and wrong-skill feedback" | **CLAIM_ALLOWED_WITH_LIMITS** | verdict literal shipped is **`wrong`** (not `wrong-skill`); `cli.py:546` |
| **"Learning Loop actually improves skills"** | **CLAIM_BLOCKED** | no skill-mutating apply path exists (apply-candidate is dry-run-only); candidates are diagnostics+previews; closed-loop proof is C063-03A (#175, not merged) |
| "wrong/missed/rejected feedback now produces improvement candidates" | **CLAIM_ALLOWED** | implemented + tested (`test_v063_wrong_missed_rejected_feedback_becomes_private_candidates`) |

## May release notes say "actually improves skills"?

**No — CLAIM_BLOCKED.** The shipped loop *surfaces and previews* improvement
candidates; it never changes a skill (no apply path) and there is no merged
closed-loop proof yet (#175 open). Hermes' approved framing now upgrades from
"will let users inspect… preview" to **"now lets users inspect diagnostics,
review privacy-safe improvement candidates, and preview changes with a
non-mutating dry-run"** — but **not** "improves skills" until an apply path +
closed-loop proof land and O063-03R returns PASS.

## Implementation quality notes

- Privacy is strong and **was hardened after the preliminary review** (commit
  `21fed14`): candidates carry a hashed `skill_label` (raw skill name never
  emitted), `candidate_id` validated against `llc_[a-f0-9]{12}`, `assert_privacy_safe`
  fail-closed on `FORBIDDEN_TEXT_RE`.
- No auto-apply / auto-publish exists — `apply-candidate` non-dry-run path mutates
  nothing and says so.
- Confidence is `low` for a single signal, `medium` otherwise — conservative.

## Recommendation

Proceed to enable the **inspect / review / preview** claims in v0.6.3 release
notes (CLAIM_ALLOWED). Keep "actually improves skills" **blocked**. Reconcile the
`wrong` vs `wrong-skill` literal across roadmap US-063-003 and the #174 tier docs
(O063-06). O063-03R remains the release-blocking privacy gate, finalized once
C063-03A (#175) merges. No code changes made here.
