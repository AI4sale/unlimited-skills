# v0.6.4 Money Saved Meter — Tier Bonuses (O064-03)

**Roadmap ref:** `...#v0.6.4`. **Status:** planning/design (no code).
**Invariant:** no live billing, no hosted dashboards, no entitlement enforcement,
no telemetry. Each tier bonus is a **local** artifact/surface; paid-tier extras
are bounded and future-compatible. Dollars are estimated and off by default (see
O064-01 §7, O064-02).

## Free / Community Core
- **Bonus:** local **value receipt** + periodic **push nudge** ("Last 100 calls:
  ~X bytes / ~Y est. tokens of standing MCP context avoided").
- **User value:** passive, ongoing proof the gateway pays for itself — no command,
  no account.
- **CLI/docs surface:** push nudge after an existing local surface + `mcp savings`
  (pull) unchanged; `--json` aggregate.
- **Privacy:** aggregate counts/bytes/est-tokens only; no server names in the push
  nudge; local-only.
- **Not live:** dollars (opt-in, local rate only); no hosted anything.
- **Release-note-safe:** "local periodic estimate of context avoided".

## Registered
- **Bonus:** a **future-compatible local savings export** (schema-versioned) the
  user could later carry to a hosted catalog/update value view — produced locally,
  no upload.
- **User value:** savings history is portable forward without sending anything now.
- **CLI/docs surface:** local export file (no submit verb).
- **Privacy:** install id not embedded; same safe fields as Free.
- **Not live:** any hosted submission/sync.
- **Release-note-safe:** "local export, future-compatible; no upload in v0.6.4".

## Team
- **Bonus:** a **shareable local team savings summary** (aggregate per-member
  bytes/tokens avoided, member-local aliases), shared over the team's own channel.
- **User value:** a team can see collective context savings without a dashboard.
- **CLI/docs surface:** local summary file; manual share.
- **Privacy:** aliases not OS users/emails; aggregates only; no server names.
- **Not live:** dashboard, hosted audit, SLA, auto-sync.
- **Release-note-safe:** "local team summary; no dashboard, no upload".

## Business
- **Bonus:** an **admin-readable local savings/backlog export** (per-team/agent
  aggregate savings; prioritization of where the gateway helps most), import-ready
  for a *future* dashboard.
- **User value:** ops can quantify gateway value across the org, locally, today.
- **CLI/docs surface:** local JSON/YAML export.
- **Privacy:** workflow/agent **classes** not raw tasks; no client identities; no
  hosted audit log.
- **Not live:** Business dashboard, hosted audit log, entitlement, billing.
- **Release-note-safe:** "local export a future dashboard could import".

## Enterprise
- **Bonus:** an **audit-safe local savings evidence pack** (aggregate context-cost
  avoided + method/assumptions), for governance review; no auto-action.
- **User value:** governed environments get defensible, local ROI evidence with no
  data egress.
- **CLI/docs surface:** evidence pack export + method statement.
- **Privacy:** aggregates only; no prompts/paths/keys; SHA256 wording only if used,
  signature `not-claimed`.
- **Not live:** SSO/SCIM, on-prem license server, hosted compliance portal, billing.
- **Release-note-safe:** "local audit-safe savings evidence; no hosted features".

## Claim safety checklist

- [ ] Every tier bonus is local; nothing fakes a live paid/hosted system.
- [ ] No telemetry / upload / billing / entitlement.
- [ ] Dollars estimated + off by default; tokens labeled estimated.
- [ ] Push nudge aggregates (no server names); paid-tier exports are
      docs-only/future-compatible except the Free local meter (fully live).
- [ ] Public release-note wording uses the per-tier "Release-note-safe" lines.

---

### Evidence summary (for the task)

- **File:** `docs/product/v0.6.4/money-saved-meter-tier-bonuses.md`
- **Per-tier sections:** Free (live local meter), Registered/Team/Business/
  Enterprise (bounded local exports, future-compatible).
- **No fake paid features; no telemetry; dollars estimated/off-by-default.**
