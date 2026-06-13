# Feedback to backlog routing

Public-alpha feedback is only useful when it becomes a concrete backlog item.
This routing table defines the first owner action for each report type.

| Report type | Backlog destination | Owner action | Regression hook |
| --- | --- | --- | --- |
| First-value reached under 5 minutes | Adoption notes | Record the useful path and preserve it in docs | Public-alpha docs tests if wording changes |
| First-value delayed or missed | Quickstart backlog | Identify the exact stalled step | Quickstart or install-path smoke |
| Install friction | Install/package backlog | Reproduce on Windows, macOS, or Linux as reported | quickstart/package smoke, `tests/test_install_path_docs.py`, or installer test |
| Skill not invoked / wrong suggestion | Retrieval backlog | Convert valid miss into a frozen eval candidate | `scripts/check-skill-effectiveness.py` and eval fixture update |
| MCP savings report | MCP measurement backlog | Compare names/counts/sizes with docs and lab benchmark | MCP boundary verifier or focused MCP test |
| Docs confusion | Docs backlog | Patch the nearest doc and add a wording guard if repeated | `tests/test_public_alpha_docs.py` |
| Marketplace/listing feedback | Listing backlog | Re-check submission tracker, launch pack, and copy before changing claims | Marketplace listing verifier |

## Routing rules

- A report becomes backlog only after the owner can state a specific next
  action.
- If a user supplied only broad frustration, ask one follow-up for the exact
  command, step, or expected skill. Do not ask for prompts, tool inputs, tool
  outputs, raw MCP configuration, tokens, or private paths.
- If the report is a retrieval miss, prefer adding an eval candidate before
  changing ranking. Ranking changes must keep the frozen effectiveness gate
  green.
- If the report is install friction, prefer a clean-environment reproduction
  before changing install code. Docs hotfixes can ship first when wording is
  clearly wrong.
- If the report is marketplace/listing feedback, re-check for prohibited
  claims before updating copy: no paid CTA, no hosted/team/enterprise readiness
  claim, no payment link, and no delivery promise.

## Closure outcomes

Close or route every report with one of these outcomes:

- `backlog:code-fix`
- `backlog:docs-fix`
- `backlog:eval-candidate`
- `backlog:listing-copy`
- `backlog:benchmark-docs`
- `answered:no-change`
- `blocked:needs-repro`

The issue comment should name the outcome and the next owner action. It should
not promise delivery dates, hosted services, paid plans, or enterprise support.

The closure outcome labels above are included in `.github/labels.yml` so the
label verifier can keep docs, issue templates, and triage operations aligned.
