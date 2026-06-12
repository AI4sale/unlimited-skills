# Skill Effectiveness Gate

Unlimited Skills must not be only a catalog that agents ignore. The A0 gate
checks whether the router can produce a fast, visible, relevant skill
suggestion before a release claims adoption readiness.

This is not hosted telemetry and not RAG. It is a deterministic local gate for
skill invocation readiness:

- no prompt upload;
- no tool output upload;
- no skill body in the suggestion output;
- no local path in the suggestion output;
- no automatic skill execution;
- no hosted calls.

## Suggest Probe

Use `suggest` when a hook or router needs a cheap skill-use nudge:

```bash
unlimited-skills suggest "review this repository for exposed secrets" --json
```

The command returns only:

- `task_summary_hash`;
- up to three skill candidate names;
- score;
- reason code;
- recommended next action;
- latency;
- privacy booleans.

It does not print the user task, skill body, tool output, or local `SKILL.md`
path. The intended router behavior is:

1. Search first.
2. View one relevant skill.
3. Act using the selected skill.

If no skill crosses the floor, continue normally.

## A0 Merge Gate

Run the frozen eval gate before merging skill-routing, ranking, hook, indexing,
or release-readiness changes:

```bash
python scripts/check-skill-effectiveness.py --json --no-record
python scripts/verify-skill-effectiveness-gate.py
```

The A0 eval set lives in `evals/invocation-scenarios.json` and contains 30
positive skill-eligible scenarios plus 12 negative no-skill scenarios. The
checker runs the real cold `suggest` subprocess for every scenario, including
the ambient card path used by hooks.

Minimum A0 merge thresholds:

- positive scenarios: `30`;
- negative scenarios: `12`;
- top-1 hit rate: `>= 0.55`;
- top-3 hit rate: `>= 0.83`;
- false positive rate: `<= 0.10`;
- p90 suggest latency: `<= 1500ms`;
- p95 suggest latency: `<= 2500ms`;
- injection precision: `>= 0.90`;
- no negative scenario receives a skill card;
- no unintended skill body leak outside the sanctioned tier-3 card channel;
- no prompt upload;
- no local path leak.

## v0.5 Release Gate

Before a v0.5 public adoption release, run:

```bash
python scripts/verify-skill-effectiveness-gate.py --gate v0.5-release
```

The v0.5 gate raises quality and latency thresholds:

- top-1 hit rate: `>= 0.65`;
- top-3 hit rate: `>= 0.90`;
- false positive rate: `<= 0.10`;
- p90 suggest latency: `<= 1200ms`;
- p95 suggest latency: `<= 2000ms`.

## When To Run

Run this gate:

- on every public adoption or release gate;
- before v0.5;
- at least every 10 releases;
- after changes to ranking, router instructions, hooks, indexing, or skill
  import behavior.

For release cadence, refresh the compact record only after a full accepted run:

```bash
python scripts/check-skill-effectiveness.py --json
git add evals/last-effectiveness-run.json
```

The eval gate is deterministic and local. Real model behavior should also be
observed locally with redacted invocation reports, but those reports are not CI
gates yet because they depend on agent behavior outside this repository.
