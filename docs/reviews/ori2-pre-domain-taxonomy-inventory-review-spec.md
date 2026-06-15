# ORI2-PRE-03 — Domain Taxonomy & Inventory Semantics Review Spec

**Task:** ORI2-PRE-03 (Opus preflight, unblocked). **Status:** review spec, no
source/runtime change. **Purpose:** define what a *correct* inventory snapshot and
domain coverage table mean, so rubric items A4/A5 (ORI2-PRE-02) can be graded
objectively rather than by taste. Answers: what counts as a "domain", how counts are
derived, and what makes the table honest vs misleading.

## What the snapshot must convey (and why)

The always-loaded AGENTS.md block must let an agent answer, in one glance: *"For the
domain I just entered, is it plausible the library has something — and is it worth a
1-second `suggest`?"* That requires (a) a credible total, (b) per-collection
provenance, and (c) a domain map. Nothing more — this is a routing hint, not a
catalog.

## Inventory count semantics

- **Unit of count = a routable skill** = one resolvable `SKILL.md` the router can
  return via `suggest`/`view`. Reference files, scripts, and template fragments are
  NOT counted.
- **De-duplication:** a skill present under multiple aliases counts once (by resolved
  name), to avoid inflating the total.
- **Per-collection split:** report counts for each installed collection
  (`ecc`, `superpowers`, `local`) separately; the total is their sum after de-dup.
- **Source of truth:** derived from `list --json` (or equivalent), never hand-typed
  (rubric C1). The generator records the count basis (which command, which root).
- **Tolerance:** the drift guard (rubric C2) should allow a small, declared delta
  (e.g. ±N or ±X%) so routine library growth does not break CI on every skill add,
  while a large divergence still fails.

## Domain taxonomy

### Design constraints
- **Small and stable.** A scannable table (target ≤ ~15 domains). Too many rows and
  the agent stops reading; too few and it cannot localize its task.
- **Task-shaped, not technology-shaped.** Domains map to the kind of work an agent
  does, because that is what the agent knows about itself mid-run. Suggested axis
  (illustrative, the build may refine): code-implementation, code-review,
  testing/QA, debugging, security, frontend/UI, backend/API, data/ML, infra/ops/
  deploy, git/release workflow, docs/writing, research, planning/architecture,
  agents/automation.
- **Derivable, not editorial.** Each domain's "availability" should be computed by
  mapping skills to domains (via pack/category/tags), not assigned by opinion, so the
  table regenerates with the library.

### Availability semantics
- The table shows, per domain, a coarse availability signal (e.g. a count bucket or
  a present/sparse/none marker) — enough to decide "worth a lookup?", not a promise
  of a specific skill.
- **Honesty rule:** a domain with zero routable skills must read as empty, not be
  silently dropped. Hiding empty domains would teach the agent the library covers
  everything (the exact over-trust failure to avoid).

## Mapping method (skills → domains)

- Prefer existing structured signals already in the repo: pack name, category/path
  segment (e.g. `packs/ecc/skills/<category>/...`), and any front-matter tags.
- The mapping must be **deterministic** and checked in (a table or rule file), so two
  generations of the same library produce the same domain assignment.
- Unmapped skills land in an explicit "other/uncategorized" bucket that is visible in
  the output — never discarded — so coverage gaps in the taxonomy are themselves
  observable.

## What a reviewer checks (ORI2-03 grading hooks)

1. Total and per-collection counts match a fresh `list --json` within tolerance.
2. De-dup is applied (no alias double-count).
3. Domain table is generated from a checked-in mapping, not editorialized.
4. Empty domains are shown as empty (honesty rule), not hidden.
5. An "other/uncategorized" bucket exists and is non-silent.
6. Regenerating twice yields identical output (determinism).
7. Row count stays scannable (≤ ~15) — over-long tables are PASS_WITH_FIXES.

## Anti-goals

- No per-skill listing in AGENTS.md (that is what `list`/`suggest` are for).
- No marketing-style "200+ skills!" rounding that the drift guard cannot verify.
- No domain invented to look comprehensive when it maps to zero skills.
