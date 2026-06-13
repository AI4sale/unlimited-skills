# Feedback guide

Unlimited Skills sends **no telemetry**. There is no auto-upload, no crash
reporter, no usage ping: search, suggestion, indexing, and the MCP savings
measurement all run on your machine, and the learning logs are local files
under your library's `.learning/` directory. The project only learns what
you choose to tell it — feedback is manual and voluntary, through GitHub
issues.

## Prepare a paste-safe report

Use `feedback prepare` to generate a local, redacted report you can paste into
a GitHub issue:

```bash
unlimited-skills feedback prepare
unlimited-skills feedback prepare --include-usage-snapshot
unlimited-skills feedback prepare --format markdown --out feedback.md
unlimited-skills feedback doctor
```

The command does not upload anything. It prints or writes a report only on
your machine. The report includes coarse metadata such as Unlimited Skills
version, OS family, Python family, install method, indexed skill counts,
quickstart status, local suggest outcome counts, Claude Code MCP installer
configured/not configured status, issue-template mapping, and latest local
error categories.

`--include-usage-snapshot` may also include local MCP savings counts: server
names, tool counts, byte counts, token estimates, and status strings. It still
does not include MCP schemas, spawn commands, args, environment names or
values, raw `.mcp.json`, or raw `.claude.json`.

The generated report excludes prompts, tool inputs, tool outputs, skill
bodies, MCP schemas, launch commands, environment names or values, tokens,
proofs, private keys, local absolute paths, raw `.mcp.json`, and raw
`.claude.json`.

That makes your reports disproportionately valuable in this public alpha.
One honest "the quickstart stalled at step 2" is worth more than any
dashboard we refuse to build.

## Where to report what

Open an issue at
<https://github.com/AI4sale/unlimited-skills/issues/new/choose> and pick the
matching template:

| You want to say... | Template |
| --- | --- |
| "The first five minutes worked / did not work" | [First-value feedback (quickstart)](../.github/ISSUE_TEMPLATE/first-value-feedback.yml) |
| "Install or setup failed or fought me" | [Install friction](../.github/ISSUE_TEMPLATE/install-friction.yml) |
| "I expected a skill suggestion and got silence or the wrong one" | [Skill not invoked / wrong suggestion](../.github/ISSUE_TEMPLATE/skill-not-invoked.yml) |
| "Here are my measured MCP savings numbers" | [MCP savings report](../.github/ISSUE_TEMPLATE/mcp-savings-report.yml) |

Anything that fits none of these — a plain blank issue is fine too.

## Before you paste output

- Prefer `unlimited-skills feedback prepare` and paste the generated JSON or
  Markdown into the matching issue template.
- `suggest` and `mcp savings` output is privacy-safe by contract (skill
  names, sources, scores, server names, counts, byte sizes — never your
  prompt text, never local paths, never skill bodies or schema contents).
  Check anyway before pasting.
- Never paste MCP server configuration, spawn commands, environment
  variables, or tokens. The savings template has a required checkbox for
  exactly this.
- Replace usernames and machine paths in tracebacks with placeholders.

## What happens to your report

It stays a public GitHub issue, triaged by maintainers. Retrieval misses
feed the frozen effectiveness eval set discussion (see
[adoption/skill-effectiveness-standard.md](adoption/skill-effectiveness-standard.md)
for how suggestion quality is gated); install friction feeds the test
matrix; savings reports keep the lab benchmark honest. This is a free
public alpha — there is no paid support channel, and nothing here is a
delivery promise.

## How reports are measured in the first week

The first public-alpha week uses manual adoption measurement only. See
[adoption/first-week-adoption-measurement.md](adoption/first-week-adoption-measurement.md)
and [adoption/adoption-signals.md](adoption/adoption-signals.md) for the exact
signal definitions, success thresholds, failure thresholds, owner actions, and
fallback plan.

The short version: PyPI installs and public GitHub counters are directional;
GitHub issue templates and public launch replies are the first-value signals;
and the fallback for low signal is clearer docs plus manual outreach, not
telemetry.

The privacy contract stays unchanged:

- no telemetry;
- no auto-upload;
- no tracking pixels;
- no analytics SDK;
- no prompt collection;
- no tool input collection;
- no tool output collection.

## Triage and labels

Maintainers use the public-alpha triage workflow in
[adoption/feedback-triage-workflow.md](adoption/feedback-triage-workflow.md),
the label map in [adoption/feedback-labels.md](adoption/feedback-labels.md),
and the backlog routing table in
[adoption/feedback-to-backlog-routing.md](adoption/feedback-to-backlog-routing.md).
Public replies use
[adoption/support-response-pack.md](adoption/support-response-pack.md) so
maintainers ask for redacted evidence only and do not invent support, SLA,
hosted, team, enterprise, payment, or delivery promises.

Every template carries a `feedback:*` type label, a severity label, and either
`needs:repro` or `needs:maintainer-review`. The purpose is fast routing, not a
support promise: labels do not imply sales help, payment handling, hosted
service availability, or enterprise delivery.

No issue label implies hosted service availability or enterprise delivery.
