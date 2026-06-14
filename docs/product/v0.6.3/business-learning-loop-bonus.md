# v0.6.3 Business — Learning Loop Bonus (O063-02D)

**Tier:** Business.
**Roadmap ref:** `docs/roadmaps/unlimited-skills/UNLIMITED-SKILLS-PRIVATE-ROADMAP-v0.6.3-to-v0.6.13.md#v0.6.3`
**Invariant:** Business is positioned around admin dashboard/console, private team
packs, hosted audit logs, support, priority compatibility fixes, rollout
channels, orgs, private-registry namespaces. In v0.6.3 **none of those are
implemented or claimed live** — this bonus is a **local export**, dashboard-ready
but dashboard-independent.

## 1. Business persona

"Morgan", an ops admin for an org with many client-facing agents. Needs
operational control over skill quality: which skills fail, which workflows are
affected, what candidates exist, which are safe, which need review, and where
repeated waste happens.

## 2. Business-specific problem

Individual candidates are not enough at scale. Morgan needs an **admin-readable,
prioritizable backlog** that aggregates candidates across the local fleet/library
into a maintenance work queue — usable today without any hosted dashboard.

## 3. Business bonus definition

A **"Business Learning Backlog Export"**: a local, machine- and human-readable
export that turns improvement candidates into a prioritized maintenance backlog
with severity, affected skill label / workflow class, confidence, proposed action, review
status, and privacy-safe evidence.

## 4. Backlog export schema

```yaml
schema_version: 1
report_type: business-learning-backlog
generated_at: "2026-01-01T00:00:00Z"
scope: local-admin-export        # not hosted, not live audit log
items:
  - item_id: bl-0001
    skill_label: "skill:local-label:7f2d9b1c"
    affected_workflow_class: code-review     # class, not raw task text
    severity: high
    confidence: medium
    signal_summary: { missed: 7, wrong: 2, rejected: 3 }
    proposed_action_class: ranking-hint
    review_status: needs-review              # needs-review | approved | rejected | deferred
    evidence_ref: cand-0001                  # local candidate id, redacted
privacy: { telemetry: false, auto_upload: false, hosted_audit_log: false }
```

## 5. Severity and priority model

- **Severity** = impact x frequency band:
  - `critical`: client-facing workflow, repeated wrong verdicts (>= high band)
  - `high`: frequent miss/wrong on a core skill
  - `medium`: recurring but non-core
  - `low`: isolated or low-confidence
- **Priority** = severity adjusted by confidence; `low` confidence never auto-rises
  to `critical`. Bands are computed from counts/buckets, never raw text.

## 6. Local-only admin workflow

1. Morgan runs the local backlog export (read-only).
2. Triages by severity/priority; sets `review_status` per item.
3. Routes approved items to normal skill-maintenance PRs (handled by humans).
4. Keeps the export file as a **local** record. No hosted audit log is written or
   claimed.

## 7. Dashboard-future compatibility wording

- Say: "a local backlog export that a **future** Business dashboard could import."
- Do **not** say: "Business dashboard shows…", "hosted audit log records…", or
  anything implying the console is live in v0.6.3.
- The schema is stable/versioned so a later dashboard import needs no redefinition.

## 8. How it supports later support / priority-compatibility fixes

The same backlog item ids and severity bands become the input a future support /
priority-compatibility-fix workflow can consume — so v0.6.3's local export is the
on-ramp, not a throwaway.

## 9. Privacy and redaction rules

Forbidden from export: raw prompts, task/query text, secrets, tokens, private
keys, skill bodies, MCP schemas, absolute paths, client identities, real
usernames/emails. Allowed: counts, buckets, severity/priority bands, opaque skill labels,
workflow **classes**, action classes, local candidate ids.

## 10. Release-note paragraph (draft)

> Business admins get a **local Learning Backlog Export**: improvement candidates
> rolled up into a prioritized maintenance queue with severity, affected skill label and
> workflow class, confidence, proposed action, and review status — fully local,
> with no hosted audit log, no live dashboard, and no client data in the export.
> It is dashboard-ready for the future without requiring one today.

---

### Evidence summary (for the task)

- **File:** `docs/product/v0.6.3/business-learning-loop-bonus.md`
- **Example backlog export:** section 4 (synthetic YAML).
- **Example severity scoring:** section 5.
- **Fields forbidden from export:** section 9.
- **Bounds honored:** no live dashboard, no hosted audit logs, no enforced
  entitlement, no auto-remediation; local export distinct from hosted features.
