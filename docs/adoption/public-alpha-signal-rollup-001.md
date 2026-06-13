# Public-Alpha Signal Rollup 001

Date checked: 2026-06-13

Scope: first manual signal rollup after `v0.5.1-alpha` publication.

This rollup uses only public aggregate metadata and manual report surfaces. It
uses no telemetry, no tracking pixels, no analytics SDKs, no hidden
identifiers, no private user data, no prompt collection, no tool input
collection, no tool output collection, and no hosted query forwarding.

Privacy checklist: no telemetry; no tracking pixels; no analytics SDK; no
private user data; no prompt collection; no tool input collection; no tool
output collection; no hosted query forwarding.

## Rollup Summary

Decision: `continue_with_low_signal`

The public-alpha distribution path is visible: PyPI exposes
`unlimited-skills==0.5.1`, GitHub has the `v0.5.1-alpha` prerelease, and the
public repository is discoverable. Manual first-value signal is not available
yet: no public GitHub issues or submitted feedback reports were visible during
this check. Treat this as `low_signal` and `no_feedback_yet`, not as success or
failure.

## Data Sources Checked

| source | evidence | result | privacy boundary |
| --- | --- | --- | --- |
| PyPI project JSON | https://pypi.org/pypi/unlimited-skills/json | latest version `0.5.1`; visible releases `0.5.0`, `0.5.1` | Public package metadata only |
| PyPI project page | https://pypi.org/project/unlimited-skills/ | package is available as `unlimited-skills` | Public package metadata only |
| GitHub release | https://github.com/AI4sale/unlimited-skills/releases/tag/v0.5.1-alpha | prerelease `v0.5.1-alpha - adoption tools`, published 2026-06-13T04:05:42Z | Public release metadata only |
| GitHub repository counters | https://github.com/AI4sale/unlimited-skills | 5 stars, 0 forks, public repository | Public repository metadata only |
| GitHub issues | `gh issue list --state all --limit 100` | no issues returned | Public issue tracker only |
| GitHub open PRs | `gh pr list --state open` | only parked PR #119 is open | Public PR metadata only |
| Marketplace submission tracker | `docs/adoption/marketplace-submission-tracker.md` | all tracked surfaces remain `not_submitted` | Maintainer-authored public tracker only |
| LinkedIn launch signal | owner-provided public post metrics/comments | not provided for this rollup | Omitted until owner provides public aggregate signal |

PyPI download counts were not checked in this PR because the PyPI JSON endpoint
does not expose package download counts. Add aggregate download statistics later
only from an owner-approved public or aggregate source.

## Installation/Discovery Signals

| signal | status | note |
| --- | --- | --- |
| PyPI availability | present | `unlimited-skills==0.5.1` is visible on PyPI. |
| GitHub release availability | present | `v0.5.1-alpha` prerelease exists. |
| GitHub stars | present | 5 stars at the time of this check. |
| GitHub forks | none_visible | 0 forks at the time of this check. |
| GitHub issues | no_feedback_yet | No public issues returned. |
| Marketplace/listing visibility | not_submitted | External submissions are blocked pending owner action and evidence. |

These are directional distribution signals only. They do not prove successful
installation or first value.

## First-Value Signals

No first-value feedback report was visible during this check.

Expected report surfaces:

- `first-value-feedback` issue template;
- `install-friction` issue template;
- `skill-not-invoked` issue template;
- `mcp-savings-report` issue template;
- public comments that explicitly describe a successful or failed install.

Current status: `no_feedback_yet`.

## Feedback/Issues

GitHub issues returned no public reports. There are currently no visible
first-value, install-friction, skill-not-invoked, MCP-savings, privacy, or
security reports to triage.

This does not imply that users succeeded. It only means no public manual report
was visible in the checked sources.

## Marketplace/Listing Status

All tracked discovery surfaces remain `not_submitted`:

- Claude Code plugin marketplace;
- MCP Registry / discovery;
- GitHub repository discovery.

A3.4 actual submission evidence remains `blocked_pending_owner_approval`.
Do not submit or claim acceptance until the owner approves the exact
destinations, submission owner, listing copy, and whether Codex may submit or
only prepare evidence.

## Social/LinkedIn Launch Signal

No owner-provided LinkedIn launch metrics, replies, or comments were available
for this rollup. The social signal is intentionally omitted rather than
inferred.

## Signal Quality Assessment

Quality: `low_signal`

The checked public distribution surfaces prove that the release can be found,
but they do not prove install completion, useful retrieval, or first value.
Manual first-value evidence is still missing. The next useful action is to
collect a small number of explicit manual reports, not to add telemetry.

## Blockers

| blocker | owner | action | fallback |
| --- | --- | --- | --- |
| No manual first-value reports yet | Release owner | Ask for three redacted first-value or install-friction reports using the public issue templates. | Keep the rollup as `no_feedback_yet` and do not claim adoption success. |
| A3.4 marketplace submission evidence is blocked | Project owner | Approve exact destinations, submission owner, listing copy, and Codex submission permission. | Keep all marketplace rows `not_submitted` and avoid acceptance claims. |
| PyPI download count is not available from checked PyPI JSON | Release owner | Add an owner-approved aggregate download source if needed. | Use only package availability/version as directional evidence. |
| LinkedIn launch signal was not provided | Project owner | Provide public aggregate post metrics or relevant public comments. | Omit social signal from this rollup. |

## Next Actions

| area | next action | owner |
| --- | --- | --- |
| Adoption | Ask 3-5 known alpha users to run the PyPI quickstart and file redacted public feedback. | Release owner |
| Docs | Link this rollup from adoption docs so future checks have a baseline. | Maintainers |
| Support | If any install-friction issue appears, reproduce it on a clean shell before changing code. | Install owner |
| Feedback triage | Label new reports within 24-48 hours using the public-alpha feedback workflow. | Maintainers |
| Marketplace/listing | Keep A3.4 blocked until owner approval exists; do not submit from this rollup. | Project owner |

## Non-Goals and Claim Guard

This rollup does not add analytics, telemetry, tracking pixels, automatic
diagnostic upload, hosted query forwarding, paid outreach, payment links,
marketplace submission, hosted/team/enterprise readiness claims, product
readiness claims, or external acceptance claims.
