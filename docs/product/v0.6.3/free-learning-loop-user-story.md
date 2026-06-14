# v0.6.3 Free / Community Core — Learning Loop User Story (O063-02A)

**Tier:** Free / community-core (MIT, local, offline-first, registration-free).
**Roadmap ref:** `docs/roadmaps/unlimited-skills/UNLIMITED-SKILLS-PRIVATE-ROADMAP-v0.6.3-to-v0.6.13.md#v0.6.3`
**Status of referenced commands:** some commands below are **proposed for Codex
C063-02 and not yet in the codebase** — every such command is marked
`[needs code verification]`. Verified-present commands are marked `[present]`.

## 1. Free-tier persona

"Sam", a solo engineer or indie agent builder. Runs Unlimited Skills locally,
never registered, no account, often offline. Has a local skill library and the
local router. Cares about: better skill retrieval, zero data leaving the machine,
and never having skills silently rewritten.

## 2. Jobs-to-be-done

- "When the router misses or picks the wrong skill, I want to record that so my
  local setup gets better over time."
- "I want to see what improvement the tool would propose, **before** anything
  touches my skills."
- "I want to confirm nothing is uploaded and nothing auto-changes."

## 3. Before / after workflow

**Before v0.6.3:** Sam can record `accepted/rejected/neutral` feedback
(`feedback record` `[present]`) and read aggregate counts
(`learning-summary --events` `[present]`), but there is no way to express a
*missed* or *wrong* skill, and no way to turn a signal into a previewable
improvement. The loop captures; it does not yet improve.

**After v0.6.3 (target):** Sam can record missed/wrong-skill feedback, list
local improvement **candidates**, run a learning **doctor** to see loop health,
and preview a **dry-run** patch for a candidate — all local, all non-mutating.

## 4. Exact CLI journey

```
# 1. Record what happened (verdict taxonomy shipped in C063-02; literal is `wrong`)
unlimited-skills feedback record --name <skill> --verdict missed        # [present, main 7b7ea27]
unlimited-skills feedback record --name <skill> --verdict wrong         # [present, main 7b7ea27]
unlimited-skills feedback record --name <skill> --verdict rejected      # [present]

# 2. Check loop health
unlimited-skills learning doctor                                        # [present, main 7b7ea27]

# 3. See what could improve (local candidates only; skills shown as hashed skill_label)
unlimited-skills improvement-candidates                                 # [present, main 7b7ea27]

# 4. Preview a fix WITHOUT mutating anything (dry-run only; no apply path exists)
unlimited-skills apply-candidate --dry-run <candidate-id>               # [present, main 7b7ea27]
```

Today's verified fallback journey (works on current code):
`feedback record --verdict rejected` -> `learning-summary --events` ->
`feedback prepare` (paste-safe report).

## 5. Expected empty-state behavior

- `learning doctor` with no feedback: reports "no local feedback yet", explains
  how to record the first signal, exits 0. Never errors on an empty library.
- `improvement-candidates` with no qualifying signal: prints "no candidates yet"
  plus the minimum signal needed (e.g. N missed/wrong records for one skill).

## 6. Expected normal-state behavior

- `improvement-candidates` lists candidate id, affected skill, signal summary
  (counts/buckets, never raw text), confidence, and proposed action class
  (ranking hint / doc fix / draft skill). Read-only.
- `apply-candidate --dry-run` prints a unified-diff-style preview and an explicit
  "no files were changed" footer.

## 7. Dry-run safety explanation

Dry-run is **non-mutating by contract**: it computes the proposed change and
renders it, but writes nothing to the skill library, the index, or config. There
is no implicit apply. A real apply (if it exists at all in Free) must be a
separate, explicit, human-invoked command — never a side effect of preview.

## 8. Privacy boundaries

- No network calls, no telemetry, no upload — ever, in Free.
- Feedback and candidates store **counts, buckets, verdicts, and skill names**,
  never raw prompts, task text, queries, secrets, tokens, or absolute paths
  (enforced today by `event_safe_payload`, `search_core.py`).
- Candidate previews must not embed raw query/prompt text — only redacted
  summaries.

## 9. What counts as user value (Free)

Sam turns scattered "that was wrong" moments into a concrete, reviewable list of
local improvements and can preview each safely — saving the time of manually
re-tuning or re-authoring skills, with zero registration and zero data exposure.

## 10. Explicitly NOT included in Free v0.6.3

- No hosted catalog, no remote learning, no team sync, no dashboard.
- No telemetry, no auto-upload, no account.
- No auto-apply and no auto-publish of candidates.
- No billing or entitlement gating.

---

### Evidence summary (for the task)

- **File:** `docs/product/v0.6.3/free-learning-loop-user-story.md`
- **CLI journey:** record missed/wrong feedback -> `learning doctor` ->
  `improvement-candidates` -> `apply-candidate --dry-run` (candidate preview),
  with a verified fallback on today's commands.
- **Privacy promises:** local-only, no telemetry/upload, no raw prompts/paths/
  tokens/secrets, redacted candidate summaries, dry-run non-mutating.
- **Non-goals:** no hosted sync, no telemetry, no auto-rewrite, no auto-publish,
  no paid claims, no implementation (Codex owns code).
- **Candidate-preview vs auto-apply:** preview is read-only and explicit; apply is
  a separate human action, never a side effect.
