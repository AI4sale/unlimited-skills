# Marketplace and listing launch pack

Purpose: give the release owner a ready-to-submit, rule-checked launch pack for
the v0.5 public alpha adoption lane.

This is a preparation artifact, not proof that any marketplace accepted the
project. Re-check every linked submission surface immediately before sending,
because marketplace rules can change.

Track submission status in
[marketplace-submission-tracker.md](marketplace-submission-tracker.md). Use
[marketplace-submission-runbook.md](marketplace-submission-runbook.md) and
[submission-owner-approval-packet.md](submission-owner-approval-packet.md)
before any owner sends listing copy to a marketplace, registry, directory, or
discovery surface. The approval packet must name the exact destination, exact
listing copy reference, submitter, evidence requirements, blocked-claims
acknowledgment, fallback, and `permission_to_submit: yes`.

## Current source check

Checked on 2026-06-12:

- Claude Code plugin docs: plugins are shared through marketplaces; community
  submissions use the Claude or Console submission forms; run
  `claude plugin validate` before submission; approved community plugins are
  pinned to a commit SHA and the public catalog can lag behind approval.
  Source: <https://code.claude.com/docs/en/plugins>
- Claude Code marketplace docs: marketplaces are added with
  `claude plugin marketplace add <source>`; marketplace validation checks
  `.claude-plugin/marketplace.json`, duplicate names, path traversal, and
  version mismatches against referenced plugin manifests.
  Source: <https://code.claude.com/docs/en/plugin-marketplaces>
- MCP Registry docs: the registry hosts metadata pointing to publicly
  installable packages or public remote servers; it does not support
  private-only servers. Source:
  <https://modelcontextprotocol.io/registry/about>
- Official MCP Registry surface: <https://registry.modelcontextprotocol.io/>

## Submission targets

### Claude Code community plugin marketplace

Readiness state: ready to submit after the release owner validates the plugin
locally with the current Claude Code CLI.

Required local checks before submission:

```bash
claude plugin validate .
claude plugin marketplace add ./ --scope local
/plugin install unlimited-skills@unlimited-skills
```

Submit through the current Claude plugin submission form documented by
Anthropic. If submitting from an individual account, use the Console form; if
submitting from a Team or Enterprise organization, use the claude.ai directory
submission form with owner/directory-management access.

### MCP discovery surfaces

Readiness state: prepare listing copy now; submit only where the surface accepts
Python/PyPI or local CLI gateway packages.

The current MCP Registry rule is important: it accepts metadata for publicly
installable packages or public remote servers, not private-only servers.
Unlimited Skills is public on PyPI, but the Unlimited Tools gateway is a local
CLI gateway, not a hosted remote server. The submission text must describe it
as a local MCP gateway and must not imply a hosted MCP service.

### GitHub repository discovery

Readiness state: repository copy is good enough for discovery. Keep topics and
README language aligned with the actual public alpha:

- local-first
- Claude Code
- MCP
- skill retrieval
- no telemetry
- free public alpha
- MIT core

Do not add payment, hosted-team, or enterprise-readiness wording to discovery
copy.

## Listing copy

Use [marketplace-listing-copy.md](marketplace-listing-copy.md) as the source
for paste-ready listing fields.

Minimum install block for listing pages:

```bash
pip install unlimited-skills
unlimited-skills quickstart
unlimited-skills mcp install --claude-code --dry-run
unlimited-skills mcp install --claude-code
```

Claude Code plugin install block:

```text
/plugin marketplace add AI4sale/unlimited-skills
/plugin install unlimited-skills@unlimited-skills
```

Recommended proof block:

```bash
unlimited-skills mcp install status
unlimited-skills mcp savings
```

## Claim guard

Allowed claims:

- free public alpha;
- local-first;
- no telemetry by default;
- CLI and plugin are MIT core;
- bundled ECC and Superpowers packs are included in the v0.5 wheel;
- MCP savings are measured locally from the user's real Claude Code config;
- lab benchmark: 40 realistic tools, 90,420 bytes full schema dump versus
  1,268 bytes standing cost behind the 3 meta-tools;
- skill effectiveness claims must point to the frozen evaluation result, not
  to a broad universal guarantee.

Blocked claims:

- paid plan CTA;
- payment link;
- checkout link;
- hosted/team availability;
- enterprise-ready;
- production hosted gateway;
- guaranteed marketplace acceptance;
- automatic telemetry;
- automatic upload;
- uploading prompts, skill bodies, source code, local paths, env values,
  tokens, or tool inputs/outputs.

## Submission checklist

Before submission:

- [ ] The target row exists in
      `docs/adoption/marketplace-submission-tracker.md`.
- [ ] The exact destination has a completed owner approval packet in
      `docs/adoption/submission-owner-approval-packet.md`.
- [ ] The packet has explicit `submitter`, `permission_to_submit: yes`,
      `exact_listing_copy_reference`, evidence requirements,
      blocked-claims acknowledgment, and fallback.
- [ ] Current rules for that surface were re-checked on the submission day.
- [ ] The tracker has owner, status, blocker, next action, and evidence fields.
- [ ] `pip install unlimited-skills` works from a clean environment.
- [ ] `unlimited-skills quickstart` works and imports bundled packs when the
      library is empty.
- [ ] `unlimited-skills mcp install --claude-code --dry-run` shows a redacted
      diff and does not write `.mcp.json`.
- [ ] `unlimited-skills mcp install --claude-code` registers the gateway.
- [ ] `unlimited-skills mcp install status` reports configured state.
- [ ] `unlimited-skills mcp uninstall --claude-code` removes only
      `unlimited-tools`.
- [ ] `claude plugin validate .` passes with the current Claude Code CLI.
- [ ] Listing copy has no paid, hosted, team, enterprise-ready, or telemetry
      claims.
- [ ] Listing copy includes GitHub issues as the support channel.
- [ ] Listing copy points limitations to
      `docs/releases/v0.5.0-alpha-known-issues.md`.
- [ ] No tracker row claims accepted/submitted status without evidence.

## Evidence to attach or keep ready

- PyPI package URL: <https://pypi.org/project/unlimited-skills/0.5.1/>
- GitHub release URL:
  <https://github.com/AI4sale/unlimited-skills/releases/tag/v0.5.1-alpha>
- Source repository: <https://github.com/AI4sale/unlimited-skills>
- A3.1 Claude Code MCP installer merge: PR #133.
- Public alpha release workflow evidence: GitHub Actions run for v0.5.0-alpha.
- Fresh install smoke evidence from the release process.

## Owner note

This pack intentionally avoids sales language. The next growth step is user
adoption and first-value feedback, not paid conversion.
