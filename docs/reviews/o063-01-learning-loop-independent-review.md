# O063-01 — Independent Learning Loop Code Review (v0.6.3)

**Reviewer:** Claude Opus (independent lane, worktree `usk-o063-review`, base `db5739c`).
**Roadmap item:** `v0.6.3-alpha` — *Learning Loop Actually Improves Skills* (US-063-001..005).
**Method:** independent read of the runtime code paths below. Codex's parallel
map (`#172`, `v0.6.3-learning-loop-implementation-map.md`) exists; this memo was
written from source first and not copied from it.

## Verdict: PARTIALLY IMPLEMENTED

The **capture + aggregate + privacy** half of the loop is real, tested, and
privacy-safe. The **improvement** half — the part the v0.6.3 VFP actually
promises ("*actually improves skills*") — is **specified but not built**: there
is no missed/wrong-skill signal, no feedback->eval-candidate builder, and no
traced closed-loop proof. v0.6.3 can proceed to *implementation* of those gaps,
but it **cannot honestly claim the headline VFP** until they land.

## Stage-by-stage map

| Loop stage | State | Evidence (file:symbol) |
| --- | --- | --- |
| Local usage signal | **Implemented** | `search_core.py:log_event` -> `.learning/events.jsonl`; `record_router_call` -> `.learning/router-metrics.json`; events `suggest`/`view`/`skill_used`/`quickstart` (`commands/library.py:200-233`) |
| Session correlation | **Implemented** | `search_core.py:session_correlation_id` / `hash_session_id` / `_local_salt` — salted, machine-local, raw id never written |
| Explicit feedback | **Partial** | `commands/library.py:cmd_feedback` (236-248) writes `.learning/feedback.jsonl`; verdicts limited to `accepted/rejected/neutral` (`cli.py:545`) |
| Missed / wrong-skill report | **Missing** | No `missed` / `wrong-skill` verdict; US-063-003 requires `suggested, viewed, used, accepted, rejected, missed, wrong-skill` |
| Aggregation / metrics | **Implemented** | `compute_event_metrics` (`commands/library.py:262-368`): funnel rates, tier/score/margin buckets, session-attributed suggest->view->use; surfaced by `learning-summary --events` |
| Eval candidate builder | **Missing** | No command converts an accepted/rejected/missed row into an eval-fixture draft (gap-map row "Eval candidate") |
| Fix -> improvement ledger | **Missing** | No artifact links a feedback item -> fix commit -> verification (gap-map row "Fix implementation") |
| Release gate proves improvement | **Partial** | Frozen-effectiveness eval + v0.6 frozen-contract harness exist, but the gate emits no per-feedback before/after improvement row |
| Closed-loop proof | **Missing** | US-063-004 wants one traced example (signal->diagnosis->change->verification); none exists |
| Feedback report (paste-safe) | **Implemented** | `feedback.py:build_feedback_report` + `assert_feedback_report_safe` |

## Commands referenced by the tier stories — verification status

The v0.6.3 tier user-stories (O063-02A..E) reference these CLI commands. Marking
their implementation status from code inspection (per task review requirement):

| Command | Status | Note |
| --- | --- | --- |
| `unlimited-skills feedback record --verdict ...` | **Exists** | `cli.py:545`, only `accepted/rejected/neutral` |
| `unlimited-skills learning-summary [--events]` | **Exists** | `cli.py:562-569`, `cmd_learning_summary` |
| `unlimited-skills feedback prepare` | **Exists** | `feedback.py:build_feedback_report` |
| `unlimited-skills learning doctor` | **Does NOT exist** | needs code verification / Codex C063-02 |
| `unlimited-skills improvement-candidates` | **Does NOT exist** | needs code verification / Codex C063-02 |
| `unlimited-skills apply-candidate --dry-run <id>` | **Does NOT exist** | needs code verification / Codex C063-02 |

## Product gaps vs tech debt

**Product gaps (block the honest VFP claim):**
1. **No missed/wrong-skill signal** — the loop only learns from skills that *were*
   suggested, never from the ones that *should* have been. Highest-leverage gap
   for "improves skills." (US-063-003)
2. **No feedback->eval-candidate path** — no mechanism turns a real signal into a
   reviewable improvement. (US-063-004 / gap-map "Eval candidate")
3. **No closed-loop proof** — the release cannot demonstrate one improvement
   end-to-end. (US-063-004)

**Tech debt (do not block v0.6.3):**
- No single `success-report` command (manual via `learning-summary --events` +
  ROI receipt is an acceptable fallback).
- No improvement-ledger automation (PR body / changelog evidence suffices short-term).
- `feedback` verdict not joined to an exact run beyond the session-correlation token.

## Release blockers vs non-blockers

- **BLOCKER (for the VFP claim, not for code work):** US-063-003 expanded verdict
  taxonomy (missed/wrong-skill) **and** US-063-004 one closed-loop proof. Until
  both exist, release notes must NOT say the loop "actually improves skills" — at
  most "the learning loop captures signal and is measurable."
- **NON-BLOCKER:** success-report command, ledger automation, gate improvement row.

## Recommendation

v0.6.3 **can proceed** once Codex's C063-02 (verdict taxonomy + local feedback
signal contract incl. the three not-yet-existing commands above, US-063-003) and
C063-03 (closed-loop proof fixture, US-063-004) land and pass O063-03's privacy
review. US-063-005 should record the honest state: **measurable, not yet
self-improving**, with the missed/wrong-skill signal and the candidate builder as
the named next deltas. No code changes were made in this review (per non-goals).

## Reproduce

```
git worktree add ../usk-o063-review main
grep -n "verdict" unlimited_skills/cli.py                 # 545: accepted|rejected|neutral
sed -n '236,248p;262,368p' unlimited_skills/commands/library.py
sed -n '405,484p;582,684p' unlimited_skills/search_core.py
cat docs/adoption/learning-loop-gap-map.md
```
