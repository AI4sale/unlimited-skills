# First-week adoption measurement

Unlimited Skills v0.5 public alpha measures first-week adoption with **no
telemetry**. There is no tracking pixel, analytics SDK, auto-upload, prompt
collection, tool input collection, or tool output collection. Every user-level
signal in this plan is either public repository metadata, public social
response, or a report a user intentionally opens.

The measurement contract is **no telemetry**.

Explicitly forbidden in this launch:

- no telemetry;
- no auto-upload;
- no tracking pixels;
- no analytics SDK;
- no prompt collection;
- no tool input collection;
- no tool output collection.

## Scope

The first week starts when the v0.5 public alpha announcement is published and
ends seven calendar days later. The measurement window is intentionally short:
the goal is to learn whether a new user can install the package, reach first
value, and understand how to report friction before the project invests in
larger distribution.

## Signals

| Signal | Source | Owner | Action | Privacy boundary |
| --- | --- | --- | --- | --- |
| PyPI installs | PyPI project download statistics, used only as directional signal | Release owner | Snapshot daily and compare trend direction | Aggregate package-level count only |
| GitHub stars, forks, watchers | Public GitHub repository counters | Release owner | Snapshot daily | Public repository metadata |
| GitHub issues opened | Public issue tracker | Maintainers | Label and triage each business day | User-submitted public issue only |
| First-value feedback reports | `first-value-feedback` issue template | Maintainers | Classify first value reached, delayed, or missed | Manual user report only |
| Install-friction reports | `install-friction` issue template | Maintainers | Reproduce or route to install docs/tests | Manual user report only |
| Skill-not-invoked reports | `skill-not-invoked` issue template | Retrieval owner | Convert validated misses into eval candidates | Manual user report only |
| MCP savings reports | `mcp-savings-report` issue template | MCP owner | Compare against lab benchmark and docs | Manual names/counts/sizes report only |
| Marketplace/listing mentions | Marketplace review pages, listing comments, public links | Release owner | Track approval, rejection, wording confusion | Public listing surface only |
| LinkedIn replies/comments | Public replies/comments to launch posts | Release owner | Record recurring objections and install attempts | Public social comments only |

Do not infer private usage from silence. Silence means unknown, not success.

## Success thresholds

The first week is successful when all of these are true:

- At least 10 directional PyPI installs are visible by the end of the window.
- At least 5 public GitHub interest signals are visible across stars, forks,
  and watchers.
- At least 3 manual feedback artifacts arrive across first-value,
  install-friction, skill-not-invoked, or MCP-savings reports.
- At least 1 first-value report confirms a useful result within 5 minutes.
- No accepted P0/P1 security or privacy report shows telemetry, auto-upload,
  tracking pixel, analytics SDK, prompt capture, tool input capture, or tool
  output capture.

These are alpha thresholds, not business KPIs. They prove that distribution,
install, feedback, and safety loops are alive.

## Failure thresholds

Treat the launch as failing and start a corrective release when any of these
happens:

- Zero PyPI installs are visible after 48 hours.
- Zero manual feedback artifacts arrive by the end of the first week.
- Two or more independent users report the same install blocker.
- A first-value report shows "Never got a useful result" and the failure is
  reproducible on a clean environment.
- A privacy report shows automatic collection, upload, tracking, or analytics.
- Marketplace/listing review rejects the package because the install or
  privacy claim is unclear.

## Triage cadence

During the first week:

- Daily: snapshot PyPI, GitHub counters, open issue counts, listing status, and
  public launch-post replies.
- Every business day: triage new issues, assign labels, and identify the next
  owner action.
- Twice during the week: review first-value and install-friction reports
  together so docs and tests move in the same direction.
- End of week: publish a short public summary with numbers, what changed, what
  did not change, and the next corrective release plan.

## Rollup 001

The first manual snapshot is
[`public-alpha-signal-rollup-001.md`](public-alpha-signal-rollup-001.md).
It records a `low_signal` / `no_feedback_yet` baseline: PyPI exposes
`unlimited-skills==0.5.1`, the GitHub `v0.5.1-alpha` prerelease exists, and no
public feedback issues were visible during the check.

PyPI download counts are intentionally not inferred from PyPI JSON because that
endpoint does not expose download counts. Use only owner-approved aggregate
download sources for that field.

Future rollups should be generated with
`scripts/generate-public-alpha-signal-rollup.py` and reviewed before publishing.
The reproducible CI path is
`python scripts/generate-public-alpha-signal-rollup.py --fixture-mode --out /tmp/rollup.md`.
The live path is
`python scripts/generate-public-alpha-signal-rollup.py --out docs/adoption/public-alpha-signal-rollup-002.md`;
it uses public aggregate sources only and can include optional owner-provided
local aggregate social input with `--social-json`. Do not use the generator to
claim private usage, marketplace acceptance, hosted readiness, paid readiness,
or social engagement that the owner did not provide.

## Owner actions and fallback

| Condition | Owner | Action | Fallback if signal is low |
| --- | --- | --- | --- |
| Low PyPI installs | Release owner | Check package visibility, README install path, and announcement links | Publish one focused install post and ask known testers to try the PyPI path |
| Low feedback volume | Release owner | Make the GitHub issue templates easier to find from docs and posts | Ask for three manual first-value reports directly |
| Repeated install friction | Install owner | Reproduce on clean Windows, macOS, and Linux shells | Ship docs hotfix first, then code hotfix if needed |
| Repeated retrieval miss | Retrieval owner | Convert report into an eval candidate | Hold ranking changes until the frozen eval remains green |
| MCP savings confusion | MCP owner | Clarify what the command measures and what it excludes | Add a short example to `docs/feedback.md` |
| Marketplace wording confusion | Release owner | Update listing copy and docs references | Pause marketplace push until the copy is clear |

If all signals are low and no technical blocker is visible, the fallback is
not to add telemetry. The fallback is targeted manual outreach, clearer issue
templates, and a shorter first-value path.

## Non-goals

This plan does not add analytics, hosted query forwarding, hidden counters,
automatic diagnostic upload, per-user identifiers, prompt sampling, tool
payload sampling, or usage-based ranking updates.
