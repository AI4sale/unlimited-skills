# Local Event Privacy Support Runbook

Purpose: help maintainers answer questions about local event logs, local
feedback rows, paste-safe reports, and the `v0.5.3-alpha` privacy hardening
without asking users for unsafe evidence or making support promises.

Status: A4.11 support guidance. This is documentation only; it does not add
telemetry, upload paths, hosted calls, paid support, formal response-time
commitments, hosted readiness, team readiness, or enterprise readiness.

## What Local Event Logs Are For

Unlimited Skills can write local diagnostic rows so the local operator can
understand search, skill routing, MCP savings, feedback, and learning-loop
behavior on their own machine.

The main local files are:

- `<library>/.learning/events.jsonl`;
- `<library>/.learning/feedback.jsonl`;
- `<home>/.learning/team-events.jsonl`;
- local MCP audit logs when MCP audit tooling is used.

These files are local diagnostic material. They are not telemetry. The public
core does not upload them.

## What Changed In A4.10 / v0.5.3

`v0.5.3-alpha` packages the A4.10 local event privacy hardening:

- new search, skill-use, daemon, and feedback rows replace raw query/task text
  with hashes and presence flags;
- raw freeform feedback notes are not persisted as raw text in hardened rows;
- exact hit scores are bucketed in event hit metadata;
- local absolute paths are removed or converted to library-relative paths when
  safe;
- `feedback prepare` remains the paste-safe support surface;
- `learning-summary --events` remains aggregate-only.

Important limitation: `v0.5.3-alpha` hardens new rows. It does not magically
rewrite old local logs that were created before the A4.10 hardening. Treat
legacy pre-v0.5.3 rows as potentially containing raw query text, notes, local
paths, or other local details.

In short: `v0.5.3-alpha` does not magically rewrite old local logs.

## Paste-Safe And Not Paste-Safe

Paste-safe by design:

- `unlimited-skills feedback prepare`;
- `unlimited-skills feedback prepare --format markdown`;
- `unlimited-skills feedback prepare --include-usage-snapshot --format markdown`;
- `unlimited-skills learning-summary --events` when copied as aggregate output;
- redacted command names, step names, OS family, Python family, install method,
  and trimmed errors with usernames, paths, tokens, keys, and secrets removed.

Not paste-safe by default:

- raw `.learning/events.jsonl`;
- raw `.learning/feedback.jsonl`;
- raw `.learning/team-events.jsonl`;
- raw MCP audit JSONL logs;
- raw `.mcp.json`;
- raw `.claude.json`;
- environment dumps;
- tokens, keys, proofs, private config values, local absolute paths;
- prompts, tool inputs, tool outputs, skill bodies, or MCP schemas.

## Safe User Guidance

When a user reports a privacy concern, ask for:

1. the command or feature category involved;
2. the expected privacy boundary in their own words;
3. `unlimited-skills feedback prepare --format markdown`;
4. a redacted command name, step name, or error excerpt only if needed.

Do not ask users to paste, attach, send, or upload raw local event logs. Do not
ask for raw config files, env values, tokens, keys, local paths, prompts, tool
inputs, tool outputs, skill bodies, or MCP schemas.

## Inspecting Local Logs Safely

Users may inspect their own local logs on their own machine. Maintainers should
frame this as local self-inspection, not as something to paste into an issue.

Safe local inspection examples:

```bash
unlimited-skills learning-summary --events
unlimited-skills feedback prepare --format markdown
```

If a user intentionally opens a raw local JSONL file, they should inspect it
locally and report only a redacted summary such as:

- which command or event type looked wrong;
- whether a raw value appeared;
- the field name, if safe;
- whether the row was created before or after `v0.5.3-alpha`.

## Deleting Or Rotating Local Logs Safely

Users control their local logs. If they want to clear local learning history,
they can move the files aside or delete only the specific local diagnostic
files they choose.

Recommended safe workflow:

1. close running Unlimited Skills daemon/processes first;
2. locate the active library root with the install docs or local config;
3. optionally archive the specific `.learning` files outside the project;
4. delete or rename only the selected diagnostic files;
5. run `unlimited-skills feedback prepare --format markdown` or
   `unlimited-skills learning-summary --events` afterward to confirm the new
   local state.

Do not tell users to delete their whole skill library. Do not ask for the
archive. Do not ask them to upload the old raw files.

## Maintainer Response Rules

Maintainers may ask for:

- `feedback prepare` output;
- aggregate `learning-summary --events` output;
- OS/Python/install method;
- redacted command names or step names;
- redacted error excerpts;
- a yes/no answer about whether the row was pre-v0.5.3 or post-v0.5.3.

Maintainers must never ask for:

- raw `events.jsonl`;
- raw `feedback.jsonl`;
- raw `team-events.jsonl`;
- raw MCP audit JSONL logs;
- raw `.mcp.json`;
- raw `.claude.json`;
- env dumps;
- tokens, keys, proofs, private config values;
- local absolute paths;
- prompts, tool inputs, tool outputs, skill bodies, or MCP schemas.

## Legacy Pre-v0.5.3 Handling

If a user reports a legacy row with unsafe content:

1. acknowledge that old local rows may predate A4.10 hardening;
2. ask them not to paste the raw row;
3. ask whether the issue reproduces after upgrading to `v0.5.3-alpha` or later;
4. ask for `feedback prepare --format markdown` after the upgrade;
5. if the issue reproduces in new rows, treat it as a privacy bug and route it
   to maintainer review.

## Claims To Avoid

Do not claim:

- telemetry exists or was added;
- uploads exist or were added;
- hosted support is available;
- team or enterprise privacy controls are ready;
- paid support, formal response-time coverage, delivery dates, or payment paths exist;
- all legacy local logs were rewritten by the upgrade.

## Related Docs

- [Local event privacy policy](local-event-privacy-policy.md)
- [Local event privacy audit](local-event-privacy-audit.md)
- [Public-alpha support response pack](support-response-pack.md)
- [Feedback guide](../feedback.md)
- [v0.5.3-alpha release notes](../releases/v0.5.3-alpha.md)
