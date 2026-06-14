# Local Learning Loop

Status: v0.6.3-alpha candidate surface.

Unlimited Skills can now turn local feedback into privacy-safe improvement
candidates. The loop is deliberately local and dry-run first:

1. record a local signal;
2. inspect learning state;
3. list improvement candidates;
4. preview a candidate without mutating skill files;
5. use the preview as human-reviewed evidence for a future skill or routing
   change.

## Commands

```powershell
unlimited-skills feedback record python-patterns --verdict wrong --query "private task text"
unlimited-skills feedback record python-patterns --verdict missed --query "private task text"
unlimited-skills feedback record python-patterns --verdict rejected --query "private task text"
unlimited-skills learning doctor
unlimited-skills improvement-candidates
unlimited-skills apply-candidate --dry-run <candidate-id>
```

`apply-candidate` currently supports `--dry-run` only. It prints
`written=false`, `mutated_files=[]`, and a no-write message.

## Feedback Outcomes

`feedback record` supports:

- `accepted`;
- `rejected`;
- `neutral`;
- `missed`;
- `wrong`.

Only `rejected`, `missed`, and `wrong` become improvement candidates. Accepted
and neutral feedback stay available to aggregate learning summaries.

## Privacy Boundary

The Learning Loop reads local `.learning` files only:

- `<root>/.learning/events.jsonl`;
- `<root>/.learning/feedback.jsonl`;
- `<root>/.learning/router-metrics.json`.

Candidate output must not include prompts, raw queries, raw notes, local
absolute paths, tokens, keys, or skill bodies. Privacy-unsafe skill labels are
redacted before serialization.

There are no hosted calls, telemetry, model calls, training, marketplace
submissions, or automatic skill edits in this flow.

## Verification

```powershell
python -m pytest tests/test_learning_loop_cli.py tests/test_feedback_report.py tests/test_effectiveness_instrumentation.py tests/test_router_metrics.py -q
python scripts/verify-v06-frozen-contracts.py --json
python scripts/verify-feedback-report-boundaries.py
git diff --check
```
