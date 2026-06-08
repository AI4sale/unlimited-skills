# Local Skill Hub

Local Skill Hub is a registered local/LAN service for shared skill storage and retrieval across many agent instances.

It exists because 10, 100, or 1,000 agent runtimes should not each maintain separate skill libraries, indexes, and update state. A registered hub centralizes retrieval/storage locally, while each client still decides whether it can use a selected skill.

## Product Boundary

- Existing `unlimited-skills serve` remains the free MIT local daemon and does not require registration.
- New `unlimited-skills hub serve` is the registered Local Skill Hub and requires registration.
- Local CLI commands such as `search`, `list`, `view`, `reindex`, `adapt`, and `serve` continue to work offline without registration.

Registered users can use Local Skill Hub for free up to 100 active client instances. An active client instance is a registered agent/runtime client that contacted the hub within the last 30 days.

## Catalog Readiness

The private registry audit scanned 315 skills and returned `YES_WITH_ALLOWLIST`.

That verdict means Local Skill Hub must use allowlist-only distribution. Full catalog distribution is disabled. The hub may distribute only skills that the private registry allowlist marks as hub-safe.

## Architecture

```text
hosted registry -> registered local hub -> agent clients
```

The hosted registry provides approved catalog metadata and allowlisted collection updates to registered hubs. The local hub stores and retrieves skills for local/LAN clients. Agent clients request relevant skill metadata or selected skill bodies from the hub.

The hub does not execute skills. It does not run downloaded scripts. Tool, platform, OS-specific, and package requirements remain client-side and must be verified by the client before use.

Local search queries are not sent to the hosted registry by default. Hosted registry calls are for registration, allowlisted catalog/update metadata, and explicitly requested hosted actions.
