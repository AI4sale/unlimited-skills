# O063-03 — Learning Loop Privacy & Security Review (v0.6.3)

**Reviewer:** Claude Opus (independent lane, base `db5739c`).
**Scope:** v0.6.3 Learning Loop candidate generation, dry-run output, local files,
logs, stdout, docs, and the per-tier artifacts (O063-02A..F). **Not** a broad
security audit outside v0.6.3.

## Verdict: PASS_WITH_FIXES

The **already-shipping** capture/aggregate/report surfaces are privacy-safe by
construction and fail-closed (details below) — **PASS**. The **not-yet-built**
candidate/apply/per-tier-export surfaces (Codex C063-02/C063-03) must adopt the
named guards in §3 **before they ship** — those are the **required fixes**, to be
re-reviewed once implemented. Nothing unsafe ships today; v0.6.3 cannot be
declared BLOCKED on unwritten code, but it **must not** release the improvement
half until §3 is satisfied.

## 1. Existing surfaces — PASS (verified in code)

| Surface | File:symbol | Why it passes |
| --- | --- | --- |
| Event log write | `search_core.py:event_safe_payload` (582), `log_event` (607) | `query/task/filter` -> `*_summary_hash` + `*_present`; `notes` -> presence+length bucket; `path` -> library-relative or dropped; `hits` -> safe rows (name/collection/score_bucket only) |
| Session correlation | `search_core.py:hash_session_id` (441), `_local_salt` (405) | salted machine-local sha256, raw id never written, not portable |
| Router meter | `search_core.py:record_router_call` (637) | stores skill name, numeric score, codes/timing only; atomic write; failure swallowed |
| Feedback row | `commands/library.py:cmd_feedback` (236) | routed through `event_safe_payload` before write |
| Feedback report | `feedback.py:assert_feedback_report_safe` (415) | fail-closed: forbidden field names, forbidden-text regex (paths/tokens/keys/Bearer), `*_included` flags forced false |
| Feedback aggregate | `feedback.py:_learning_feedback_summary` (213) | verdict counts only; `notes_included`/`queries_included` false |

**No telemetry / no hosted upload (verified):** `feedback.py` report sets
`network_calls/hosted_calls/upload_available = false`; no network client in any
reviewed path.

## 2. SHA256 vs signature wording — must not overclaim

The per-tier artifacts (Enterprise evidence pack, Registered report) describe
archive integrity. **Required:** integrity is **SHA256 verification**; the word
**"signed"/"signature"** must not appear as a claim unless the code performs
cryptographic signing. The Enterprise spec already carries
`integrity.signature: not-claimed` — keep this; reject any release copy that says
"signed packs" without signing code. (E19 bundle signing is parked / out of this
release.)

## 3. Required guards for the NEW candidate surfaces (release-blocking preconditions)

| # | Risk | File (to be created, C063-02/03) | Required fix | Release impact |
| --- | --- | --- | --- | --- |
| R1 | Candidate text embeds raw query/prompt/task | `improvement-candidates` generator | Derive candidates only from already-sanitized rows; never re-read raw signal text; pass output through a fail-closed `assert_*_safe` mirroring `assert_feedback_report_safe` | BLOCKS improvement half until present |
| R2 | Dry-run diff leaks skill body / absolute paths | `apply-candidate --dry-run` | Diff renders library-relative paths only; skill-body excerpts redacted/bucketed; explicit "no files changed" footer; assert no forbidden text | BLOCKS |
| R3 | Dry-run is secretly mutating | `apply-candidate --dry-run` | No write to library/index/config in dry-run; covered by a non-mutation test (snapshot before==after) | BLOCKS |
| R4 | Auto-apply / auto-publish | candidate apply path | Apply is a separate explicit human command; no implicit apply; no publish verb in Free/Registered/Team/Business/Enterprise v0.6.3 | BLOCKS |
| R5 | Per-tier artifact leaks identity/paths | registered report / team packet / business backlog / enterprise pack | Each export runs a fail-closed safety assertion; team uses aliases not OS user/email; business uses workflow **classes** not raw tasks; no raw install id | BLOCKS that tier's export |
| R6 | `learning doctor` prints raw signal | `learning doctor` | Doctor prints counts/buckets/health only; no raw query/notes; empty-state safe | PASS_WITH_FIXES |
| R7 | Candidate report shared externally still leaks | all paste-safe outputs | Reuse `feedback.py` FORBIDDEN_FIELD_NAMES + FORBIDDEN_TEXT_RE; add fixtures with planted needles (raw path, `sk_`/`ghp_` token, BEGIN PRIVATE KEY) that must fail | BLOCKS sharing claim |

## 4. Confirmations required from implementation (checklist for re-review)

- [ ] No telemetry by default; no hosted upload in any candidate/apply path.
- [ ] Dry-run proven non-mutating by test.
- [ ] No auto-rewrite, no auto-publish anywhere.
- [ ] Candidate + per-tier outputs pass a fail-closed safety assertion with
      planted-needle fixtures.
- [ ] SHA256/signature wording honest (no "signed" without signing code).
- [ ] Verdict taxonomy (missed/wrong) stored via `event_safe_payload`.

## 5. Blocking fixes vs non-blocking

- **Blocking (improvement half):** R1-R5, R7 — the candidate/apply/export
  surfaces must not ship without these.
- **Non-blocking (hardening):** R6 doctor output (fixable in-flight), and adding
  a dedicated `tests/test_*_privacy_grep` for each new artifact (strongly
  recommended, mirrors the existing feedback privacy grep that caught a real leak
  in A3.1.1).

## 6. Recommendation

Existing surfaces: **PASS**. Release the v0.6.3 improvement half only after Codex
C063-02/C063-03 implement R1-R5/R7 and this review re-runs to **PASS**. Until
then, release notes must use the honest framing from O063-01 ("captures signal
and is measurable", not "auto-improves"). No code changes were made here.
