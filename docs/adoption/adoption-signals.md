# Adoption signals

This file is the source-of-truth vocabulary for public-alpha adoption
signals. It exists so release notes, issue triage, and launch reviews use the
same words.

## Signal classes

### Directional distribution signals

Directional signals show whether people can find the project. They are useful
for launch health, but they do not prove successful usage.

- PyPI package installs.
- GitHub stars.
- GitHub forks.
- GitHub watchers.
- Marketplace or listing visibility.
- Public launch-post replies and comments.

### Manual first-value signals

Manual first-value signals show whether a person reached a useful result.
They are higher quality than distribution counters because the user chose to
explain what happened.

- First-value feedback issue.
- Install-friction issue.
- Skill-not-invoked or wrong-suggestion issue.
- MCP savings report.
- Public comment describing a successful or failed install.

### Safety signals

Safety signals protect the public-alpha boundary.

- Security report.
- Privacy report.
- Issue claiming telemetry, automatic upload, tracking, analytics SDK usage,
  prompt collection, tool input collection, or tool output collection.
- Marketplace rejection caused by unclear safety or privacy wording.

## What counts as first value

A user reached first value when they intentionally ran Unlimited Skills and
got one of these outcomes:

- a useful `suggest` result;
- a useful `search`, `view`, or `where` result;
- successful quickstart import and first search;
- a useful MCP savings estimate;
- a useful feedback report generated locally;
- a clear decision that no matching skill exists.

The final case matters: a clean, quiet "no relevant skill" result can still be
first value when it prevents a wrong skill from being injected.

## What does not count

Do not count these as first value:

- a package install with no run;
- a star or fork with no report;
- a failed install that was never reproduced or explained;
- a social like with no install attempt;
- any private assumption about hidden usage.

## Privacy rules

Adoption measurement must stay manual and public:

- no telemetry;
- no auto-upload;
- no tracking pixels;
- no analytics SDK;
- no prompt collection;
- no tool input collection;
- no tool output collection;
- no hidden per-user identifier;
- no hosted query forwarding.

Reports may include only what the user chooses to paste. Maintainers should
ask for redacted `feedback prepare` output instead of raw logs.

## Weekly rollup format

The first dated rollup is
[`public-alpha-signal-rollup-001.md`](public-alpha-signal-rollup-001.md). It
records a `low_signal` / `no_feedback_yet` baseline after `v0.5.1-alpha`:
PyPI and GitHub release discovery are live, but no manual first-value reports
were visible in the checked public sources.

Use this structure for the first-week summary:

```text
Window:
PyPI installs:
GitHub stars/forks/watchers:
Issues opened:
First-value reports:
Install-friction reports:
Skill-not-invoked reports:
MCP savings reports:
Marketplace/listing mentions:
LinkedIn replies/comments:
Repeated blockers:
Privacy/security incidents:
Decision:
Next action:
```

Decision must be one of:

- `continue`: first-value path is working;
- `docs-hotfix`: users are blocked or confused by instructions;
- `code-hotfix`: a reproducible product bug blocks first value;
- `pause-distribution`: privacy/security claim or listing rejection needs
  correction before broader launch.
