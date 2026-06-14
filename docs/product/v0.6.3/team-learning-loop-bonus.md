# v0.6.3 Team — Learning Loop Bonus (O063-02C)

**Tier:** Team / team-free.
**Roadmap ref:** `docs/roadmaps/unlimited-skills/UNLIMITED-SKILLS-PRIVATE-ROADMAP-v0.6.3-to-v0.6.13.md#v0.6.3`
**Invariant:** Team Free has create/join/status/pending/approve/mode/sync,
members/reject/revoke/collections/leave, **manual approval by default**, public/
registered catalogs only, **no private publishing, no dashboard, no SLA**. The
private-pack access question is undecided — this bonus does **not** rely on it.

## 1. Team persona

"Dana", lead of a 4-person agent team. Each member runs Unlimited Skills locally.
Dana needs to coordinate skill improvements without a dashboard, without pushing
private packs, and without anyone's local prompts leaving their machine.

## 2. Team-specific problem

A team does not just need candidates; it needs a **safe review workflow**: who
hit the miss, which skill was affected, what candidate is proposed, who approved
the local change, and what was deferred — with a local audit trail.

## 3. Team bonus definition

A **"team review packet"** (redacted, shareable inside the team) plus a
**manual team approval flow** for improvement candidates. Both are local-first
and ride the existing manual-approval Team primitives; no new distribution.

## 4. Review packet fields

`team-review-packet` (redacted; shared internally as a file, not auto-published):

- `packet_id`, `schema_version`, `generated_at`
- `member_alias` (team-local alias, **not** OS user, email, or machine id)
- `candidates[]`: `{ candidate_id, affected_skill, signal_summary (counts/buckets),
  confidence, proposed_action_class, redaction_status }`
- `review_status` per candidate: `proposed | approved | rejected | deferred`
- `privacy`: all-false upload/telemetry flags

## 5. Approval / rejection flow

1. Member generates a redacted packet from local candidates.
2. Dana reviews; each candidate gets `approved | rejected | deferred` **manually**
   (manual approval is the Team Free default — no auto-apply team-wide).
3. The decision is recorded locally as an audit row (section 7).
4. Approved candidates are applied **locally by each member** via the Free
   `apply-candidate` flow `[needs code verification]` — never pushed automatically.

## 6. How local-only mode works

In local-only mode the packet is a file Dana shares over the team's existing
channel (repo, chat, drive). Unlimited Skills neither transmits nor syncs it. The
"team" is a coordination convention over local artifacts, not a hosted service.

## 7. Team-sync compatibility without private publishing

Team `sync` may represent **which public/registered collections** a team aligns
on, and may carry an *approved-candidate manifest* (ids + action classes only) —
**never** skill bodies, raw signals, or private packs. Private publishing stays
out of scope.

### Example approve/reject decision record (synthetic)

```yaml
packet_id: pkt-0007
decided_by: lead-alias-1
decisions:
  - candidate_id: cand-0001
    affected_skill: python-reviewer
    decision: approved
    reason_class: ranking-hint-helps
  - candidate_id: cand-0002
    affected_skill: go-reviewer
    decision: rejected
    reason_class: low-confidence
  - candidate_id: cand-0003
    affected_skill: sql-optimizer
    decision: deferred
    reason_class: needs-more-signal
```

## 8. Redaction rules (checklist)

- [ ] No raw prompts, task/query text, or notes bodies
- [ ] No secrets, tokens, private keys
- [ ] No skill bodies or MCP schemas
- [ ] No absolute local paths
- [ ] No real OS usernames / emails / machine ids (team-local aliases only)
- [ ] Only counts, buckets, verdicts, skill names, action classes

## 9. Conflict cases

- Same skill, opposite member verdicts -> packet shows both; Dana decides; record
  the chosen `reason_class`.
- A candidate approved by Dana but a member's local skill differs -> dry-run
  preview per member before local apply; no forced overwrite.
- Stale candidate (skill changed since signal) -> mark `deferred: needs-more-signal`.

## 10. Release-note paragraph (draft)

> Teams get a **redacted team review packet** and a **manual approval flow** for
> Learning Loop candidates: collect local improvement candidates, review them
> together, approve/reject/defer each by hand, and keep a local audit trail — with
> no dashboard, no private publishing, no SLA, and no data leaving a member's
> machine.

---

### Evidence summary (for the task)

- **File:** `docs/product/v0.6.3/team-learning-loop-bonus.md`
- **Example team review packet:** section 4 fields + section 7 manifest scope.
- **Example approve/reject decision record:** section 7 (synthetic).
- **Redaction checklist:** section 8.
- **Bounds honored:** no dashboard, no private packs, no SLA, manual approval
  default, no full-catalog distribution, rejected candidate explicitly represented.
