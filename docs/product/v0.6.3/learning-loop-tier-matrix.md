# v0.6.3 Learning Loop — Cross-Tier Matrix (O063-02F)

**Roadmap ref:** `docs/roadmaps/unlimited-skills/UNLIMITED-SKILLS-PRIVATE-ROADMAP-v0.6.3-to-v0.6.13.md#v0.6.3`
**Inputs:** the five tier stories O063-02A..E in `docs/product/v0.6.3/`.
**Purpose:** one release-ready artifact proving every tier gets a concrete v0.6.3
bonus without overclaiming inactive hosted/paid functionality.

> **Implementation note:** the Learning Loop's *capture/aggregate/privacy* half
> is implemented, and **Codex C063-02 / PR #173 is merged** for the Free-core
> inspect / candidates / dry-run surfaces (`improvement-candidates`,
> `apply-candidate --dry-run`, `learning doctor`, missed/wrong verdicts). #175
> remains pending for the closed-loop regression proof, and O063-03R/O063-04 must
> pass before release-ready claims.
>
> **Reconciliation with the shipped C063-02 impl (O063-06, preliminary vs #173):**
> the shipped verdict literal is **`wrong`** (not `wrong-skill`), and candidate
> output identifies skills by an opaque `skill_label`, never the raw name. Earlier
> roadmap/spec language used `wrong-skill` as a conceptual label; current public
> docs follow the shipped literal `wrong`. Per-tier exports (registered report /
> team packet / business backlog / enterprise pack) are **not** in #173 and remain
> docs-only, future-compatible.

## Tier matrix

### Free / community-core
- **Baseline:** local router, library, search/view/use, `feedback record`
  (`accepted/rejected/neutral`), `learning-summary`, `feedback prepare`, daemon,
  MCP gateway.
- **v0.6.3 bonus:** missed/wrong feedback + local **improvement candidates**
  + **dry-run** candidate preview + `learning doctor`.
- **User value:** turn "that was wrong" moments into a reviewable, previewable
  local improvement list — zero registration, zero data exposure.
- **CLI/docs surface:** `feedback record --verdict missed|wrong`,
  `improvement-candidates`, `apply-candidate --dry-run`, `learning doctor`.
- **Privacy boundary:** local-only; counts/buckets/verdicts/opaque skill labels only; no
  raw prompts/paths/tokens; dry-run non-mutating.
- **Not included:** hosted catalog, telemetry, team sync, dashboard, auto-apply,
  auto-publish, billing.
- **Future-compatible (not live):** none required — Free is fully live and local.
- **Reviewer notes:** the only tier whose bonus is meant to be *fully functional*
  in v0.6.3; depends on C063-02 landing.
- **Release-note wording:** see `free-learning-loop-user-story.md` s.9.

### Registered / registered-community
- **Baseline:** Free + install id, update channel, compat checks, hosted catalogs
  (read), SHA256-verified archives, registration-gated Local Skill Hub.
- **v0.6.3 bonus:** **registered-ready candidate report** (sanitized,
  schema-versioned local artifact for future catalog/update compatibility).
- **User value:** local improvements travel forward cleanly when an opt-in hosted
  path ships later — without uploading anything now.
- **CLI/docs surface:** a local report generator (no submit verb).
- **Privacy boundary:** artifact local-only; raw install id not embedded; no
  upload; same redaction as Free.
- **Not included:** hosted feedback submission, catalog publishing, entitlement
  enforcement, billing, remote learning.
- **Future-compatible (not live):** the report **shape** anticipates a future
  opt-in submit path; no live round-trip in v0.6.3.
- **Reviewer notes:** highest overclaim risk — wording must avoid "submit/sync".
- **Release-note wording:** see `registered-learning-loop-bonus.md` s.9.

### Team / team-free
- **Baseline:** create/join/status/pending/approve/mode/sync, members/reject/
  revoke/collections/leave, manual approval default, public/registered catalogs,
  no private publishing, no dashboard, no SLA.
- **v0.6.3 bonus:** **redacted team review packet** + **manual team approval flow**
  + local audit trail of decisions.
- **User value:** coordinate improvements as a team safely — review, approve/
  reject/defer by hand, keep a local trail.
- **CLI/docs surface:** packet generation + decision record (files shared over the
  team's own channel).
- **Privacy boundary:** team-local aliases only; no private packs; no auto-apply
  team-wide; same redaction as Free.
- **Not included:** dashboard, private publishing, SLA, hosted audit logs,
  auto-team-apply, full-catalog distribution.
- **Future-compatible (not live):** `sync` may later carry an approved-candidate
  manifest (ids + action classes only).
- **Reviewer notes:** must not rely on the undecided private-pack question.
- **Release-note wording:** see `team-learning-loop-bonus.md` s.10.

### Business
- **Baseline:** admin dashboard/console, private team packs, hosted audit logs,
  support, priority compat fixes, rollout channels, orgs, private-registry
  namespaces — **all designed, not live in v0.6.3**.
- **v0.6.3 bonus:** **Business Learning Backlog Export** (local prioritized
  maintenance queue: severity, affected skill/workflow class, confidence, action,
  review status).
- **User value:** admins prioritize skill-maintenance work at scale — today,
  without a live dashboard.
- **CLI/docs surface:** local backlog export (JSON/YAML).
- **Privacy boundary:** workflow **classes** not raw tasks; no client identities;
  no hosted audit log; same redaction as Free.
- **Not included:** live dashboard, hosted audit logs, enforced entitlement,
  auto-remediation, billing.
- **Future-compatible (not live):** schema is import-ready for a future dashboard.
- **Reviewer notes:** wording must say "future dashboard could import", never
  "dashboard shows".
- **Release-note wording:** see `business-learning-loop-bonus.md` s.10.

### Enterprise
- **Baseline:** SSO/SCIM, audit logs, on-prem/VPC license server, managed fleet,
  compliance, private registry, Enterprise Skill Lock — **none newly live in
  v0.6.3**.
- **v0.6.3 bonus:** **Enterprise Learning Evidence Pack** + **No-Auto-Apply
  Governance Contract** (Skill-Lock-respecting, approved-source-bounded, redacted
  audit evidence).
- **User value:** governed environments can allow diagnostics/previews with proof
  of no auto-mutation and approved-source enforcement.
- **CLI/docs surface:** evidence pack export + governance statement.
- **Privacy boundary:** counts only; no prompts/paths/keys/tokens; integrity =
  SHA256, signature `not-claimed` unless code signs.
- **Not included:** SSO/SCIM, on-prem license server, hosted compliance portal,
  billing, auto-remediation, Skill-Lock bypass.
- **Future-compatible (not live):** evidence pack feeds future governance
  workflows.
- **Reviewer notes:** do **not** overclaim "signed" when only SHA256 is used.
- **Release-note wording:** see `enterprise-learning-loop-bonus.md` s.10.

## Claim safety checklist

- [ ] Every tier has a concrete, bounded v0.6.3 bonus.
- [ ] Free is fully useful and local.
- [ ] Registered/Team/Business/Enterprise bonuses do not fake live paid systems.
- [ ] No telemetry by default; no prompt/skill/private-data upload; no auto-apply;
      no full-catalog distribution; no live billing; no production hosted rollout.
- [ ] "signed" is not claimed unless code signs (Enterprise/Registered integrity).
- [ ] Commands not yet in code are marked `[needs code verification]`.
- [ ] Public-doc claims are the "Allowed" lists; "Forbidden" lists stay
      internal/future-only.

## Contradictions found and fixed during integration

1. **Registered vs Free overlap** — both produce candidate output; resolved by
   scoping Registered strictly to the *forward-compatible report format*, not a
   new capability.
2. **Signature-claim drift** — Registered baseline says "SHA256-verified", but
   Enterprise prose risked overclaiming cryptographic signing; aligned both to
   SHA256 with explicit `signature: not-claimed`.
3. **Team private-pack dependency** — initial Team draft leaned on private packs;
   removed, since that question is undecided.
4. **Business "dashboard" tense** — normalized all Business wording to "future
   dashboard could import", never present-tense live dashboard.

## Allowed in public docs vs internal/future-only

- **Allowed publicly (v0.6.3):** local Learning Loop, missed/wrong feedback,
  improvement candidates, dry-run preview, learning doctor, per-tier local
  artifacts (registered report / team packet / business backlog / enterprise
  evidence pack) as docs-only future-compatible patterns, SHA256 verification,
  no-auto-apply guarantee.
- **Internal/future-only (do NOT publish as live):** hosted submission/sync,
  live dashboards, hosted audit logs, SSO/SCIM, license server, billing,
  signatures, marketplace feedback, remote learning.

---

### Evidence summary (for the task)

- **Tier matrix:** this file.
- **Release notes draft:** `docs/releases/v0.6.3-tier-bonus-release-notes-draft.md`.
- **Claim safety checklist:** above.
- **Contradictions found and fixed:** above (4 items).
