# Local Learning Loop feedback signal contract

Roadmap ref:
`docs/roadmaps/unlimited-skills/UNLIMITED-SKILLS-PRIVATE-ROADMAP-v0.6.3-to-v0.6.13.md#US-063-003`

Status: v0.6.3 release-candidate contract.

The local Learning Loop has seven feedback outcomes. They come from two local
sources:

| Outcome | Source | Meaning | Candidate behavior |
| --- | --- | --- | --- |
| `suggested` | event | Router produced at least one suggestion. | Not an improvement candidate by itself. |
| `viewed` | event | A skill was inspected after retrieval. | Not an improvement candidate by itself. |
| `used` | event | A skill was marked used. | Not an improvement candidate by itself. |
| `accepted` | feedback row | The local user marked a suggestion useful. | Counted in summaries, not actionable by default. |
| `rejected` | feedback row | The local user rejected a suggestion. | Produces a redacted improvement candidate. |
| `missed` | feedback row | The local user says the router missed a needed skill. | Produces a redacted improvement candidate. |
| `wrong` | feedback row | The local user says the router suggested the wrong skill. | Produces a redacted improvement candidate. |

## Storage Boundary

Runtime event and feedback writers must keep raw local records private and
redacted by default:

- raw prompt/task/query text is replaced with `*_summary_hash` and a presence
  flag;
- freeform notes become `notes_present` and `notes_length_bucket`;
- local absolute paths must not appear in candidate, proof, or support output;
- tokens, keys, private skill bodies, and unredacted private skill labels must
  not appear in candidate, proof, or support output;
- candidate output uses a redacted `skill_label` such as `skill-<12 hex>`.

The public contract schema is:

- `schemas/learning-feedback-signal.schema.json`

The deterministic fixtures are:

- `fixtures/learning-loop/feedback-signals-valid.jsonl`;
- `fixtures/learning-loop/feedback-signals-invalid.jsonl`.

The verifier is:

```powershell
python scripts/verify-learning-feedback-contract.py
```

The verifier checks that all seven outcomes are represented, valid rows are
redacted, invalid rows with raw query/path/token/private body fields are
rejected, and no hosted upload, telemetry, model call, or automatic skill edit is
required.

## CLI Surfaces

The contract is exposed through:

```powershell
unlimited-skills feedback record <skill-name> --verdict accepted
unlimited-skills feedback record <skill-name> --verdict rejected
unlimited-skills feedback record <skill-name> --verdict missed
unlimited-skills feedback record <skill-name> --verdict wrong
unlimited-skills learning doctor
unlimited-skills improvement-candidates
unlimited-skills apply-candidate --dry-run <candidate-id>
```

`learning-summary --events` remains aggregate-only. In the events mode it
includes local feedback counts for `accepted`, `rejected`, `neutral`, `missed`,
and `wrong` without raw queries, notes, prompts, skill bodies, local paths,
tokens, or keys. The legacy default `learning-summary` output keeps its
pre-v0.6.3 `accepted`/`rejected`/`neutral` shape for compatibility.

## Non-Goals

- No hosted analytics.
- No telemetry by default.
- No training pipeline.
- No automatic skill editing.
- No marketplace submission.
