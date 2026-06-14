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
unlimited-skills feedback record <skill-name> --verdict wrong --query "<short task summary>"
unlimited-skills feedback record <skill-name> --verdict missed --query "<short task summary>"
unlimited-skills feedback record <skill-name> --verdict rejected --query "<short task summary>"
unlimited-skills learning doctor
unlimited-skills improvement-candidates
unlimited-skills apply-candidate --dry-run <candidate-id>
```

`--query` is optional diagnostic input for local learning. When present, the raw
query text is not stored at rest: feedback rows keep a `query_summary_hash` and
presence/bucket fields so candidates can aggregate signals without replaying the
prompt or task text.

`apply-candidate` currently supports `--dry-run` only. It prints
`written=false`, `mutated_files=[]`, and a no-write message.

On a new library with no feedback yet, the commands are intentionally quiet:

```text
unlimited-skills learning doctor
No learning feedback found yet.

unlimited-skills improvement-candidates
No improvement candidates yet.
```

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

The formal local feedback signal contract is documented in
[`learning-loop-feedback-contract.md`](learning-loop-feedback-contract.md). It
defines all seven local outcomes: `suggested`, `viewed`, `used`, `accepted`,
`rejected`, `missed`, and `wrong`.

The deterministic closed-loop proof is documented in
[`reports/v0.6.3-learning-loop-closed-loop-proof.md`](reports/v0.6.3-learning-loop-closed-loop-proof.md).
It proves the redacted dry-run candidate path and explicitly does not claim
automatic skill improvement.

The final main-branch smoke after #174 and #175 is documented in
[`reports/v0.6.3-learning-loop-main-smoke.md`](reports/v0.6.3-learning-loop-main-smoke.md).

## Verification

```powershell
python scripts/verify-learning-feedback-contract.py
python scripts/verify-learning-loop-closed-loop-proof.py
python -m pytest tests/test_learning_loop_cli.py tests/test_feedback_report.py tests/test_effectiveness_instrumentation.py tests/test_router_metrics.py -q
python -m pytest tests/test_learning_loop_contracts.py -q
python scripts/verify-v06-frozen-contracts.py --json
python scripts/verify-feedback-report-boundaries.py
git diff --check
```
