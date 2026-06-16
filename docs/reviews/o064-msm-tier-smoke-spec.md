# O064-MSM-TIER-SMOKE-SPEC — Money Saved tier smoke target

Opus-owned implementation note (not a standalone docs-only tier). It defines the
exact end-to-end smoke sequence Codex must wire into the integration verifier
**C064-MSM-SMOKE**. This note does not by itself claim tier completion — the tier
VFP is the runnable commands + artifacts + tests shipped in
[#210](https://github.com/AI4sale/unlimited-skills/pull/210) (Team),
[#211](https://github.com/AI4sale/unlimited-skills/pull/211) (Business), and the
Enterprise PR (evidence pack + verifier).

## Smoke sequence (run from a clean install)

Each step must exit 0 and produce the named artifact; step 7 must produce
`ok=false`.

1. `unlimited-skills money-saved meter --json` — Free meter prints a safe aggregate report.
2. `unlimited-skills money-saved registered-export --out registered-money-saved.json --json-status` — Registered export written (`registered-export-v1`).
3. `unlimited-skills money-saved team-rollup --input registered-money-saved.json --out team-money-saved.json --json-status` — Team rollup written (`money-saved-team-rollup-v1`).
4. `unlimited-skills money-saved admin-export --input team-money-saved.json --csv money-saved-admin.csv --json money-saved-admin.json` — Business CSV + JSON written (`money-saved-admin-export-v1`); CSV and JSON rows agree.
5. `unlimited-skills money-saved evidence-pack --input money-saved-admin.json --out evidence/` — Enterprise evidence pack written (`money-saved-evidence-pack-v1`) with `manifest.json` + 6 proof files.
6. `unlimited-skills money-saved verify-evidence-pack --input evidence/ --json` — verifier returns `ok=true` (all checks pass; exit 0).
7. Tamper any file under `evidence/` (e.g. edit `privacy-proof.json`), then re-run
   `unlimited-skills money-saved verify-evidence-pack --input evidence/ --json` — verifier returns `ok=false` (exit 1).

## Acceptance criteria

- The sequence above runs end-to-end from a clean install of the published wheel.
- Each schema version is exactly as named; measured facts stay separate from token
  estimates; dollars stay disabled by default at every tier.
- The verifier fails closed on tamper (step 7 → `ok=false`, exit 1) and on bad
  input (missing `--input` → exit 2).
- No forbidden claim appears in any artifact: no exact-money / exact-token /
  bill-reduction, no hosted dashboard / billing / telemetry, no SSO/SCIM /
  hosted-governance / signature-enforced.
- This note lives inside the implementation PR stack and is used by Codex for
  C064-MSM-SMOKE; it does not assert tier completion on its own.
