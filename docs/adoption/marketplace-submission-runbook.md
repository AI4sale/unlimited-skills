# Marketplace Submission Runbook

Purpose: give the release owner a repeatable procedure for submitting
Unlimited Skills to public-alpha discovery surfaces without overstating the
product state.

This runbook does not authorize submission by itself. It requires owner action
and a fresh rule check immediately before sending anything.

## Standard Procedure

1. Pick one row from
   [marketplace-submission-tracker.md](marketplace-submission-tracker.md).
2. Open the current submission URL or current official docs for that surface.
3. Re-check rules for package type, plugin format, metadata, support channel,
   license, privacy wording, and prohibited claims.
4. Run the local checks required by the launch pack.
5. Compare the paste-ready copy against the claim guard.
6. Submit only if the surface still accepts this type of listing.
7. Update the tracker with status, date, owner, blocker, next action, and
   evidence link.
8. If blocked or rejected, keep the row and record the reason.

## Surface Checks

### Claude Code plugin marketplace

Before submission:

```bash
claude plugin validate .
claude plugin marketplace add ./ --scope local
/plugin install unlimited-skills@unlimited-skills
```

Submission must use the current Anthropic-owned submission path. If the
current docs require a Console form or an organization directory-management
role, record that as the owner action in the tracker.

### MCP discovery or registry surfaces

Before submission, verify that the current registry rules accept a public PyPI
package that provides a local MCP gateway. If the surface only accepts hosted
remote MCP servers, mark the row `blocked` and state that Unlimited Skills is
a local CLI gateway, not a hosted server.

### GitHub discovery

GitHub discovery is repository hygiene, not third-party acceptance. Use it for
topics, release links, README wording, and issue-template routing. Do not mark
GitHub discovery as `accepted` unless a specific GitHub surface or directory
actually accepted the listing.

## Evidence Requirements

Valid evidence can be:

- marketplace submission URL;
- GitHub issue, PR, release, or discussion link;
- PyPI release URL;
- screenshot reference stored outside the public repo when it contains account
  data;
- rejection email summary with sensitive data removed;
- dated owner note that a surface is blocked by current rules.

Do not commit private account screenshots, email addresses, tokens, payment
data, unpublished submission forms, or private review messages to the public
repo.

## Copy Guard

Every submission must preserve these boundaries:

- no paid CTA;
- no payment link;
- no hosted/team/enterprise readiness claim;
- no guaranteed acceptance claim;
- no delivery promise;
- no telemetry claim beyond the product's actual no-telemetry behavior;
- no upload claim beyond explicit manual feedback paths.

If a surface requires a promise that violates these boundaries, mark it
`blocked`.

## Completion Definition

A submission task is complete only when the tracker row has:

- a valid status;
- a current `date_checked`;
- a concrete `submission_owner`;
- a next action;
- an evidence link or explicit `none`;
- a blocker value, even when it is `none`.
