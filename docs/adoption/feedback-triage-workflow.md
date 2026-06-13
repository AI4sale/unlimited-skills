# Feedback triage workflow

This workflow keeps early public-alpha feedback actionable within 24-48 hours
without collecting telemetry. It applies to reports created from:

- first-value feedback;
- install friction;
- skill not invoked / wrong suggestion;
- MCP savings report;
- marketplace/listing discovery feedback.

## Daily triage loop

1. Open new GitHub issues with any `feedback:*` label.
2. Confirm the report type label matches the template or contact link.
3. Confirm severity: `severity:p0-user-blocker`, `severity:p1-high-friction`,
   or `severity:p2-improvement`.
4. Add exactly one needs label when action is blocked:
   `needs:repro` or `needs:maintainer-review`.
5. Route the issue using
   [feedback-to-backlog-routing.md](feedback-to-backlog-routing.md).
6. Leave a short maintainer comment naming the outcome and next owner action.
7. Revisit P0/P1 issues within 24-48 hours until routed or closed.

## Severity definitions

### P0 user blocker

Use `severity:p0-user-blocker` when a clean user cannot install, cannot run
quickstart, cannot reach any useful result, or reports a privacy/security
claim involving automatic collection or upload.

Required action: reproduce or disprove the blocker the same day. If reproduced,
prepare a corrective release or public workaround.

### P1 high friction

Use `severity:p1-high-friction` when the user can continue only with maintainer
help, a manual workaround, unclear docs, or a non-obvious command.

Required action: route within 24-48 hours to install, docs, retrieval, MCP, or
listing backlog.

### P2 improvement

Use `severity:p2-improvement` for useful feedback that does not block first
value: wording issues, benchmark clarification, listing polish, rough edges,
or successful first-value reports.

Required action: batch into the next adoption/docs pass or close with a clear
answer.

## Type-specific routing

### First-value feedback

Classify the report as:

- first value reached under 5 minutes;
- first value reached after friction;
- first value not reached.

Delayed or missed first value feeds quickstart docs, install path docs, or code
smoke tests.

### Install friction

Add `needs:repro` until the exact failing step can be reproduced or explained.
Reproduced install friction feeds quickstart/package smoke, installer tests, or
install docs.

### Skill invocation failure

A valid skill-invocation miss feeds the frozen eval set before ranking changes.
Do not tune retrieval from one anecdote unless the eval gate stays green.

### MCP savings report

MCP savings reports should contain names, counts, sizes, token estimates, and
status strings only. If the report shows confusion, update the MCP docs or
feedback guide before changing measurement code.

### Marketplace/listing discovery feedback

Marketplace feedback feeds the submission tracker and listing copy. Re-check
copy before changing it: no paid CTA, no hosted/team/enterprise readiness
claim, no payment link, and no delivery promise.

## Privacy rule

Never ask users to paste prompts, tool inputs, tool outputs, raw MCP
configuration, commands with secrets, environment values, tokens, private keys,
or unredacted local paths. Prefer `unlimited-skills feedback prepare` output.
