# Adoption Roadmap

Purpose: keep the post-`v0.5.1-alpha` roadmap focused on public-alpha adoption
and first value.

## Current Outcome

Users should be able to:

1. discover Unlimited Skills;
2. install `unlimited-skills==0.5.1` from PyPI;
3. run `unlimited-skills quickstart`;
4. run `unlimited-skills mcp install --claude-code --dry-run`;
5. optionally install the Claude Code MCP gateway;
6. report first-value, install-friction, skill-invocation, or MCP-savings
   feedback manually through GitHub.

## Active Adoption Queue

| Priority | Work | Status | Evidence |
| --- | --- | --- | --- |
| A4.3 | Public-alpha feedback triage workflow | merged | PR #139 |
| A3.3 | Marketplace/listing submission tracker | merged | PR #140 |
| A3.4 | Actual submission evidence pack | blocked_pending_owner_approval | Exact destinations and owner action are not approved yet. |
| A5.1 | Roadmap reset and trust-layer moratorium | in progress | This document. |
| A4.4 | First public-alpha signal rollup | next after A5.1 | Use manual aggregate sources only. |

## Feedback Routing

- First-value reports feed README, quickstart, listing copy, and install path
  improvements.
- Install friction reports feed package smoke, installer docs, and quickstart
  failure handling.
- Skill-not-invoked reports feed the frozen eval set and ranking work.
- MCP savings reports feed measured proof review, not sales claims.
- Marketplace/listing feedback feeds the submission tracker and listing copy.

## A3.4 Owner Gate

A3.4 is blocked until the owner approves exact destinations, exact submission
owner, exact listing copy, and whether Codex may submit externally or only
prepare evidence.

Codex must not submit to external marketplaces, registries, directories, or
claim submission evidence without that approval.

## Signal Rollup Rule

Signal rollups must use manual or aggregate sources only:

- PyPI package availability and version;
- GitHub release existence;
- GitHub issues and feedback reports;
- marketplace/listing submission status;
- LinkedIn launch post reactions/comments if available;
- first-value reports;
- install-friction reports;
- skill-not-invoked reports;
- MCP savings reports.

Do not add telemetry, tracking pixels, analytics SDKs, user-level behavior
collection, payment promises, hosted readiness claims, team readiness claims,
or sales promises to improve signal quality.
