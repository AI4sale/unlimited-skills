# Enterprise Trust Stack Status

Purpose: describe the existing trust/governance work without turning it into
the active public-alpha roadmap.

## Current Status

The trust stack exists as background infrastructure. It is not deleted, but it
is not the active adoption priority after `v0.5.1-alpha`.

Existing areas include:

- MCP profile policy;
- signed MCP profile bundles;
- managed trust store;
- rollout planning and policy doctor;
- audit replay and policy impact simulation;
- incident drills;
- local and managed policy surfaces;
- E19 MCP profile bundle publisher and signing ceremony work in PR #119.

## Moratorium

No new E28+ hosted/team/trust implementation may start unless at least one of
these is true:

- real user feedback demands it;
- a team or customer asks for it;
- adoption data shows trust is blocking use;
- the owner explicitly reopens the Enterprise track.

## #119 Status

PR #119 remains background. It should not be merged into the active adoption
lane unless the adoption queue is clean or the owner explicitly reopens it.

The current adoption queue includes:

- A3.4 actual submission evidence pack, blocked pending owner approval;
- A5.1 roadmap reset and trust-layer moratorium;
- A4.4 first public-alpha signal rollup.

## Claim Boundary

This status page is not a readiness claim.

Do not use it to imply:

- hosted availability;
- team readiness;
- Enterprise readiness;
- paid plan availability;
- payment path availability;
- sales commitment;
- delivery promise.

Existing trust-layer docs can describe implemented mechanics and verification
gates, but public alpha positioning must stay focused on local-first adoption.
