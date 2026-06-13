# Local Event Privacy

Unlimited Skills keeps local learning and diagnostic events on the user's
machine. These files help the local operator understand search, routing,
feedback, and MCP savings behavior. They are not telemetry and are not
uploaded by the public core.

## Local Files

The main local diagnostic surfaces are:

- `<library>/.learning/events.jsonl`;
- `<library>/.learning/feedback.jsonl`;
- `<home>/.learning/team-events.jsonl`;
- local MCP audit JSONL logs when MCP audit tooling is used.

Raw files are not paste-safe support artifacts. Public issues should use
`unlimited-skills feedback prepare --format markdown` or aggregate
`unlimited-skills learning-summary --events` output instead.

## v0.5.3 and Later Contract

For new local rows written after the A4.10 hardening packaged in
`v0.5.3-alpha`:

- raw query/task/filter text is replaced with summary hashes and presence
  flags;
- raw freeform feedback notes are not persisted as raw text;
- exact hit scores are bucketed;
- local absolute paths are removed or converted to library-relative paths when
  safe;
- `learning-summary --events` remains aggregate-only;
- `feedback prepare` remains the paste-safe support surface.

The upgrade does not rewrite legacy pre-v0.5.3 local logs. Treat older raw
local logs as potentially containing raw query text, notes, local paths, or
other local details.

## Paste-Safe Surfaces

Paste-safe by design:

- `unlimited-skills feedback prepare`;
- `unlimited-skills feedback prepare --format markdown`;
- `unlimited-skills feedback prepare --include-usage-snapshot --format markdown`;
- `unlimited-skills learning-summary --events` aggregate output;
- redacted command names, step names, OS family, Python family, install method,
  and trimmed errors with usernames, local paths, tokens, keys, and secrets
  removed.

Not paste-safe by default:

- raw `.learning/events.jsonl`;
- raw `.learning/feedback.jsonl`;
- raw `.learning/team-events.jsonl`;
- raw MCP audit JSONL logs;
- raw `.mcp.json`;
- raw `.claude.json`;
- env dumps;
- tokens, keys, proofs, private config values;
- local absolute paths;
- prompts, tool inputs, tool outputs, skill bodies, or MCP schemas.

## Support Boundary

Maintainers should use
[adoption/local-event-privacy-support-runbook.md](adoption/local-event-privacy-support-runbook.md)
for local event privacy questions.

Maintainers may ask for:

- `feedback prepare` output;
- aggregate `learning-summary --events` output;
- OS/Python/install method;
- redacted command names or step names;
- redacted error excerpts;
- whether a row was created before or after `v0.5.3-alpha`.

Maintainers must never ask users to paste, attach, send, or upload raw local
event logs, raw MCP audit logs, raw config files, env dumps, tokens, keys,
local paths, prompts, tool inputs, tool outputs, skill bodies, or MCP schemas.

## Non-Claims

This privacy contract does not add telemetry, automatic upload, analytics,
tracking pixels, hosted query forwarding, marketplace submission, paid support,
payment paths, hosted service readiness, team readiness, enterprise readiness,
or a formal response-time commitment.
