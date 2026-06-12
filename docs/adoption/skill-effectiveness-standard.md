# Skill Effectiveness Regression Standard

Owner directive: «Сделать фикс, написать стандартный тест, который каждые 10 релизов прогоняет проверку эффективности скилла» — every 10 releases at the latest, the skill-suggestion effectiveness check MUST be re-run and its record committed. This document is the standing standard; the baseline diagnosis behind it is [a0-invocation-diagnosis.md](a0-invocation-diagnosis.md).

## What is measured

`scripts/check-skill-effectiveness.py` replays the frozen scenario set `evals/invocation-scenarios.json` (30 diagnosis scenarios + 10 added negatives N1–N10; with the two diagnosis no-skill scenarios S18/S28 that is 28 positives and 12 no-skill scenarios) through the REAL cold `suggest` probe — one `python -m unlimited_skills suggest --json` subprocess per scenario, exactly the way agents and hooks invoke it — against the bundled 267-skill library (`packs/`).

Metrics:

- **top-1 / top-3 hit rate** — share of positive scenarios where an expected skill is the first / among the (≤3) returned suggestions;
- **false-positive rate** — share of no-skill scenarios where `suggest` returns ANYTHING above the score floor (silence beats noise);
- **forbidden top-1 violations** — the wrong-ecosystem hijackers observed in the baseline (e.g. `flutter-dart-code-review` topping a Python review query) must never be top-1 again;
- **cold-probe latency p50/p90/p95/max** — wall time of the full subprocess, spawn included (max is a warning above 5000 ms, not a gate — cold-spawn outliers happen; investigate if repeated);
- **privacy invariants** — VERIFIED by scanning every actual probe output during the run, never assumed: `no_prompt_upload` (the task/query text never appears in suggest output — only `task_summary_hash`, a short sha256 of the normalized query), `no_local_path_leak` (no absolute filesystem paths anywhere in the output), `no_skill_body_leak` (no skill body content; verified against normalized chunks of every indexed body). All three must be true to PASS.

## The `suggest --json` output contract (privacy-hardened)

The probe's JSON output contains ONLY:

| Field | Content |
| --- | --- |
| `task_summary_hash` | short sha256 (12 hex chars) of the lowercased, whitespace-normalized query — a correlation id, never the text |
| `top_3_skill_candidates` | up to 3 objects with `name`, `source` (pack/collection), `score` — never paths, descriptions, or bodies |
| `reason_code` | `match_found` / `below_floor` / `empty_library` / `error` |
| `recommended_next_action` | a next step referencing skills by NAME only (e.g. `unlimited-skills view <name>`) |
| `latency_ms` | in-process probe time |

It never echoes the task/query text, never includes local filesystem paths, and never includes skill bodies. Text mode prints `name [source] — description` one-liners (no paths, no scores) or nothing. The `UserPromptSubmit` hook hint is built from this contract and is equally path-free and prompt-free.

## Thresholds (PASS/FAIL — Hermes A0 merge gate)

| Metric | A0 gate | Measured 2026-06-12 (post-gate run) |
| --- | --- | --- |
| top-1 hit rate | >= 0.55 | **0.929** (26/28 positives) |
| top-3 hit rate | >= 0.83 | **0.964** (27/28 positives) |
| false-positive rate | <= 0.10 | **0.000** (0/12 negatives) |
| forbidden top-1 violations | 0 | **0** |
| latency p90 | <= 1500 ms | **~700 ms** (direct spawn) |
| latency p95 | <= 2500 ms | **~710 ms** |
| latency max | <= 5000 ms (warning only, unless repeated) | **~740 ms** |
| privacy: no_skill_body_leak / no_prompt_upload / no_local_path_leak | all true | **all true** |

Planned v0.5 gate (tighten once the library and ranking stabilize; requires a fresh measured run before adoption):

| Metric | v0.5 gate |
| --- | --- |
| top-1 hit rate | >= 0.65 |
| top-3 hit rate | >= 0.90 |
| false-positive rate | <= 0.10 |
| latency p90 | <= 1200 ms |
| latency p95 | <= 2000 ms |

History on the same frozen queries: baseline before the A0 ranking fixes — top-1 0.679, top-3 0.750, false-positive rate 0.143, 2 forbidden top-1 violations (S2, S29); diagnosis-time top-1 relevance was 17/30 with `search --mode lexical` at 3.9 s and hybrid at 9.9 s per call. A0 calibration run (2026-06-12, 5 negatives) — top-1 0.821, top-3 0.821, FP 0.000. Hermes-gate run (2026-06-12, 10 negatives) — top-1 0.929, top-3 0.964, FP 0.000 after: the `prompt-optimizer` pack description fix (S29 — the pack shipped a broken empty `description: >-` frontmatter scalar), the profiling↔benchmarking synonym group (S19), the `pull request`/`release notes` phrase-alias table (S5, S27). All of these are generic library/ranking fixes; no eval query is special-cased.

Known honest miss at the calibrated floor (12.0): S7 (refactor a large module safely) — the best matching bundled skills (`hexagonal-architecture` at 4) sit far below the floor, and no generic synonym honestly bridges "refactor safely" to them. Raising the floor any lower than 12 readmits the strongest negative (N4 at 11). Do NOT tune queries to fix this; fix ranking or the library.

## How to run

```bash
# full run: replays all scenarios, prints the table, writes the record
python scripts/check-skill-effectiveness.py

# machine-readable
python scripts/check-skill-effectiveness.py --json

# cadence gate only (no scenario replay, < 1 s)
python scripts/check-skill-effectiveness.py --cadence-check

# CLI alias (wraps the same script logic; requires a source checkout)
unlimited-skills skills check-effectiveness [--json] [--cadence-check] [--no-record]
```

A full run writes `evals/last-effectiveness-run.json` — `{version, date, results (including the privacy booleans), thresholds, pass}`. Commit that file together with the run.

## Cadence contract (every 10 releases)

`--cadence-check` compares the version recorded in `evals/last-effectiveness-run.json` against the shipped release manifests in `docs/releases/` and **FAILS (exit 1) when 10 or more releases have shipped since the recorded run**, or when no record exists. It is part of the release checklist in [release-process.md](../release-process.md): run it before tagging every release; when it fails, run the full check, fix any regression, and commit the fresh record.

The gate is enforced in two places:

1. `python scripts/check-skill-effectiveness.py --cadence-check` in the release checklist (docs/release-process.md);
2. `tests/test_skill_effectiveness_check.py::test_repo_record_exists_and_cadence_is_green` — the normal test suite goes red when the record is missing or 10+ releases stale, so the gap cannot ship unnoticed even if the checklist is skipped.

## Rules for changing the eval set

- The 30 diagnosis scenarios (S1–S30) are FROZEN: queries must not be rewritten to make the checker pass.
- `expected_skills` may be extended only with skills that would genuinely change the work for that scenario (document the reasoning in the file's `notes`).
- New scenarios (positive or negative) may be appended with fresh ids; update `tests/test_skill_effectiveness_check.py::test_frozen_scenario_file_shape` counts accordingly.
- Threshold changes require a fresh measured run recorded in this document with the date and the reason.
- If the bundled packs change materially (skills added/removed), re-run the full check and re-document the table above.

## Latency budget notes

The probe's hard budget is p90 < 1.5 s cold, process spawn included. Measured composition on the calibration machine (Windows, 267-skill indexed library): bare Python spawn ~105 ms; `unlimited_skills.suggest` import + index load + scoring ~300-350 ms; total direct spawn p90 ~450 ms; through `powershell -NoProfile -File <launcher>` p90 ~790 ms (PowerShell adds ~300 ms). The fast path depends on two invariants — keep them:

1. `python -m unlimited_skills suggest` and the rendered launchers dispatch to `unlimited_skills/suggest.py` WITHOUT importing `unlimited_skills.cli` (see `unlimited_skills/__main__.py`); the full CLI import alone costs ~650 ms.
2. `suggest` never syncs native skill roots, never loads embedding models, and reads the prebuilt lexical index (`.unlimited-skills-index.json`); a missing index falls back to a filesystem walk, which is slower but still within budget at this library size.

If the library outgrows the budget, the documented upgrade path is the existing warm daemon (`unlimited-skills serve`, `unlimited_skills/server.py`): teach `suggest` to proxy to the daemon when it is running and fall back in-process otherwise.
