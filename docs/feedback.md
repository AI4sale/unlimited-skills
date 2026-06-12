# Feedback guide

Unlimited Skills sends **no telemetry**. There is no auto-upload, no crash
reporter, no usage ping: search, suggestion, indexing, and the MCP savings
measurement all run on your machine, and the learning logs are local files
under your library's `.learning/` directory. The project only learns what
you choose to tell it — feedback is manual and voluntary, through GitHub
issues.

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
