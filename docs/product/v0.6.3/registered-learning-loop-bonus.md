# v0.6.3 Registered Community — Learning Loop Bonus (O063-02B)

**Tier:** Registered / registered-community.
**Roadmap ref:** `docs/roadmaps/unlimited-skills/UNLIMITED-SKILLS-PRIVATE-ROADMAP-v0.6.3-to-v0.6.13.md#v0.6.3`
**Invariant:** the paid/registry layer is **designed but deliberately inert** in
v0.6.3. Nothing here implies live billing, live hosted upload, or production
hosted rollout. Future-hosted behavior is marked **future-compatible, not live**.

## 1. Registered-tier persona

"Riley", who has registered for an install id and the update channel. Wants the
local Learning Loop **plus** confidence that, when the hosted catalog/update path
matures, their accumulated improvement candidates can travel forward cleanly —
without uploading anything today.

## 2. Bonus definition

A **"registered-ready candidate report"**: a sanitized, versioned local artifact
that packages improvement candidates in a shape that a *future* catalog/update
compatibility review could consume — produced and stored **locally only**.

## 3. Difference from Free

| | Free | Registered |
| --- | --- | --- |
| Learning loop | full, local | full, local (unchanged) |
| Candidate output | local list + dry-run | **+ registered-ready candidate report** (sanitized, schema-versioned) |
| Forward path | none implied | a documented, future-compatible artifact shape |
| Upload | never | **never in v0.6.3** (artifact stays local) |

The Registered bonus is a **format and a forward-compatibility promise**, not a
new network capability.

## 4. Safe local artifact format

`registered-ready-candidate-report` (written under the local `.learning/`
workspace, never transmitted):

- `schema_version`, `report_type`, `generated_at`
- `install_id_present: true|false` (the id itself is **not** embedded)
- `candidates[]`: `{ candidate_id, affected_skill, signal_summary (counts/buckets),
  confidence, proposed_action_class, redaction_status }`
- `privacy`: explicit all-false upload/telemetry flags
- `compatibility`: `{ catalog_schema_target, forward_compatible: true|false }`

## 5. Future-hosted compatibility boundaries

- The report is **shaped for** a future catalog/update review but performs **no**
  submission. Any "submit" verb is out of scope for v0.6.3 and must not appear as
  a working command.
- Forward compatibility means: fields are stable/versioned, so a later release can
  add an explicit, opt-in submit path **without** redefining the artifact.

## 6. Explicit privacy rules

Forbidden from the artifact (and from any future upload): raw prompts, task/query
text, secrets, tokens, private keys, skill bodies, MCP schemas, absolute local
paths, the raw install id. Allowed: counts, buckets, verdicts, skill names,
boolean presence flags, schema/version metadata.

## 7. Example sanitized candidate report (synthetic)

```json
{
  "schema_version": 1,
  "report_type": "registered-ready-candidate-report",
  "generated_at": "2026-01-01T00:00:00Z",
  "install_id_present": true,
  "candidates": [
    {
      "candidate_id": "cand-0001",
      "affected_skill": "python-reviewer",
      "signal_summary": { "missed": 3, "wrong_skill": 1, "rejected": 2 },
      "confidence": "medium",
      "proposed_action_class": "ranking-hint",
      "redaction_status": "clean"
    }
  ],
  "privacy": { "telemetry": false, "auto_upload": false, "network_calls": false },
  "compatibility": { "catalog_schema_target": "v0.6.x", "forward_compatible": true }
}
```

## 8. CLI / doc wording that avoids overclaiming

- Say: "produces a local registered-ready report for **future** catalog
  compatibility."
- Do **not** say: "submit/sync/share with the catalog", "remote learning",
  "marketplace feedback", or anything implying a live round-trip.

## 9. Release-note paragraph (draft)

> Registered users get a **registered-ready candidate report** — a sanitized,
> schema-versioned local artifact that packages local improvement candidates for
> future catalog/update compatibility. It stays on your machine: no upload, no
> telemetry, no account data embedded. It exists so your local improvements can
> travel forward cleanly when an explicit, opt-in hosted path ships later.

## 10. Open questions for future releases

- When (if ever) does an explicit, opt-in submit path land, and under which tier?
- Does the catalog review consume per-candidate or per-library reports?
- How is the install id correlated server-side **without** embedding it locally?

---

### Evidence summary (for the task)

- **File:** `docs/product/v0.6.3/registered-learning-loop-bonus.md`
- **Example sanitized report block:** see section 7 (synthetic).
- **Forbidden uploaded fields:** raw prompts, task/query text, secrets, tokens,
  private keys, skill bodies, MCP schemas, absolute paths, raw install id.
- **Suggested release-note text:** see section 9.
- **For O063-03:** this artifact shape is the privacy-review surface; the
  reviewer can use sections 4, 6, and 7 directly.
