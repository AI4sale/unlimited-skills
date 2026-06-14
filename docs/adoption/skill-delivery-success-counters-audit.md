# Skill Delivery Success Counters Audit

Status: W1 audit. This document maps the current local evidence for the
skill-delivery funnel and records the implementation gaps before any new
runtime counters are added.

This is a docs/test audit only. It does not add runtime behavior, telemetry,
uploads, hosted calls, marketplace submissions, payment flows, v0.7 release
gates, package publishing, yanking, or tags.

## Audit Summary

Current state: partial.

Unlimited Skills can already measure local aggregate routing activity through
`events.jsonl` rows for `suggest`, `view`, and `skill_used`, plus
`feedback record`, `learning-summary --events`, and `roi receipt`. The privacy
boundary is strong enough for aggregate
operator summaries: raw queries, raw tasks, raw notes, local absolute paths,
skill bodies, tool inputs, tool outputs, MCP schemas, env values, tokens, and
keys must not appear in paste-safe summaries.

The missing piece is a single local success report that joins the full funnel:

```text
suggested -> shown/carded -> viewed -> used -> accepted/rejected -> improved
```

Today, `suggest -> view -> use` can be counted by local events, and
`accepted/rejected/neutral` can be counted by local feedback rows. The
improvement loop is still a handoff through feedback triage, eval candidates,
ranking/router/docs changes, and release gates; it is not yet closed by a
single command.

The local correlation field is `session_correlation_id`: a salted local token
used for aggregate `suggest -> view -> use` rates, never a raw session id.

## Evidence Checked

Code and command surfaces:

- `unlimited_skills/suggest.py`
- `unlimited_skills/search_core.py`
- `unlimited_skills/commands/library.py`
- `unlimited_skills/commands/feedback.py`
- `unlimited_skills/commands/roi.py`
- `unlimited_skills/feedback.py`
- `unlimited_skills/roi_receipt.py`
- `unlimited_skills/server.py`
- `unlimited_skills/quickstart.py`
- `scripts/verify-v06-frozen-contracts.py`

Docs and tests:

- `docs/cli-contracts.md`
- `docs/local-event-privacy.md`
- `docs/feedback.md`
- `docs/roi-receipt.md`
- `docs/releases/v0.6-contract-freeze-spec.md`
- `docs/releases/v0.6-contract-compliance-audit.md`
- `docs/adoption/local-event-privacy-audit.md`
- `docs/adoption/first-week-adoption-measurement.md`
- `docs/skill-improvement-workflow.md`
- `tests/test_local_event_privacy.py`
- `tests/test_feedback_report.py`
- `tests/test_roi_receipt.py`

## Counter Status Vocabulary

- `ready`: existing local aggregate signal is sufficient for a W1 report.
- `partial`: existing signal exists, but correlation, attribution, or
  operator action is incomplete.
- `missing`: no local counter exists yet.
- `not_applicable`: the surface is intentionally outside this funnel.

## Funnel Counter Audit

| funnel_step | current_signal_source | current_event_or_command | available_fields | missing_fields | privacy_status | counter_status | owner | action | fallback | implementation_task |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| suggestion generated | local suggest probe | `suggest` event; `unlimited-skills suggest "<task>" --json` | `task_summary_hash`, `reason_code`, `latency_ms`, top candidate names/sources, score buckets, margin buckets, delivery tier, salted session correlation when available | explicit per-run success verdict | local-only; no raw prompt/task/query in paste-safe output | ready | Codex | Keep aggregate suggest count and reason-code counts | Use `learning-summary --events` when raw logs cannot be inspected | W1.1 expose suggest count and no-match count in `skills success-report --json` |
| suggestion shown to user/model | hook/CLI delivery tier | `suggest` event fields `delivery_tier`, `injected`; UserPromptSubmit card path | card shown count, injected count, hint tier count, score/margin buckets | explicit "user saw it" acknowledgement outside host injection | local-only; no telemetry or upload | partial | Codex | Count delivered hint/card attempts separately from generated suggestions | Treat card delivery as a proxy until W0 proves visible first value | W1.1 add delivered_hint_count and delivered_card_count |
| skill card injected | high-confidence card path | `suggest --card` JSON; `suggest` event `delivery_tier=3`, `injected=true` | carded suggest count, injected count, tier counts, card-to-action proxy in learning metrics | card render success inside every host | card content is explicit selected-skill channel; no unrelated skill bodies | partial | Codex | Keep card injection as local proxy metric | W0 validates first visible value in a fresh user path | W1.1 report card_to_action_proxy_rate with W0 dependency note |
| skill viewed | local CLI and daemon view | `view`, `daemon_view`; `unlimited-skills view <name>` | skill name, library-relative path, salted session correlation | whether view was useful | local-only; paths are library-relative in hardened rows | ready | Codex | Count views after suggest sessions | If session correlation is missing, count aggregate views only | W1.1 include view_count and suggest_to_view_rate |
| skill used | local CLI and daemon use | `skill_used`, `daemon_skill_used`; `unlimited-skills use <name>` | skill name, query/task summary hashes, library-relative path, salted session correlation | whether use solved the task | local-only; no raw task/query in hardened rows | ready | Codex | Count uses after suggest sessions | If no session correlation, report aggregate use_count only | W1.1 include use_count and suggest_to_use_rate |
| use accepted / useful | explicit local feedback | `feedback record <skill> --verdict accepted`; legacy `feedback <skill> --verdict accepted`; `learning-summary` feedback counts | per-skill accepted count | correlation from accepted verdict back to exact use/session | local-only; raw notes are not in paste-safe output | partial | Codex | Count accepted verdicts and mark attribution gap | Ask operator to record verdict after use until runtime attaches session ids | W1.1 add accepted_count and accepted_after_use_gap |
| use rejected / wrong skill | explicit local feedback | `feedback record <skill> --verdict rejected`; `feedback record <skill> --verdict wrong`; issue template `skill-not-invoked`; support response pack | per-skill rejected count, wrong-feedback count, public/manual labels | optional wrong sub-reason taxonomy | local-only/manual; no auto-upload | ready | Codex | Keep rejected/wrong verdict counts privacy-safe | Use GitHub issue template when local feedback is insufficient | W1.1 count rejected_count and wrong_feedback_count when local source exists |
| missed feedback | explicit local feedback | `feedback record <skill> --verdict missed`; `feedback prepare`; support triage workflow | local missed count, manual report category, reproduction owner, issue labels | optional missed sub-reason taxonomy | local/manual only; no prompt collection | ready | Retrieval owner | Convert validated misses into eval candidates | Use public issue labels when local counter is absent | W2 add missed eval candidate creation path |
| wrong feedback | manual/local feedback | `feedback record <skill> --verdict wrong`; `skill-not-invoked` issue template; support response pack | local wrong count, manual wrong-suggestion label | optional wrong sub-reason taxonomy | local/manual only | ready | Retrieval owner | Separate generic rejection from wrong verdict in eval handoff | Ask reporter for redacted command/category, not raw prompt | W2 add wrong-feedback eval candidate path |
| feedback converted to eval case | maintainer workflow | `docs/skill-improvement-workflow.md`; frozen eval set update process | documented maintainer flow and eval gate | automatic conversion from feedback row to eval fixture | no prompt upload; maintainer-reviewed only | missing | Retrieval owner | Define explicit feedback-to-eval acceptance checklist | Keep manual triage until eval converter exists | W2 implement feedback-to-eval candidate builder |
| eval/ranking/router/docs updated | maintainer PR and release gate | `scripts/check-skill-effectiveness.py`; docs/router/eval PRs | eval result, top-1/top-3/false-positive metrics, PR evidence | link from a feedback item to the exact fix commit | public PR evidence only | partial | Codex / Retrieval owner | Require PRs to cite the feedback/eval case they fix | Maintain manual changelog evidence | W2 add improvement ledger mapping feedback -> eval -> fix |
| release gate proves improvement | frozen gates and release docs | `scripts/check-skill-effectiveness.py`; `scripts/verify-v06-frozen-contracts.py`; release notes | gate pass/fail, eval metrics, privacy boundary checks | per-feedback before/after counter in release artifact | aggregate only; no telemetry | partial | Release owner | Record before/after eval result in release evidence | Hold improvement claims to measured eval deltas | W2 add release-gate improvement summary |

## Not Applicable Surface

E19 MCP profile bundle publishing is not a skill-delivery success counter.
It is a local, fixture-safe distribution primitive for MCP profile bundles.
It can support future governed distribution, but it does not prove that a user
was suggested the right skill, viewed it, used it, accepted it, or improved the
router. Treat E19 as `not_applicable` for W1 unless a future task explicitly
adds a distribution-to-skill-delivery counter.

## Privacy Boundary

W1 does not loosen the local-event privacy contract. Any future success report
must remain local-only and aggregate-only by default.

Forbidden in W1/W1.1 outputs:

- telemetry;
- no upload;
- upload paths;
- hosted calls;
- no marketplace submission;
- no package publishing;
- no v0.7;
- no payment;
- tracking pixels;
- analytics SDKs;
- raw prompts;
- raw queries;
- raw tasks;
- raw notes;
- tool inputs;
- tool outputs;
- skill bodies;
- MCP schemas;
- env names or values;
- tokens, keys, or proofs;
- local absolute paths;
- payment links;
- paid, hosted, team, or enterprise readiness claims.

## W1 Result

W1 can close as an audit because the gaps are explicit and actionable.
It must not be used to claim v0.7 readiness. The next implementation task is
W1.1 only after owners accept the counter model in this document.
