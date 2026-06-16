# O064-004R — Money Saved Meter Reproduction Docs: Opus Review Forms

**Roadmap ref:** `...#v0.6.4` US-064-004. **Status:** review templates (no code). **Reviewer:** Opus.
**Purpose:** pre-built per-task checklists so that when Codex opens the **US-064-004 reproduction
docs** PR (C064-004A walkthrough / C064-004B docs verifier / C064-004C discoverability wiring /
C064-004D tests), the Opus reviewer grades each O064-004R dimension in minutes against fixed,
**repo-grounded** criteria. Same role TIER-06 / ORI2-PRE-07 played for earlier batches.

**Grade against (already in repo):**
- Value model — `docs/product/v0.6.4/money-saved-meter-value-model.md` (exact/measured/estimated; dollars off; cadence-not-billing).
- JSON contract — `docs/product/v0.6.4/money-saved-meter-json-contract.v1.md`.
- Before/after command — `docs/product/v0.6.4/money-saved-meter-before-after-command.md`.
- 100-call value report — `docs/product/v0.6.4/money-saved-meter-100-call-value-report.md`.
- Known limitations — `docs/reports/v0.6.4-money-saved-meter-known-limitations.md`.
- Acceptance matrix — `docs/product/v0.6.4/money-saved-meter-acceptance-matrix.md` (T1–T15).

**Verdict scale (every form):** `PASS` / `PASS_WITH_FIXES` / `BLOCKED`. One must-have (M)
failure ⇒ `BLOCKED`; should-have (S) failure ⇒ `PASS_WITH_FIXES`. Cite `file:line` evidence.
Opus posts the verdict; **Codex merges** (Opus does not grant acceptance / does not merge).

## Ground truth: the real CLI surface (verified on main)

The walkthrough's commands MUST match the actual `money-saved meter` subcommand exactly:

```
unlimited-skills money-saved meter
  [--json] [--out <file>] [--json-status]
  [--mode {before,after,current}]            # default: current
  [--mcp-savings-json <file>]                # read an existing `mcp savings --json` artifact
  [--audit-log <file>]
  [--compare <previous-meter.json>]
  [--target-calls <int>]                     # default: 100; "this is not billing math"
  [--fixture-100-call]                       # emit the deterministic 100-call value report fixture
```
Supporting input: `unlimited-skills mcp savings --json`. Verifier scripts (from US-064-003):
`scripts/verify-money-saved-100-call-report.py --json` and
`scripts/verify-money-saved-meter-100-call-fixture.py --json`.

> **R4 watch-item:** the roadmap prose says "fixture-100-call mode" and "100-call window"; the real
> flag is **`--fixture-100-call`** and the cadence flag is **`--target-calls`** (NOT
> `--target-call-count`). Any doc command using a non-existent flag/spelling is an R4 FAIL.

---

## Form O064-004R1 — Reproducibility path

Goal: a new user reproduces a measurement from the docs **without guessing**.

- [ ] **M** A single walkthrough exists at `docs/product/v0.6.4/money-saved-meter-reproduce-measurements.md`.
- [ ] **M** Covers all run modes end to end: empty/no-data; `--mode current`; before→after
      (`--mode before` … `--mode after --compare …`); and `--fixture-100-call`.
- [ ] **M** Every command is **copy-pasteable** and self-contained (shows the `mcp savings --json`
      pre-step and the `--mcp-savings-json`/`--out` wiring, matching the before/after command doc).
- [ ] **M** Explains interpreting **partial vs complete windows** (`is_complete_window`,
      `window_call_count` / `target_call_count`).
- [ ] **M** Shows how to **verify privacy** (the all-False privacy block / `assert_*_safe`) and how
      to compare **Markdown vs JSON** output.
- [ ] **S** Links the value model, JSON contract, before/after command, 100-call report, and known
      limitations (no dead/renamed links).
- **Do NOT approve if:** any documented mode can't be run as written; a step depends on a file the
  prior step didn't produce; or a reader must infer a flag not shown.
- Evidence: __________  Verdict: __________

## Form O064-004R2 — Claim & language

- [ ] **M** No forbidden claims anywhere in the new/edited docs: *exact tokens saved*, *exact money
      saved*, *guaranteed bill reduction*, *hosted telemetry(-backed) savings*, *provider billing
      reconciliation*, *all skill-body savings measured exactly*.
- [ ] **M** Required boundary phrases present and correct: **bytes measured / tokens estimated**
      (`bytes // 4`), **dollars disabled by default** (null unless local rate), **100 calls = cadence
      for operator review, not billing math**, **local-only / no upload**.
- [ ] **M** "What is NOT implemented yet" section names: push nudge, state writer, paid-tier exports,
      release gate/version/tag/publish, hosted surfaces (consistent with known-limitations doc).
- [ ] **S** Tone matches the authorized public claim (O064-07); nothing stronger than "local periodic
      estimate of context avoided".
- **Do NOT approve if:** any exact-money/token or hosted/live claim appears, or a tier/paid feature is
  described as live.
- Evidence: __________  Verdict: __________

## Form O064-004R3 — Privacy

- [ ] **M** The docs never instruct the user to paste or share raw prompts, task text, skill bodies,
      secrets/keys/tokens, local absolute paths, private-repo paths, server/MCP names, or raw MCP
      schemas/payloads — into any command, file, or report.
- [ ] **M** Any example output shown is aggregate/redacted (no real paths/servers/secrets; matches the
      `redacted-fixture-upstream` style of the fixtures).
- [ ] **M** Where the walkthrough has the user write files (`--out before-meter.json` etc.), it states
      those stay **local** (no upload/submit verb).
- [ ] **S** Notes that the meter aborts/suppresses rather than writing a partially-redacted report
      (fail-closed `assert_money_saved_meter_safe`).
- **Do NOT approve if:** any step would put sensitive data into a file/flag/example, or implies the
  output is sent anywhere.
- Evidence: __________  Verdict: __________

## Form O064-004R4 — Command consistency

- [ ] **M** Every documented command/flag exists in the real CLI (see ground-truth surface above):
      `money-saved meter`, `--json`, `--out`, `--json-status`, `--mode {before,after,current}`,
      `--mcp-savings-json`, `--audit-log`, `--compare`, `--target-calls`, `--fixture-100-call`;
      plus `unlimited-skills mcp savings --json`.
- [ ] **M** No invented/misspelled flags (e.g. `--target-call-count`, `--fixture100`, `--price-*` if
      not implemented). Defaults stated correctly (`--mode current`, `--target-calls 100`).
- [ ] **M** Both verifier scripts referenced by their real paths and invoked as documented
      (`--json`, emit `ok=true`); the C064-004B docs verifier
      (`scripts/verify-money-saved-reproduction-docs.py --json`) actually checks the
      required-commands / forbidden-claims / boundary-phrases set and emits `ok=true`.
- [ ] **S** `docs/cli-contracts.md` and known-limitations updated to point at the walkthrough
      (C064-004C), with no release-claim inflation and no version bump/tag/publish.
- **Do NOT approve if:** any documented command would error as written, or the docs verifier passes
  while a forbidden claim / missing boundary phrase is actually present (verifier is too weak).
- Evidence: __________  Verdict: __________

---

## Cross-cutting (all US-064-004 PRs)

- [ ] Docs-only / no runtime behavior change; Free-core meter output unchanged.
- [ ] No release/tag/version bump/PyPI/hosted/team/business/enterprise work; #119/E19 stays parked.
- [ ] Tests green (`.venv/Scripts/python.exe -m pytest …`); the new docs verifier passes; frozen
      contracts + feedback boundaries + docs/security claims pass; full suite green; `git diff --check`.

## Reviewer output

One verdict per form + one overall, each PASS mapped to the criterion (and the T1–T15 acceptance
test where relevant) it satisfies, so the review demonstrably confirms a new user can reproduce the
measurement honestly, privately, and with commands that actually run. Opus posts to the Hermes chat;
**Codex merges.**
