# O063-04 — Learning Loop Docs & Release UX Review (v0.6.3)

**Reviewer:** Claude Opus. **Reviewed on main `b952aa2`:** `docs/learning-loop.md`,
`docs/releases/v0.6.3-alpha.md`, `docs/learning-loop-feedback-contract.md`.
**Question:** can a normal user understand why the Learning Loop matters, run it,
inspect candidates, and dry-run safely?

## Verdict: PASS_WITH_FIXES (fixes are minor, non-blocking)

The docs are clear, copy-pasteable, honest about scope, and explicitly do not
imply auto-improvement or remote sync. Two small UX nits below would improve the
first-run experience; neither blocks release.

## What passes

- **5-minute journey:** `docs/learning-loop.md` numbers the flow (record → doctor
  → candidates → dry-run → human-reviewed evidence). Clear.
- **Copy-pasteable:** concrete command blocks in both docs.
- **Value explicit:** "Wrong, missed, and rejected skill signals become reviewable
  candidates instead of dead-end logs."
- **No over-claim:** "`apply-candidate` is dry-run only", "does not claim automatic
  skill improvement", "no automatic skill edits" — consistent with O063-05
  (CLAIM_BLOCKED for "improves") and O063-01.
- **Rollback / no-write reassurance:** "prints `written=false`, `mutated_files=[]`".
- **Local-only:** `.learning` reads only; no telemetry / hosted / training.

## Minor fixes (recommended, non-blocking)

1. **`--query` example may mislead.** `docs/learning-loop.md` shows
   `feedback record python-patterns --verdict wrong --query "private task text"`.
   A naive reader may think the query is stored verbatim. Add an inline note: the
   `--query` value is reduced to a `query_summary_hash` at rest and never stored
   raw (`event_safe_payload`, `search_core.py`). This turns a possible privacy
   worry into a privacy *proof point*.
2. **Show an empty-state example.** The first-run output of `learning doctor`
   ("No learning feedback found yet.") and `improvement-candidates` ("no
   candidates yet") is helpful but not shown. A short empty-state snippet would
   make the very first run obviously non-scary.

## Release-notes alignment

`docs/releases/v0.6.3-alpha.md` correctly frames value as *inspect / review /
preview* and keeps the gate ("Do not tag or publish from this document alone";
owner approval + Trusted Publishing). This matches Hermes' held-claim decision and
O063-05: release notes may say "now lets users inspect/review/preview", not
"actually improves skills".

## Recommendation

**PASS_WITH_FIXES.** Ship the docs as-is for the alpha; apply the two minor UX
notes when convenient. No code changes were made in this review.
