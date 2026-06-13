# Local Event Privacy Policy

Status: active policy. A4.10 adds runtime enforcement for local event and
feedback rows.

Unlimited Skills may write local diagnostic events so the local operator can
understand whether search, skill routing, MCP savings, and feedback workflows
are working. These events are local-first. They are not telemetry and are not
uploaded by the public core. In short: not uploaded.

## Policy

1. Local event logs must not be treated as support artifacts by default.
2. Public/support workflows should prefer `unlimited-skills feedback prepare`
   because it emits a redacted summary.
3. Local events must not contain raw prompts, raw task text, raw query text,
   tool inputs, tool outputs, skill bodies, tokens, private keys, proofs,
   environment names, environment values, raw MCP schemas, raw Claude configs,
   or local absolute paths unless a field is explicitly marked
   `document-local-only` in the A4.9 audit.
4. `document-local-only` means the field may remain on the user's machine for
   diagnostics, but it must not appear in paste-safe support output.
5. Raw query/task values should be represented by a local-safe
   `task_summary_hash` where correlation is needed.
6. Session correlation must use a machine-local private salt or a per-process
   run id. Raw session ids and globally stable unsalted fingerprints are not
   allowed.
7. Search/view/use logs should prefer skill names, collections, counts, reason
   codes, and buckets over paths, raw scores, or raw task text.
8. MCP savings logs may use counts and byte sizes. MCP server names are
   local-only operator diagnostics unless a future stricter mode hashes them.
9. Team and policy audit logs may include local operational identifiers only
   when tokens, auth headers, private keys, sensitive download URLs, and local
   filesystem paths are excluded.
10. MCP audit replay/inspector tools must keep raw imported `tools_schema` and
    `tools_call` rows out of public/support reports. Summaries and counts are
    acceptable.

## A4.10 Runtime Enforcement

Runtime writers now sanitize local `.learning/events.jsonl` and
`.learning/feedback.jsonl` rows before persistence:

- raw `query`, `task`, and `filter` fields are replaced with
  `query_summary_hash`, `task_summary_hash`, or `filter_summary_hash` plus a
  `*_present` boolean;
- raw freeform `notes` are replaced with `notes_present` and
  `notes_length_bucket`;
- absolute `path` fields are replaced with `library_path` only when the path
  is inside the configured library root;
- search hit metadata keeps name/collection/description and converts exact
  scores to `score_bucket`; raw `score` and `path` are not persisted in event
  hit rows;
- MCP server names remain documented-local-only operator diagnostics for MCP
  savings; support workflows still prefer redacted `feedback prepare` output.

This enforcement does not add telemetry, uploads, hosted calls, or any support
bundle that treats raw local logs as paste-safe.

## Paste-Safe Surfaces

These surfaces are intended to be paste-safe:

- `unlimited-skills feedback prepare`;
- `unlimited-skills feedback prepare --format markdown`;
- `learning-summary --events`;
- public-alpha signal rollups generated from allowed aggregate inputs.

These surfaces are not automatically paste-safe:

- raw `<library>/.learning/events.jsonl`;
- raw `<library>/.learning/feedback.jsonl`;
- raw `<home>/.learning/team-events.jsonl`;
- raw hub audit logs;
- raw MCP audit replay inputs;
- local config files such as `.mcp.json` or `.claude.json`.

## Required Guards

Docs and tests must preserve these guards:

- no telemetry;
- no auto-upload;
- no hosted calls;
- no tracking pixels;
- no analytics SDK;
- no prompt collection;
- no tool input collection;
- no tool output collection;
- no paid CTA;
- no payment link;
- no hosted readiness claim;
- no team readiness claim;
- no enterprise readiness claim;
- #119 remains parked unless the owner explicitly reopens it.

## Owner / Action / Fallback

| risk | owner | action | fallback |
|---|---|---|---|
| Raw query/task text in event rows | Codex | A4.10 replaces with `query_summary_hash` / `task_summary_hash` or removes. | Disable writing the risky field. |
| Local absolute paths in event rows | Codex | A4.10 replaces with library-relative `library_path` when safe, otherwise removes. | Keep only skill name/collection. |
| Freeform feedback notes | Codex | A4.10 stores only note presence and length bucket. | Keep verdict counts only. |
| MCP server names | Codex | A4.10 keeps them documented-local-only for MCP savings diagnostics. | Hash server names and keep counts in a future stricter mode. |
| Team/policy operational ids | Codex | Keep local-only; never include tokens/auth/private keys/paths. | Hash ids in exported support summaries. |
| Raw MCP audit rows | Codex | Keep out of support/public reports. | Summaries only. |

## A4.10 Acceptance Dependency

A4.10 must use this policy and `local-event-privacy-audit.md` as the acceptance
contract. It should not broaden the public support surface, add telemetry,
create uploads, or alter #119/E19 scope.
