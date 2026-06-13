# Public-alpha support response pack

Use these templates for early public-alpha GitHub issues, launch replies, and
maintainer follow-ups. They are intentionally conservative: ask for redacted
local evidence only, route to labels/backlog, and do not promise support
coverage, delivery dates, paid plans, hosted services, team features, or
enterprise readiness.

## Safety contract

- Prefer `unlimited-skills feedback prepare --format markdown`.
- For MCP measurement reports, prefer
  `unlimited-skills feedback prepare --include-usage-snapshot --format markdown`.
- Ask for commands only when the command itself is already user-visible and can
  be redacted.
- Ask for trimmed error output only after usernames, machine names, local paths,
  tokens, keys, secrets, environment values, and private identifiers are
  replaced with placeholders.
- Do not ask for prompts, tool inputs, tool outputs, skill bodies, MCP schemas,
  raw `.mcp.json`, raw `.claude.json`, shell history, env dumps, proofs,
  tokens, keys, or unredacted local paths.
- Treat every response as triage language, not a formal response-time
  commitment, support guarantee, sales offer, payment path, hosted-service
  promise, team-readiness claim, or enterprise-readiness claim.

## Response map

| Response type | Labels | Backlog route | Safe evidence |
| --- | --- | --- | --- |
| First value succeeded | `feedback:first-value`, `severity:p2-improvement`, `needs:maintainer-review` | Adoption notes | `feedback prepare --format markdown`, what worked, rough time-to-value |
| Install failed | `feedback:install-friction`, `severity:p1-high-friction`, `needs:repro` | Install/package backlog | OS/Python family, install method, redacted failing command, redacted error excerpt |
| Quickstart failed | `feedback:first-value`, `severity:p1-high-friction`, `needs:repro` | Quickstart backlog | `feedback prepare --format markdown`, step name, redacted quickstart excerpt |
| Claude Code MCP install failed | `feedback:install-friction`, `severity:p1-high-friction`, `needs:repro` | Claude Code install/MCP docs backlog | `feedback prepare --format markdown`, Claude Code MCP configured/not configured status, redacted error excerpt |
| Skill was not invoked | `feedback:skill-invocation`, `severity:p1-high-friction`, `needs:maintainer-review` | Retrieval eval backlog | paraphrased task keywords, expected skill name if known, `suggest --json` result, feedback report |
| Wrong skill suggested | `feedback:skill-invocation`, `severity:p1-high-friction`, `needs:maintainer-review` | Retrieval eval backlog | paraphrased task keywords, expected/actual skill names, `suggest --json` result |
| MCP savings confusing or low savings | `feedback:mcp-savings`, `severity:p2-improvement`, `needs:maintainer-review` | Benchmark/docs backlog | `feedback prepare --include-usage-snapshot --format markdown`, `mcp savings` names/counts/sizes/status output |
| Feedback report attached | existing issue labels | Existing issue route | attached prepared report, report section that looks relevant |
| Privacy concern | type label matching concern, escalate severity if reproduced | Privacy/docs/code backlog | claim category, affected command, redacted local report showing no sensitive values |
| Marketplace/listing discovery question | `feedback:marketplace`, `severity:p2-improvement`, `needs:maintainer-review` | Listing backlog | destination/surface name, current public link, wording concern |

## Templates

### First value succeeded

Thanks for trying the public alpha. This is useful signal because Unlimited
Skills deliberately has no telemetry.

If you are willing to add one redacted report, please run:

```bash
unlimited-skills feedback prepare --format markdown
```

Please include only the prepared report plus a short note on what delivered
value and roughly how long it took. We will route this as
`feedback:first-value` / `severity:p2-improvement` /
`needs:maintainer-review` and use it to preserve the path that worked.

### Install failed

Thanks for reporting the install failure. Please keep the report redacted and
avoid sharing secrets or machine-specific paths.

For the current public-alpha path, the canonical install is:

```bash
pip install "unlimited-skills>=0.5.1"
unlimited-skills quickstart
```

If that path failed, please share:

- OS family and Python family;
- install method, for example PyPI, repo checkout, or Claude Code plugin;
- the redacted failing command;
- the trimmed error excerpt with usernames, local paths, tokens, and keys
  replaced by placeholders;
- output from `unlimited-skills feedback prepare --format markdown` if it can
  run.

We will route this as `feedback:install-friction` /
`severity:p1-high-friction` / `needs:repro`.

### Quickstart failed

Thanks for trying the quickstart. The v0.5.1+ public-alpha path should be:

```bash
pip install "unlimited-skills>=0.5.1"
unlimited-skills quickstart
```

Please share the step where it stopped and a redacted excerpt from
`unlimited-skills quickstart`. If possible, also attach:

```bash
unlimited-skills feedback prepare --format markdown
```

Keep the report to version, OS/Python family, install method, indexed skill
counts, quickstart status, and redacted errors. We will route this as
`feedback:first-value` with `needs:repro` and assign it to the quickstart
backlog.

### Claude Code MCP install failed

Thanks for checking the Claude Code MCP path. Please do not paste raw
`.mcp.json`, raw `.claude.json`, server commands, args, or environment values.

Please share only:

- OS family and Python family;
- whether `pip install "unlimited-skills>=0.5.1"` succeeded;
- whether `unlimited-skills quickstart` succeeded;
- the Claude Code MCP configured/not configured status from
  `unlimited-skills feedback prepare --format markdown`;
- a redacted error excerpt if the installer printed one.

We will route this as `feedback:install-friction` /
`severity:p1-high-friction` / `needs:repro` and check the Claude Code installer
docs and smoke path first.

### Skill was not invoked

Thanks for the retrieval report. A valid missed invocation should become a
frozen eval candidate before ranking changes are made.

Please share:

- a paraphrase or 3-8 safe task keywords;
- the skill name you expected, if known;
- the output of `unlimited-skills suggest "<same safe keywords>" --json`;
- optional `unlimited-skills feedback prepare --format markdown` output.

Please do not paste the original task prompt, tool inputs, tool outputs, skill
bodies, or local paths. We will route this as `feedback:skill-invocation` /
`severity:p1-high-friction` / `needs:maintainer-review` and evaluate it against
the frozen effectiveness set before changing retrieval.

### Wrong skill suggested

Thanks for the wrong-suggestion report. These reports are most useful when we
can compare expected and actual skill names without seeing private task text.

Please share:

- a paraphrase or safe keywords for the task;
- the expected skill name if you know it;
- the actual suggested skill name;
- the output of `unlimited-skills suggest "<same safe keywords>" --json`;
- optional `unlimited-skills feedback prepare --format markdown` output.

We will route this as `feedback:skill-invocation` and add a frozen eval
candidate when the miss is reproducible.

### MCP savings confusing or low savings

Thanks for measuring your local MCP setup. Savings depend on how many MCP
servers and schemas your host loads, so low savings can be a valid result.

Please share only names, counts, byte sizes, token estimates, and status
strings from:

```bash
unlimited-skills mcp savings
unlimited-skills feedback prepare --include-usage-snapshot --format markdown
```

Do not paste MCP schemas, server configs, spawn commands, args, environment
values, raw `.mcp.json`, or raw `.claude.json`. We will route this as
`feedback:mcp-savings` / `severity:p2-improvement` /
`needs:maintainer-review` and compare it with the benchmark docs.

### Feedback report attached

Thanks for attaching a prepared report. Prepared reports are the preferred
evidence path because they are local-only and redact sensitive fields by
contract.

We will inspect the report type, apply the matching `feedback:*` label, choose
the severity, and route it through
[feedback-to-backlog-routing.md](feedback-to-backlog-routing.md). If we need a
follow-up, we will ask only for a redacted command, step name, or prepared
report section.

### Privacy concern

Thanks for raising the privacy concern. Unlimited Skills should not collect
telemetry, auto-upload data, collect prompts, collect tool inputs, collect tool
outputs, or send local reports anywhere by itself.

Please share:

- the command or feature category involved;
- what you expected to stay local;
- a redacted `unlimited-skills feedback prepare --format markdown` report if
  it helps show the local status;
- any public doc line that looked unclear.

Do not paste secrets, environment values, raw config files, proofs, local
paths, prompts, tool inputs, or tool outputs. If the concern suggests a real
automatic upload or sensitive-data exposure, we will escalate severity and
reproduce it before changing code or docs.

### Marketplace/listing discovery question

Thanks for the marketplace/listing feedback. Current public-alpha marketplace
work is tracked as owner-approved submission preparation, not as a claim of
acceptance or hosted readiness.

Please share the destination or surface name, the public link or listing text
you saw, and the wording that confused you. Do not include account data,
private marketplace forms, payment details, or non-public submission screens.

We will route this as `feedback:marketplace` / `severity:p2-improvement` /
`needs:maintainer-review`, re-check the submission tracker and listing copy,
and avoid paid, hosted, team, enterprise, payment, delivery, or acceptance
claims unless there is explicit evidence.
