# v0.6.3 Enterprise — Learning Loop Bonus (O063-02E)

**Tier:** Enterprise.
**Roadmap ref:** `docs/roadmaps/unlimited-skills/UNLIMITED-SKILLS-PRIVATE-ROADMAP-v0.6.3-to-v0.6.13.md#v0.6.3`
**Invariant:** Enterprise is positioned around SSO/SCIM, audit logs, on-prem/VPC
license server, managed fleet, compliance, private registry, and **Enterprise
Skill Lock**. v0.6.3 does **not** make any of those newly live. The bonus is
**controlled improvement with evidence**, not more automation.

## 1. Enterprise persona

"Alex", an enterprise platform/governance operator. Runs governed agent fleets
under policy. Will not enable anything that could rewrite skills, leak prompts,
bypass approved registries, or silently change a governed environment.

## 2. Enterprise-specific risk

The Learning Loop, naively shipped, looks like "the tool edits skills based on
usage." Alex needs the opposite guarantee: **diagnostics and previews only**, with
**no auto-apply**, **approved-source enforcement**, and **audit evidence** for any
change a human later makes.

## 3. Enterprise bonus definition

Two artifacts:
1. **Enterprise Learning Evidence Pack** — an audit-safe local record of what the
   loop observed and proposed, with redacted evidence.
2. **No-Auto-Apply Governance Contract** — an explicit statement that candidates
   are never applied automatically and that Skill Lock / approved-source rules are
   respected.

## 4. Evidence pack contents

```yaml
schema_version: 1
report_type: enterprise-learning-evidence-pack
generated_at: "2026-01-01T00:00:00Z"
governance:
  auto_apply: false
  approved_sources_only: true
  skill_lock_respected: true
candidates:
  - candidate_id: cand-0001
    skill_label: "skill:local-label:7f2d9b1c"
    source_class: approved-registry      # approved-registry | signed-pack | approved-local
    signal_summary: { missed: 5, wrong: 1 }
    confidence: medium
    proposed_action_class: ranking-hint
    apply_status: not-applied            # always not-applied in the pack
    integrity: { method: sha256, verified: true, signature: not-claimed }
privacy: { telemetry: false, auto_upload: false, prompts: false, paths: false }
```

## 5. No-auto-apply contract (statement)

> Unlimited Skills Learning Loop in an Enterprise-governed environment will not
> apply, rewrite, install, or publish any skill change automatically. It produces
> diagnostics, candidates, and dry-run previews only. Every change requires an
> explicit human action through the organization's approved process.

## 6. Policy / Skill Lock interaction

Under Enterprise Skill Lock, a locked instance accepts skills only from approved
registries, signed packs, or approved local sources. The Learning Loop's
candidate previews **respect the lock**: a candidate whose source class is not
approved is shown as `blocked-by-policy`, never applied.

## 7. Approved-source boundary

`source_class` is mandatory on every candidate: `approved-registry`, `signed-pack`,
or `approved-local`. Anything else is `blocked-by-policy`. No candidate may
introduce a skill from an unapproved source.

## 8. Audit fields

`candidate_id`, `skill_label`, `source_class`, `signal_summary` (counts only),
`confidence`, `proposed_action_class`, `apply_status` (always `not-applied` in the
pack), `integrity.method`, `integrity.verified`, decision actor alias and
timestamp when a human later acts (recorded locally).

## 9. Security and compliance restrictions

- **Integrity wording:** archives are **SHA256-verified**; do **not** claim
  cryptographic **signature** unless the code actually signs. The pack carries
  `integrity.signature: not-claimed` where only hashing is used.
- No prompts, task text, private paths, skill bodies, keys, or tokens in the pack.
- No SSO/SCIM, on-prem license server, or hosted compliance portal is implied.

## 10. Release-note paragraph (draft)

> Enterprise operators get an **audit-safe Learning Evidence Pack** and an explicit
> **No-Auto-Apply Governance Contract**: the Learning Loop observes and proposes,
> but never rewrites or installs skills automatically, respects Enterprise Skill
> Lock and approved-source boundaries, and records redacted local audit evidence.
> Archive integrity is described as SHA256 verification, not signature, unless
> signing is actually in use.

### Allowed vs forbidden release-note claims

- **Allowed:** "no auto-apply", "approved-source respected", "SHA256-verified",
  "local redacted evidence", "Skill-Lock-compatible previews".
- **Forbidden:** "signed packs" (unless code signs), "live audit log", "SSO/SCIM
  ready", "on-prem license server", "compliance certified", "auto-remediation".

---

### Evidence summary (for the task)

- **File:** `docs/product/v0.6.3/enterprise-learning-loop-bonus.md`
- **Example evidence pack:** section 4 (synthetic YAML).
- **Example no-auto-apply policy statement:** section 5.
- **Allowed/forbidden release-note claims:** end of section 10.
- **For O063-03:** sections 4-9 are the privacy/security review surface; verdict
  PASS/PASS_WITH_FIXES/BLOCKED requested.
