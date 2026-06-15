# O064-13 — Money Saved Meter: Cross-Tier Release Matrix

**Roadmap ref:** `...#v0.6.4`. **Status:** release-facing matrix (no code). **Blocked:**
BUILD until **US-063-005 GO**.

> **Numbering reconciliation (Hermes turn-16 summary vs turn-13 assignment):** the
> turn-13 detailed assignment numbered this batch O064-08..14; the turn-16 summary
> inserted a distinct **"Cross-tier release matrix"** as O064-13 and renumbered the
> later two. This file is that cross-tier release matrix. The other two already
> shipped in PR #182 as `o064-money-saved-meter-prebuild-safety-gates.md` (privacy/
> safety ship gates — turn-16 O064-14) and `money-saved-meter-codex-build-handoff.md`
> (Codex build handoff — turn-16 O064-15). One canonical set, no work dropped.

## Purpose
A single release-owner view: per tier, what is **live** in v0.6.4, the **allowed**
public claim, the **release-note-safe** line, and what is explicitly **not live**.
Consolidates O064-07 (claim authorization) + O064-08..12 (tier contracts) + O064-03
(tier bonuses) into one table the release gate can sign off against.

## Release matrix

| Tier | Live in v0.6.4 | Allowed public claim | Release-note-safe line | NOT live (v0.6.4) |
| --- | --- | --- | --- | --- |
| **Free / Community Core** | **Yes — live local meter** | local periodic estimate of MCP **schema** context avoided; bytes measured, tokens estimated, dollars off | "Local periodic estimate of context avoided." | hosted dashboard, telemetry, automatic dollars |
| **Registered** | local export artifact only | "local export, future-compatible" | "Local export, future-compatible; no upload in v0.6.4." | hosted submission/sync |
| **Team** | local summary artifact only | "local team summary" | "Local team summary; no dashboard, no upload." | dashboard, hosted audit, SLA, auto-sync |
| **Business** | local admin export only | "local export a future dashboard could import" | "Local export a future dashboard could import." | Business dashboard, hosted audit log, entitlement, billing |
| **Enterprise** | local evidence pack only | "local audit-safe savings evidence" | "Local audit-safe savings evidence; no hosted features." | SSO/SCIM, on-prem license, hosted compliance portal, billing |

## Cross-tier invariants (apply to every row)
1. **Local-only:** no network, no telemetry, no upload, no account in v0.6.4.
2. **Estimate honesty:** bytes **measured**, tokens **estimated** (`bytes // 4`),
   dollars **off by default** (local rate only, labeled estimated).
3. **Cadence not billing:** the 100-call window is a usage cadence, never summed into
   a per-call billing figure.
4. **Privacy fail-closed:** `assert_meter_safe` before any write/emit; **suppress,
   don't redact**; no server names in passive surfaces; no prompts/paths/keys/skill
   bodies.
5. **Only Free Core is a live runtime feature.** Registered/Team/Business/Enterprise
   ship **bounded local artifacts** that are future-compatible — they must **not**
   imply a live hosted/billing capability exists now.

## Forbidden across all tiers (from O064-07 X1–X8)
Exact/guaranteed dollars; exact token counts; "skill/skill-body context saved";
summed per-window billing; "we tracked/measured your usage"/dashboard/analytics;
uploaded/synced framing; server names in passive surfaces; comparative market-price
savings.

## Release gate sign-off (must all hold)
- US-063-005 = GO.
- Every shipped public line is drawn from the "Release-note-safe line" column.
- No row claims a live hosted/paid feature except the Free local meter (fully live).
- Privacy/safety Gates A–E (O064-14 safety-gate spec) green; acceptance required-set
  green; v0.6 frozen-contract + boundary verifiers green.

---

### Evidence summary
- **One release-owner table:** per tier — live surface, allowed claim, release-note
  line, not-live.
- **5 cross-tier invariants** + the X1–X8 forbidden set.
- **Reconciles** the turn-13/turn-16 numbering into one canonical batch (no task
  dropped).
