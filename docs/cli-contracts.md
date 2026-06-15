# CLI Contracts

This document lists the public CLI and stdout JSON contracts frozen by the
v0.6 adoption-cycle spec. The source of truth for the freeze is
[releases/v0.6-contract-freeze-spec.md](releases/v0.6-contract-freeze-spec.md).

## Contract Rules

- JSON stdout remains valid JSON on successful `--json` commands.
- Documented fields keep their meaning through v0.7.
- New optional fields may be added.
- Error text may change, but safety refusals must remain clear and local-first.
- Human-readable text output is not byte-stable unless explicitly stated.
- Public commands must not print prompts, tool inputs/outputs, skill bodies,
  MCP schemas, env values, tokens, keys, raw local configs, raw learning logs,
  or unredacted local absolute paths.

## Command Contracts

| Command | Stability | JSON contract |
| --- | --- | --- |
| `unlimited-skills --version` | Stable public-alpha | Prints the installed Unlimited Skills version. For `v0.6.2-alpha`, the PyPI-installed package returns `unlimited-skills 0.6.2`. |
| `unlimited-skills quickstart --json` | Stable public-alpha | Object with `root`, `library`, `search`, `savings`, `savings_error`, `next_steps`. The `root` value is redacted as `<local-library>`. |
| `unlimited-skills suggest "<task>" --json` | Stable public-alpha | Privacy-hardened object with `task_summary_hash`, `top_3_skill_candidates`, `reason_code`, `recommended_next_action`, and `latency_ms`. Candidate entries contain `name`, `source`, and `score`. The probe must not echo raw prompt text in JSON output. |
| `unlimited-skills suggest "<task>" --json --card` | Stable public-alpha | Adds `delivery_tier` and, only when high-confidence card injection is selected, `skill_card`. Any `skill_card` is capped, references the selected skill by name, and must not include local filesystem paths, query text, or unrelated skills. |
| `unlimited-skills mcp savings --json` | Stable public-alpha | Object with measured `servers`, total byte/token estimates, gateway byte/token estimates, savings bytes, savings percent, token heuristic, and benchmark fallback when no server is measured. |
| `unlimited-skills mcp install --claude-code --dry-run` | Stable public-alpha | Human-readable redacted dry-run plan. It must preserve existing MCP servers, avoid copying env values automatically, and explain the target scope without requiring writes. |
| `unlimited-skills mcp install --claude-code --dry-run --json` | Stable public-alpha | Installer report with action/scope/dry-run status, redacted target information, planned writes/backups, and validation status. It must preserve existing MCP servers and redact env values/local paths. |
| `unlimited-skills mcp install status --json` | Stable public-alpha | Status report for the Claude Code gateway integration without writing files. |
| `unlimited-skills feedback prepare --json` | Stable public-alpha | Alias for JSON report output. Schema-versioned local report with redacted environment, install, quickstart, suggest, MCP savings, issue-template, and local-error summaries. |
| `unlimited-skills feedback prepare --format json` | Stable public-alpha | Schema-versioned local report with redacted environment, install, quickstart, suggest, MCP savings, issue-template, and local-error summaries. |
| `unlimited-skills feedback prepare --format markdown` | Stable public-alpha | Paste-safe Markdown rendering of the same support-report boundary. |
| `unlimited-skills learning-summary --events` | Stable public-alpha | JSON object with `feedback` counts and aggregate `effectiveness` metrics. No raw query/task text, raw notes, prompts, skill bodies, local absolute paths, tokens, or env values. |
| `unlimited-skills learning-summary --events --json` | Stable public-alpha | Explicit JSON form of the aggregate-only events summary. This is the `0.6.1` hotfix surface that replaced the untagged `0.6.0` upload after the published verifier caught the missing flag. |
| `python scripts/verify-learning-feedback-contract.py` | Stable docs tooling | Offline verifier for the local Learning Loop feedback signal contract. It checks the valid and invalid fixtures for `suggested`, `viewed`, `used`, `accepted`, `rejected`, `missed`, and `wrong` without hosted calls. |
| `python scripts/verify-learning-loop-closed-loop-proof.py` | Stable docs tooling | Offline proof that one redacted `wrong` feedback row flows through `learning doctor`, `improvement-candidates`, and `apply-candidate --dry-run` without leaking private fields or mutating skill files. |
| `unlimited-skills learning doctor` | Stable public-alpha | Local-only JSON diagnostic for `.learning` state: root/log presence, aggregate feedback/event/router counts, candidate count, candidate ids, and privacy flags. It must be helpful on empty state and must not print raw prompts, raw queries, raw notes, local paths, tokens, keys, or skill bodies. |
| `unlimited-skills improvement-candidates` | Stable public-alpha | Local-only JSON list of redacted Learning Loop improvement candidates derived from local feedback. Candidate entries include id, type, title, source, safe skill label, signal count, confidence, recommended action, dry-run summary, and privacy flags. No skill files are modified. |
| `unlimited-skills apply-candidate --dry-run <candidate-id>` | Stable public-alpha | Local-only JSON dry-run preview for one Learning Loop candidate. It reports `written=false`, `mutated_files=[]`, a preview summary, and an explicit no-write message. Non-dry-run apply is intentionally unavailable. |
| `unlimited-skills roi receipt` | Stable public-alpha | Prints a screenshot-friendly Markdown local ROI receipt with aggregate local-safe values only. |
| `unlimited-skills roi receipt --format markdown` | Stable public-alpha | Prints the Markdown receipt with the required measured-not-promised notice and no forbidden fields. |
| `unlimited-skills roi receipt --format json` | Stable public-alpha | Emits `schemas/roi-receipt.schema.json` JSON with version, library count, quickstart status, MCP savings summary, skill routing aggregates, learning-summary aggregates, feedback-prepare status, and privacy notice. |
| `unlimited-skills roi receipt --since 7d` | Stable public-alpha | Filters local aggregation to the requested window when event timestamps support it. Unsafe legacy rows are skipped and reported as `unavailable_legacy_logs`. |
| `unlimited-skills roi receipt --out roi-receipt.md` | Stable public-alpha | Writes the selected format to a local file. It does not upload, transmit, or print the local output path. |
| `unlimited-skills money-saved meter --json` | Stable v0.6.4 development surface | Emits `report_type=money_saved_meter` JSON for local before/after install measurement. It reads an optional `--mcp-savings-json` artifact and optional `--audit-log`, strips server names/raw schemas/paths, labels bytes as measured and tokens/dollars as estimates, and writes nothing unless `--out` is provided. |
| `unlimited-skills money-saved meter --mode before --mcp-savings-json before.json --out before-meter.json --json` | Stable v0.6.4 development surface | Captures a local before-install aggregate report. The output is safe to keep as a baseline for `--compare`; it does not mutate local meter state or claim release readiness. |
| `unlimited-skills money-saved meter --mode after --mcp-savings-json after.json --compare before-meter.json --json` | Stable v0.6.4 development surface | Emits the after-install aggregate report plus an optional local comparison delta when both reports contain measured context bytes. It never extrapolates exact tokens, exact dollars, or provider bill reduction. |
| `python scripts/generate-public-alpha-signal-rollup.py --fixture-mode --out <path>` | Stable docs tooling | Writes Markdown to `<path>` and prints `wrote <path>`. Fixture mode is offline and deterministic. |
| `python scripts/generate-public-alpha-signal-rollup.py --out <path>` | Stable docs tooling | Live mode may read public PyPI/GitHub aggregate counters and local tracker docs. It does not collect private user data. |

## Frozen Contract Harness

Run the v0.6 frozen-contract harness before release promotion:

```bash
python scripts/verify-v06-frozen-contracts.py --json
```

The harness checks the current working tree by default. It emits
`report_type=v06_frozen_contracts` JSON with one row per frozen surface and
`pass`, `drift`, or `blocked` status. Drift rows include owner, action, and
fallback fields and exit non-zero. Optional wheel mode verifies a clean built
wheel without uploading or publishing:

```bash
python -m build
python scripts/verify-v06-frozen-contracts.py --wheel dist/unlimited_skills-*.whl --json
```

## Stdout JSON Stability

Stable through v0.7:

- documented top-level field names;
- field meaning;
- local-only/privacy-safe boundary;
- valid JSON on success;
- non-zero exit when safety validation refuses an operation.

Not frozen:

- ordering of object keys;
- whitespace and indentation;
- exact human-readable text;
- optional fields;
- exact score values, token estimates, or benchmark fixture values;
- internal event row file names beyond the privacy boundaries in
  [local-event-privacy.md](local-event-privacy.md).

## Release and Publishing Contract

PyPI release automation must keep using the documented Trusted Publishing path
and post-publish verifier before tag claims. A release is not considered
published until:

1. the PyPI workflow succeeds;
2. the requested `unlimited-skills==<version>` installs cleanly;
3. the release verifier passes in published/package-availability mode;
4. the GitHub tag/prerelease points to the verified release commit.

`v0.6.2-alpha` is the accepted v0.6 alpha release. The `0.6.1-alpha` release
remains the valid replacement for the uploaded-but-not-released `0.6.0`
artifact. The `0.6.0` package was uploaded to PyPI but was not tagged or
released because the published verifier failed after upload when
`learning-summary --events --json` was rejected.
