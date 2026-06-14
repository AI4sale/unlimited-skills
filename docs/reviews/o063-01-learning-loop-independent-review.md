# O063-01 - Independent Learning Loop Code Review (v0.6.3)

**Reviewer:** Claude Opus (independent lane, worktree `usk-o063-review`, base
`db5739c`).
**Roadmap item:** `v0.6.3-alpha` - Learning Loop product value.
**Method:** independent read of the runtime code paths below. Codex's parallel
map (`#172`, `v0.6.3-learning-loop-implementation-map.md`) exists; this memo was
written from source first and not copied from it.

## Status note after #173

This review was originally written before C063-02 / #173 merged. The shipped
public feedback literal is now `wrong`; earlier `wrong-skill` wording is treated
as a historical/conceptual roadmap label only. #173 added the Free-core
inspection, candidate listing, learning doctor, and dry-run preview surfaces.
#175 remains the closed-loop regression proof gate.

## Verdict: PARTIALLY IMPLEMENTED

The **capture + aggregate + privacy** half of the loop is real, tested, and
privacy-safe. After #173, the Free-core inspect / review / dry-run preview path
exists. The release still must not claim that the loop actually improves or
mutates skills until the closed-loop proof in #175 is merged and O063-03R passes.

## Stage-by-stage map

| Loop stage | State | Evidence (file:symbol) |
| --- | --- | --- |
| Local usage signal | **Implemented** | `search_core.py:log_event` -> `.learning/events.jsonl`; `record_router_call` -> `.learning/router-metrics.json`; events `suggest`/`view`/`skill_used`/`quickstart` (`commands/library.py:200-233`) |
| Session correlation | **Implemented** | `search_core.py:session_correlation_id` / `hash_session_id` / `_local_salt`; salted, machine-local, raw id never written |
| Explicit feedback | **Implemented after #173** | public verdicts include `missed`, `wrong`, and `rejected`; feedback rows stay sanitized |
| Missed / wrong report | **Implemented after #173** | shipped public literal is `wrong` |
| Aggregation / metrics | **Implemented** | `compute_event_metrics` (`commands/library.py:262-368`): funnel rates, tier/score/margin buckets, session-attributed suggest->view->use; surfaced by `learning-summary --events` |
| Candidate builder | **Implemented after #173** | local privacy-safe candidates use opaque `skill_label` |
| Dry-run preview | **Implemented after #173** | dry-run preview is non-mutating |
| Release gate proves improvement | **Partial** | #175 must prove the closed loop before any "actually improves skills" claim |
| Closed-loop proof | **Pending #175** | US-063-004 wants one traced example (signal->diagnosis->change->verification) |
| Feedback report (paste-safe) | **Implemented** | `feedback.py:build_feedback_report` + `assert_feedback_report_safe` |

## Commands referenced by the tier stories - verification status

| Command | Status | Note |
| --- | --- | --- |
| `unlimited-skills feedback record --verdict missed` | **Exists after #173** | local, sanitized |
| `unlimited-skills feedback record --verdict wrong` | **Exists after #173** | public shipped literal is `wrong` |
| `unlimited-skills learning-summary [--events]` | **Exists** | `cmd_learning_summary` |
| `unlimited-skills feedback prepare` | **Exists** | `feedback.py:build_feedback_report` |
| `unlimited-skills learning doctor` | **Exists after #173** | diagnostics only |
| `unlimited-skills improvement-candidates` | **Exists after #173** | emits privacy-safe candidates |
| `unlimited-skills apply-candidate --dry-run <id>` | **Exists after #173** | non-mutating preview |

## Product gaps vs tech debt

**Product gaps (block the honest improvement claim):**
1. **Closed-loop proof pending** - #175 must prove feedback -> privacy-safe
   candidate -> candidate listing -> dry-run preview without mutation.
2. **No skill-mutating apply path** - v0.6.3 can claim inspect/review/preview, not
   automatic skill improvement.

**Tech debt (do not block v0.6.3):**
- No single `success-report` command (manual via `learning-summary --events` +
  ROI receipt is an acceptable fallback).
- No improvement-ledger automation (PR body / changelog evidence suffices
  short-term).
- `feedback` verdict not joined to an exact run beyond the session-correlation
  token.

## Release blockers vs non-blockers

- **BLOCKER for the improvement claim:** #175 closed-loop proof and O063-03R PASS.
  Until both exist, release notes must not say the loop "actually improves
  skills"; they may say users can inspect diagnostics, review privacy-safe
  candidates, and preview changes with a non-mutating dry-run.
- **NON-BLOCKER:** success-report command, ledger automation, gate improvement
  row.

## Recommendation

v0.6.3 can proceed with the honest inspect / review / dry-run preview framing
after #174/#175 and the Opus review gates land. Keep the stronger "actually
improves skills" claim blocked until a non-dry-run improvement path exists and is
tested. No code changes were made in this review (per non-goals).

## Reproduce

```text
git worktree add ../usk-o063-review main
grep -n "verdict" unlimited_skills/cli.py
sed -n '236,248p;262,368p' unlimited_skills/commands/library.py
sed -n '405,484p;582,684p' unlimited_skills/search_core.py
cat docs/adoption/learning-loop-gap-map.md
```
