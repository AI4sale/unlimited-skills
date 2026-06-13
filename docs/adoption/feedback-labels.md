# Public-alpha feedback labels

Use these labels for v0.5 public-alpha feedback. The goal is to make every
manual report actionable within 24-48 hours without adding telemetry.

Machine-readable source: [`.github/labels.yml`](../../.github/labels.yml).
Verify it with:

```bash
python scripts/verify-feedback-labels.py
```

If maintainers decide to sync labels to GitHub, use the dry-run-first helper:

```bash
python scripts/sync-github-labels.py --dry-run
```

The sync helper must not mutate GitHub labels unless `--apply` is passed
explicitly.

## Feedback type labels

| Label | Applies to | Default owner action |
| --- | --- | --- |
| `feedback:first-value` | Quickstart or first five minutes worked, stalled, or failed | Classify as reached, delayed, or missed first value |
| `feedback:install-friction` | Install, setup, package, shell, plugin, or agent installer friction | Reproduce on a clean environment and route to docs/tests or code fix |
| `feedback:skill-invocation` | `suggest`, retrieval, skill card, or wrong/no skill behavior | Check against the frozen eval set and create an eval candidate when valid |
| `feedback:mcp-savings` | `unlimited-skills mcp savings` reports or measurement confusion | Compare names/counts/sizes output with the lab benchmark and docs |
| `feedback:docs` | Documentation confusion that does not require code changes | Patch the nearest public doc and add a regression check when possible |
| `feedback:marketplace` | Marketplace/listing discovery, review, wording, or submission feedback | Re-check listing copy and submission tracker before changing public claims |

## Severity labels

| Label | Definition | Response target |
| --- | --- | --- |
| `severity:p0-user-blocker` | A clean user cannot install, start quickstart, or avoid a privacy/security breach | Same day triage; corrective release if reproduced |
| `severity:p1-high-friction` | A user can continue only with maintainer help, manual workaround, or unclear docs | 24-48 hour triage; docs or code fix assigned |
| `severity:p2-improvement` | Useful report, rough edge, wording fix, benchmark clarification, or enhancement | Batch into the next adoption/docs pass |

## Needs labels

| Label | Meaning | Next action |
| --- | --- | --- |
| `needs:repro` | Maintainer needs a clean reproduction before changing code | Ask for redacted command/output or reproduce locally |
| `needs:maintainer-review` | Report is clear enough to review, classify, and route | Assign owner and convert to backlog item or close with explanation |

## Template defaults

| Template | Required labels |
| --- | --- |
| First-value feedback | `feedback:first-value`, `severity:p2-improvement`, `needs:maintainer-review` |
| Install friction | `feedback:install-friction`, `severity:p1-high-friction`, `needs:repro` |
| Skill not invoked / wrong suggestion | `feedback:skill-invocation`, `severity:p1-high-friction`, `needs:maintainer-review` |
| MCP savings report | `feedback:mcp-savings`, `severity:p2-improvement`, `needs:maintainer-review` |
| Marketplace/listing discovery feedback | `feedback:marketplace`, `severity:p2-improvement`, `needs:maintainer-review` |

## Escalation rule

Escalate any issue to `severity:p0-user-blocker` when it shows a reproduced
install blocker, a reproduced first-value blocker on a clean environment, or a
privacy/security claim involving telemetry, automatic upload, tracking,
analytics, prompt collection, tool input collection, or tool output collection.

Do not use labels to imply support, paid delivery, hosted readiness, or sales
commitments. Labels describe triage only.
