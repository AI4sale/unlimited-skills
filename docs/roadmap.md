# Roadmap

Current strategy: public-alpha adoption first. New hosted, team, Enterprise,
or trust-layer implementation must wait until real demand evidence shows that
trust is blocking use.

## Active Priority

The active product lane after `v0.5.1-alpha` is adoption and first value:

- help users discover the PyPI package and GitHub release;
- prove clean install, quickstart, and Claude Code MCP setup from the public
  package;
- collect voluntary feedback through GitHub issue templates;
- route feedback into backlog decisions within 24-48 hours;
- track marketplace/listing submissions with owner-approved evidence;
- publish manual public-alpha signal rollups.

See [adoption-roadmap.md](adoption-roadmap.md).

## Moratorium: Hosted, Team, and Trust-Layer Expansion

No new E28+ hosted/team/trust implementation may start unless at least one of
these is true:

- real user feedback demands it;
- a team or customer asks for it;
- adoption data shows trust is blocking use;
- the owner explicitly reopens the Enterprise track.

This moratorium does not delete the existing trust stack. It keeps existing
MCP profile, signing, trust-store, audit, replay, rollout, and policy work
available as background infrastructure while the public alpha learns whether
users can install and reach first value.

PR #119 / E19 remains background unless the adoption queue is clean or the
owner explicitly reopens it.

See [enterprise-trust-stack-status.md](enterprise-trust-stack-status.md).

## Evidence Map

- `docs/roadmap.md`: top-level adoption-first roadmap and moratorium.
- `docs/adoption-roadmap.md`: active adoption queue and feedback routing.
- `docs/enterprise-trust-stack-status.md`: existing trust stack status and
  #119 background rule.
- `docs/product-strategy.md`: product strategy and current non-goals.
- `.github/ISSUE_TEMPLATE/trust-layer-proposal.yml`: evidence-gated proposal
  path for reopening hosted, team, Enterprise, or trust-layer work.

## Blocked Until Owner Approval

A3.4 actual submission evidence pack is
`blocked_pending_owner_approval`.

Owner action required before Codex submits to external marketplaces,
registries, directories, or claims submission evidence:

- approve exact destinations;
- approve exact submission owner;
- approve exact listing copy;
- approve whether Codex may submit or only prepare evidence.

## Implemented Local Core

- Recursive `SKILL.md` discovery.
- Lexical index and search.
- Chroma-compatible vector index and sidecar vector search.
- Hybrid lexical + vector retrieval.
- Privacy-safe `suggest` probe and frozen effectiveness gate.
- Codex router skill.
- Claude Code plugin and MCP installer path.
- Agent-driven one-skill adaptation workflow.
- Usage and feedback logging.
- Local-only `feedback prepare` reports.
- Basic skill drafting command.
- Safe dry-run migration scripts.
- Windows, macOS, and Linux installer/migration scripts.
- Codex installer with router and managed `AGENTS.md` patch.
- OpenClaw installer for workspace/plugin/built-in skill roots.
- Hermes context-reduction installer with rollback manifest.
- Native skill sync for Codex, Claude Code, Hermes, and OpenClaw roots.
- Registered hosted update client with SHA256-verified collection archives.
- Registered team create/join/pending/approve/sync MVP.
- Public repo self-update from GitHub releases or tags.
- Local MCP gateway, savings measurement, profile policy work, signed-bundle
  verification, trust store, replay, rollout, and incident drills.

## Background Work

These areas remain valid, but are not the active adoption lane:

- broader host adapters for the local warm-daemon lifecycle now used by the
  Claude Code prompt hook;
- learning-loop improvements that aggregate accepted/rejected matches;
- broader adapter support for more agent harnesses;
- hosted registry hardening;
- private encrypted team-pack publishing;
- Enterprise Skill Lock refinements;
- E19 MCP profile bundle publisher and signing ceremony (#119).

Background work can resume only when it does not displace adoption tasks, or
when owner approval explicitly changes the priority.
