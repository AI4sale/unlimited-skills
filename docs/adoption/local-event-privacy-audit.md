# Local Event Privacy Audit

Status: A4.9 audit; implementation hardening is deferred to A4.10.

This audit covers local event logs and local support summaries after the
v0.5.2-alpha effectiveness instrumentation release. It is evidence-backed by
the current writers/readers in `unlimited_skills/search_core.py`,
`unlimited_skills/commands/library.py`, `unlimited_skills/suggest.py`,
`unlimited_skills/server.py`, `unlimited_skills/mcp/server.py`,
`unlimited_skills/commands/mcp.py`, `unlimited_skills/quickstart.py`,
`unlimited_skills/feedback.py`, `unlimited_skills/team.py`,
`unlimited_skills/policy_sync.py`, and the MCP audit inspector/replay docs.

No code behavior changes ship in A4.9. This document creates the field-level
contract for A4.10.

## Scope Boundary

- Local event store: `<library>/.learning/events.jsonl`.
- Local feedback store: `<library>/.learning/feedback.jsonl`.
- Team audit store: `<home>/.learning/team-events.jsonl`.
- Hub audit store: `<home>/hub/logs/audit.jsonl`.
- Managed-policy audit rows written by policy sync helpers.
- MCP audit replay/inspector inputs and outputs.
- User-facing summaries that read or summarize local events:
  `learning-summary --events`, `feedback prepare`, MCP savings reports, and
  support response guidance.

Out of scope for A4.9: changing event writers, migrating existing logs,
adding uploads, adding telemetry, or changing user-facing stdout contracts.

## Decision Vocabulary

Field decisions use these values only:

- `keep`: safe local diagnostic data; keep as-is.
- `hash`: replace raw value with a non-reversible local/private hash.
- `redact`: replace with a fixed redacted marker or coarse category.
- `remove`: stop writing the field.
- `document-local-only`: keep only if explicitly documented as local-only.

Risk levels use these values only: `safe`, `caution`, `unsafe`.

Required table shorthand:

- `risk_level: safe | caution | unsafe`
- `decision: keep | hash | redact | remove | document-local-only`

## Event-Type Inventory

| event_type | writer / reader | current behavior | risk summary | A4.10 handoff |
|---|---|---|---|---|
| `suggest` | `unlimited_skills/suggest.py`; read by `learning-summary --events` and `feedback prepare` | Stores `task_summary_hash`, floor, elapsed time, reason code, injection flag, score/margin buckets, top hit names/scores, optional delivery tier, and salted session correlation. | Mostly safe after #148; exact hit scores and skill names are local diagnostic data. | Keep. Document local-only; do not reintroduce raw query text. |
| `search` | `unlimited_skills/commands/library.py` | Stores raw `query`, mode, and top hit metadata. Hit metadata can include library paths from `asdict(hit)`. | Unsafe: raw query/task text and local paths can persist. | Replace `query` with `task_summary_hash`; replace hit paths with names/collections or library-relative paths. |
| `list` | `unlimited_skills/commands/library.py` | Stores collection/filter text, shown count, and total count. | Caution: `filter` can contain user task text. | Hash or redact `filter`; keep counts. |
| `view` | `unlimited_skills/commands/library.py` | Stores skill name and absolute `path`. | Unsafe: local absolute path persists. | Keep skill name; replace path with library-relative path or remove. |
| `skill_used` | `unlimited_skills/commands/library.py`; also MCP skills server use handler | Stores skill name, raw `query`, raw `task`, absolute path, optional source. | Unsafe: raw task/query text and local path persist. | Hash query/task; replace path with library-relative path or remove. |
| `quickstart` | `unlimited_skills/quickstart.py` | Stores library status/counts, first-search hit count, and optional MCP savings snapshot. | Safe/caution: counts are safe; MCP server names in savings are local config identifiers. | Keep counts; document MCP server names as local-only or hash names in A4.10 if policy chooses stricter mode. |
| `mcp_savings` | `unlimited_skills/commands/mcp.py` and `unlimited_skills/mcp/savings.py` | Stores MCP server names, statuses, tool counts, schema byte counts, totals, gateway bytes, and savings percent. | Caution: server names can reveal local tool topology; no commands, env values, schemas, or tokens are stored. | Keep counts; document server names local-only or hash server names in A4.10. |
| `daemon_search` | `unlimited_skills/server.py` | Stores raw query, mode, and top hit metadata. | Unsafe: same risks as `search`, but from long-running daemon. | Same as `search`. |
| `daemon_view` | `unlimited_skills/server.py` | Stores skill name and absolute path. | Unsafe: local absolute path persists. | Same as `view`. |
| `daemon_skill_used` | `unlimited_skills/server.py` | Stores skill name, raw query/task, and absolute path. | Unsafe: same as `skill_used`. | Same as `skill_used`. |
| `daemon_feedback` | `unlimited_skills/server.py` | Stores skill name, raw query, verdict, and notes. | Unsafe: query and notes can contain task text or private details. | Hash query; redact/freeform-limit notes or move notes to explicit local feedback only. |
| `feedback.jsonl` rows | `unlimited_skills/commands/library.py feedback`; summarized by `learning-summary` | Stores name, raw query, verdict, and notes. | Unsafe/caution: raw query and notes can contain private task text. | Hash query; redact notes or document as explicit local-only operator notes. |
| `team-events.jsonl` rows | `unlimited_skills/team.py` | Stores team/install identifiers, result, reason, request id, and redacted flag; sensitive text is passed through `redact_sensitive_text`. | Caution: install/team ids are operational identifiers; reason/request fields are redacted. | Keep with documented local-only boundary; ensure no tokens/auth headers are ever written. |
| `managed_policy_remove_refused` | `unlimited_skills/policy_sync.py` | Stores policy ids and assignment id for refusal audit. | Safe/caution: identifiers are not tokens but can reveal local policy state. | Keep local-only; no hosted tokens/private keys/paths. |
| Hub audit events | documented in `docs/local-skill-hub.md` | Stores event names, client/token ids, skill names, and query SHA256 values. Raw hub tokens and raw search text are documented as not logged. | Caution: token ids/client ids are operational identifiers. | Keep; document local-only and avoid raw query/token persistence. |
| MCP audit replay/inspector events | `unlimited_skills/mcp/audit_replay.py`, `unlimited_skills/mcp/audit_inspector.py`, docs | Reads/imports MCP audit rows such as `tools_schema`, `tools_call`, and `profile_loaded`; reports counts and missing identity. | Caution/unsafe depending on source: raw tool schemas/calls can contain tool input/output data. | Do not include raw imported audit rows in public/support outputs; keep summaries only. |
| `learning-summary --events` output | `unlimited_skills/commands/library.py` | Emits aggregate counts/rates/buckets only. | Safe if it remains aggregate-only. | Keep; tests must ensure no query text, raw session ids, session hashes, paths, prompts, or skill bodies are printed. |
| `feedback prepare` output | `unlimited_skills/feedback.py` | Reads events but emits redacted summaries, counts, issue template routing, and privacy flags. | Safe if `assert_feedback_report_safe` keeps rejecting forbidden fields/text. | Keep; boundary verifier remains required. |

## Field-Level Classification

| field | event_type | current_behavior | risk_level | decision | owner | fallback | implementation_task |
|---|---|---|---|---|---|---|---|
| `payload.task_summary_hash` | `suggest` | Short hash of normalized query. | safe | keep | Codex | Disable correlation if hash generation fails. | A4.10 keep invariant. |
| `payload.session_correlation_id` | all `events.jsonl` rows after #148 | Salted local-private session/run correlation. | caution | document-local-only | Codex | Omit the field if salt/session handling fails. | A4.10 keep salted/local-only invariant. |
| `payload.hits[].name` | `suggest`, `search`, `daemon_search` | Skill name. | caution | keep | Codex | Keep count only if skill names are considered too revealing. | A4.10 decide strict mode if needed. |
| `payload.hits[].score` | `suggest`, `search`, `daemon_search` | Exact score in hit metadata. | caution | redact | Codex | Replace with score bucket. | A4.10 convert to score buckets for non-stdout event logs. |
| `payload.hits[].path` | `search`, `daemon_search` | Local or library path from hit metadata. | unsafe | redact | Codex | Use skill name/collection only. | A4.10 remove paths from search event hits. |
| `payload.query` | `search`, `daemon_search`, `skill_used`, `daemon_skill_used`, `daemon_feedback`, `feedback.jsonl` | Raw user query/task text. | unsafe | hash | Codex | Remove field if hashing cannot be done safely. | A4.10 replace with `task_summary_hash`. |
| `payload.task` | `skill_used`, `daemon_skill_used` | Raw task text. | unsafe | hash | Codex | Remove field if hashing cannot be done safely. | A4.10 replace with `task_summary_hash` or `task_hash`. |
| `payload.path` | `view`, `skill_used`, `daemon_view`, `daemon_skill_used` | Absolute local filesystem path. | unsafe | redact | Codex | Use library-relative path or omit. | A4.10 remove absolute paths from local event rows. |
| `payload.filter` | `list` | Freeform filter string. | caution | hash | Codex | Keep empty/non-empty flag only. | A4.10 hash or redact filter. |
| `payload.notes` | `daemon_feedback`, `feedback.jsonl` | Freeform operator notes. | unsafe | document-local-only | Codex | Redact by default in daemon path; keep only explicit local feedback notes. | A4.10 decide redaction vs explicit-local notes. |
| `payload.verdict` | feedback rows | Accepted/rejected/neutral. | safe | keep | Codex | Keep counts only. | A4.10 keep. |
| `payload.elapsed_ms` | `suggest` | Local latency. | safe | keep | Codex | Bucket if needed. | No code change required. |
| `payload.reason_code` | `suggest`, feedback summaries | Reason/status code. | safe | keep | Codex | Keep category only. | No code change required. |
| `payload.score_bucket` | `suggest` | Coarse score band. | safe | keep | Codex | Omit if scoring changes. | No code change required. |
| `payload.margin_bucket` | `suggest` | Coarse margin band. | safe | keep | Codex | Omit if scoring changes. | No code change required. |
| `payload.library_status`, `payload.skill_count`, `payload.search_hits` | `quickstart` | Counts/status only. | safe | keep | Codex | Keep counts only. | No code change required. |
| `payload.savings.servers[].name` | `quickstart`, `mcp_savings` | MCP server names. | caution | document-local-only | Codex | Hash server names in stricter mode. | A4.10 decide. |
| `payload.savings.*_bytes`, `tools_count`, `status` | `quickstart`, `mcp_savings` | Counts, statuses, byte sizes. | safe | keep | Codex | Keep counts only. | No code change required. |
| `team_id`, `actor_install_id`, `target_install_id`, `request_id` | `team-events.jsonl` | Operational identifiers, redacted request id. | caution | document-local-only | Codex | Hash ids if exported outside local support. | A4.10 no upload; document local-only. |
| `installed_policy_id`, `managed_policy_id`, `assignment_id` | managed policy audit | Local policy identifiers. | caution | document-local-only | Codex | Hash identifiers if exported. | A4.10 no raw export in support outputs. |
| raw MCP `tools_schema` / `tools_call` rows | MCP audit replay inputs | Imported raw schemas/calls may include sensitive input/output. | unsafe | document-local-only | Codex | Summarize counts only. | A4.10 keep raw rows out of support/public outputs. |

## Unsafe And Caution Field List

Unsafe:

- raw query/task text in `search`, `daemon_search`, `skill_used`,
  `daemon_skill_used`, `daemon_feedback`, and `feedback.jsonl`;
- local absolute paths in `view`, `skill_used`, `daemon_view`,
  `daemon_skill_used`, and search hit metadata;
- freeform feedback notes when captured through daemon or local feedback rows;
- raw MCP audit schemas/calls if imported into audit tooling outputs.

Caution:

- salted local session correlation ids;
- skill names in local hit/event rows;
- exact hit scores in local event rows;
- MCP server names in `mcp_savings` snapshots;
- team/install/policy ids in local audit rows.

## User-Facing Output Boundary

User-facing stdout is not the same surface as local event logs.

- `suggest --json` remains a public/user-facing contract and must not contain
  raw task text, local paths, prompts, skill bodies outside the explicit card
  channel, env values, tokens, or tool IO.
- `learning-summary --events` must remain aggregate-only.
- `feedback prepare` must remain redacted and paste-safe.
- `mcp savings` may show local MCP server names to the local operator, but
  support workflows must ask for redacted `feedback prepare` output by default.

## A4.10 Handoff

Implementation tasks for A4.10:

1. Replace raw query/task fields in `search`, `daemon_search`, `skill_used`,
   `daemon_skill_used`, `daemon_feedback`, and `feedback.jsonl` with
   `task_summary_hash` or remove the field.
2. Remove absolute paths from `view`, `skill_used`, `daemon_view`,
   `daemon_skill_used`, and search hit event metadata.
3. Convert exact search hit scores in event logs to buckets or omit them.
4. Decide whether MCP server names stay documented-local-only or are hashed in
   local event snapshots.
5. Keep `learning-summary --events` and `feedback prepare` aggregate/redacted.
6. Add privacy grep tests that write representative events and assert no raw
   prompt/task/query text, absolute paths, env values, tokens, tool IO, or skill
   bodies persist in hardened event rows.

## Non-Goals

- No telemetry.
- No upload path.
- No hosted calls.
- No paid CTA.
- No payment link.
- No hosted readiness claim.
- No team readiness claim.
- No enterprise readiness claim.
- No #119 / E19 work.
