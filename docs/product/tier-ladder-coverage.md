# Tier Ladder Coverage & Release Gate (v0.6.x)

**Status:** governance / product gate (no code). **Scope:** the v0.6.x line
(v0.6.3 → v0.6.13). **Owner directive:** *every v0.6.x release must ship a concrete,
documented bonus for **each** above-Free tier — Registered, Team, Business, Enterprise —
defined **before** the release goes out, not bolted on after.*

**Why this file exists.** The handoff's original failure mode was that almost all real
work landed in **Free core** while the paid/tier layer stayed *designed but inert*. We
fixed that **per release** for v0.6.3 and v0.6.4 — but reactively, one at a time, with
nothing forcing the next release to do the same. This file makes tier coverage an
**explicit, checkable precondition** for every remaining v0.6.x release, so the gap
cannot recur silently.

**Honesty boundary.** The feature *themes* for v0.6.5 → v0.6.13 live in the **private**
roadmap (`UNLIMITED-SKILLS-PRIVATE-ROADMAP-v0.6.3-to-v0.6.13.md`, private registry —
not in this public repo). This file therefore provides the **enforced structure and
template**, not invented future features. Each release's themed slots are filled when
that release is scoped, from the private roadmap — never guessed here.

**Forward pre-design.** The full Free/Registered/Team/Business/Enterprise ladder for
every release v0.6.5 → v0.6.13 is already drafted in
[`v0.6.5-to-v0.6.13-tier-ladder-predesign.md`](v0.6.5-to-v0.6.13-tier-ladder-predesign.md)
(grounded in the private-roadmap themes). At build time each release's section there
expands into the full per-tier contracts + cross-tier matrix below; this table tracks
which have been turned into shipped contracts.

## Tier vocabulary (fixed)

- **Free / Community Core** — the base live feature; no account.
- **Registered** — local, account-aware bonus; still local-first, no hosted upload.
- **Team** — local multi-member/multi-agent rollup; manual sharing, no live sync.
- **Business** — admin-facing local export (CSV/JSON) + grouping; no hosted dashboard/billing.
- **Enterprise** — audit-safe local evidence/governance pack; no egress, no SSO/SCIM claims.

Above-Free tiers are **not all "paid" in the strict sense**, but all four must each get a
concrete, bounded, **local** bonus per release. No tier may claim hosted/live/billing
capability unless the code for it actually exists in that release.

## Coverage status (source of truth: the repo, not the planner)

| Release | Theme | Free | Reg | Team | Biz | Ent | Cross-tier claim | State |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: | --- |
| **v0.6.3** | Learning Loop | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **DONE** — `docs/product/v0.6.3/{free,registered,team,business,enterprise}-learning-loop-*.md` + `learning-loop-tier-matrix.md` |
| **v0.6.4** | Money Saved Meter | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **DONE** — O064 contracts (PR #182) + cross-tier matrix (O064-13) + tier review forms (PR #188) |
| **v0.6.5** | _(private roadmap)_ | — | — | — | — | — | — | **NOT SCOPED** |
| **v0.6.6** | _(private roadmap)_ | — | — | — | — | — | — | **NOT SCOPED** |
| **v0.6.7** | _(private roadmap)_ | — | — | — | — | — | — | **NOT SCOPED** |
| **v0.6.8** | _(private roadmap)_ | — | — | — | — | — | — | **NOT SCOPED** |
| **v0.6.9** | _(private roadmap)_ | — | — | — | — | — | — | **NOT SCOPED** |
| **v0.6.10** | _(private roadmap)_ | — | — | — | — | — | — | **NOT SCOPED** |
| **v0.6.11** | _(private roadmap)_ | — | — | — | — | — | — | **NOT SCOPED** |
| **v0.6.12** | _(private roadmap)_ | — | — | — | — | — | — | **NOT SCOPED** |
| **v0.6.13** | _(private roadmap)_ | — | — | — | — | — | — | **NOT SCOPED** |

✅ = a concrete bonus is documented for that tier in-repo. `—` = not yet defined.
Update a row to ✅ only when a real per-tier doc + cross-tier matrix is merged for it.

## Per-release tier-ladder template (fill before the release ships)

Copy this into `docs/product/<version>/` when the release is scoped. Each tier gets its
own short contract following the v0.6.3/v0.6.4 shape (VFP · what-it-adds-and-only-this ·
schema/aggregation · fail-closed privacy · claim boundary · backward-compat · acceptance ·
explicitly-NOT). Then one cross-tier matrix.

- [ ] **Free / Community Core** — the base live feature for `<version>` (`<theme>`):
      what every user gets with no account; the release-note-safe one-liner.
- [ ] **Registered** — the one bounded local bonus above Free; local-only, no upload.
- [ ] **Team** — the local multi-member/agent rollup; manual share, no live sync/dashboard.
- [ ] **Business** — the admin-facing local export (CSV/JSON) + grouping; no hosted/billing.
- [ ] **Enterprise** — the audit-safe local evidence/governance pack; no egress, no SSO/SCIM.
- [ ] **Cross-tier matrix** — per tier: what is **live**, the **allowed public claim**, the
      **release-note-safe** line, and what is explicitly **NOT live** in `<version>`.
- [ ] **Tier review forms** — per-tier PR review checklists (model: `docs/reviews/templates/o064-money-saved-meter-tier-review-forms.md`) so implementation PRs are graded against the contract, not by taste.

## Release gate (blocks release-readiness for any v0.6.x)

A v0.6.x release is **not** release-ready until:

1. All five tiers (Free + the four above-Free) have a concrete, documented bonus for
   that release, each within the local-first / no-unbacked-claim boundary.
2. A cross-tier matrix exists and is consistent with each tier doc (no tier promises more
   in one doc than another allows).
3. The cross-tier **claim boundary** holds: no *exact money saved*, *guaranteed bill
   reduction*, *hosted telemetry*, *live dashboard*, *enterprise governance enforced*, or
   *provider reconciliation* unless the code for it ships in that release.
4. This coverage table's row for the release is updated to ✅ with links to the docs.

A release whose paid-tier layer is empty or "design-only with no per-tier bonus" **fails
this gate**, regardless of how complete the Free core is.

## How to drive the remaining line (v0.6.5 → v0.6.13)

Do the tier-ladder design **ahead of**, not during, each build:

1. Pull the release's theme from the private roadmap (Codex / private registry).
2. Apply the template above → five tier docs + matrix + review forms in `docs/product/<version>/`.
3. Opus reviews the tier contracts pre-build; Codex implements Free core first, then the
   tier bonuses in **separate** PRs (never one giant PR); Opus reviews each against the
   tier review forms.
4. Flip the coverage row to ✅ and only then let the release gate pass.

This keeps the paid-tier value proposition **designed at every stage** — the explicit
owner requirement — instead of discovered late or left inert.
