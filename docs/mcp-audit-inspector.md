# MCP audit inspector (`unlimited-skills mcp audit-report`)

The audit inspector turns the local redacted MCP audit JSONL log written by
the gateway ([mcp-gateway.md](mcp-gateway.md) "Audit log") into actionable
reports. It is strictly **read-only** and offline (local files only — no
network, no telemetry): it never writes, rotates, or mutates audit files,
never sends anything anywhere, and its output never contains argument
values, error text bodies, secret values, or local filesystem paths (file
references are basenames only).

## Running

```bash
unlimited-skills mcp audit-report
unlimited-skills mcp audit-report --audit-log D:\logs\mcp-audit.jsonl
unlimited-skills mcp audit-report --section refusals
unlimited-skills mcp audit-report --json > report.json
```

- `--audit-log` — the log to inspect. Defaults to the same path the gateway
  uses: `<library root>/.learning/mcp-audit.jsonl`. A missing log (no active
  file, no rotated generations) is a clear message and exit code 1.
- `--section summary|refusals|upstreams|profiles|redaction|all` — limit the
  plain-text report to one section (default `all`).
- `--json` — print the full report as one JSON document validating against
  `schemas/mcp-audit-report.schema.json` (draft 2020-12). JSON output is
  always the complete document; `--section` only affects text rendering.

## Rotation handling

The gateway rotates the active file to `.1` (shifting `.1`→`.2`, …) once it
exceeds `audit_max_bytes`. The inspector reads **all generations in
chronological order** — highest index first (`.N` … `.1`, the oldest rows),
then the active file (the newest rows) — and reports how many rotated files
it read (`log.rotated_files_read`, plus the basenames in `log.files_read`).
Malformed JSONL lines are counted in `log.malformed_lines` and skipped,
never a crash.

## Reports

### Summary (`--section summary`)

Total/ok/refused call counts, per-tool and per-upstream splits (the
empty-string upstream collects calls that have no upstream, e.g.
`tools_search` without `refresh`), per-tool duration statistics
(min / median / nearest-rank p95 / max in ms), the time range covered, and
rotation coverage. Gateway lifecycle event rows are not calls and are
excluded from call counts: `profile_loaded` (reported in the profiles
section) and the E12B warm-cache events `cache_loaded`/`cache_refresh`.

### Refusals (`--section refusals`)

Breakdown of `ok: false` rows by JSON-RPC refusal code with each code's
NAME and meaning. Known codes are the gateway refusal family:
`-32001`…`-32010` (the E07/E08 upstream security model — see the table in
[mcp-gateway.md](mcp-gateway.md)), `-32011`…`-32014` (the tool-profile
family: `TOOL_NOT_VISIBLE`, `TOOL_NOT_CALLABLE`, `PROFILE_NOT_FOUND`,
`PROFILE_INVALID`), and `-32015`…`-32019` (the signed-bundle family:
`BUNDLE_SIGNATURE_INVALID`, `BUNDLE_EXPIRED`, `BUNDLE_REVOKED`,
`BUNDLE_AUDIENCE_MISMATCH`, `BUNDLE_KEY_MISSING` — see
[mcp-signed-profile-bundles.md](mcp-signed-profile-bundles.md)). Anything
unattributable is reported as `unknown`.

Audit rows carry a path-scrubbed error *string*, not a numeric code, so the
inspector classifies refusals by the distinctive phrases each gateway
refusal message uses; rows that ever carry an explicit integer `code` field
are honored directly. Also included: per-upstream refusal counts and the
most recent refusals (timestamp + tool + upstream + code only — argument
values are structurally impossible in these entries, enforced by
`additionalProperties: false` in the schema).

### Upstream health (`--section upstreams`)

Per upstream: calls, refusals, refusal rate, timeout count (`-32002`),
protocol errors (`-32003`), spawn failures (`-32001`), and average duration.
Upstreams at or above the refusal-rate threshold (default 50%) are marked
`[FLAGGED]` — start there when something feels slow or broken.

### Profile usage (`--section profiles`)

Present **only when the log carries tool-profile fields** (a `profile`
field on call rows or a `profile_loaded` event row — written by the E10
gateway). Pre-E10 logs and no-profiles open mode are read identically; the
section is simply omitted from `all` output and from the JSON document
(requesting `--section profiles` explicitly answers with a "not present"
note). When present: per-profile call counts, `profile_loaded` events with
the profile file's SHA-256 and rule counts, and counts for the
profile-related refusals `-32011`…`-32014` (zero counts included).

### Redaction self-check (`--section redaction`)

A guard against future redaction regressions: the inspector re-scans every
string that actually landed on disk with the same secret-shape heuristics
the writer uses (`audit.looks_secret`: `Bearer`/`Basic` headers, JWTs, PEM
blocks, long hex/base64-like blobs) plus the home-dir-like path pattern.

- **PASS** — no audited string looks like a secret or a local path. This is
  the expected steady state, because `redact()`/`scrub_paths()` run on
  every row before it is written.
- **FAIL** — at least one suspect. Each suspect is reported as file
  basename + line number + field path + reason (`secret-looking value` or
  `home-dir-like path`). **The suspect value itself is never printed** — the
  report must not become a second copy of whatever redaction missed.
  Inspect the named rows locally and treat a FAIL as a redaction bug.

The documented non-sensitive hash field `profile_sha256` (a hex blob by
nature, pinned by `profile_loaded` rows) is exempt from the secret scan;
`[redacted]` placeholders are skipped.

## JSON report document

One document per run (`schemas/mcp-audit-report.schema.json`):
`report_type: "mcp-audit-report"`, `schema_version: 1`, `generated_at`,
plus the `log`, `summary`, `refusals`, `upstreams`, optional `profiles`,
and `redaction` sections described above. The schema locks down the leak
surfaces (`additionalProperties: false` on recent-refusal and suspect
entries; file references restricted to basenames by pattern).

Implementation: pure functions in `unlimited_skills/mcp/audit_inspector.py`;
tests in `tests/test_mcp_audit_inspector.py`. MCP v1 schemas are alpha and
may break before v0.6.

See also: [mcp-audit-replay.md](mcp-audit-replay.md) -- the E17
`mcp profiles replay-audit` simulator reuses this inspector's readers and
refusal classification to replay the same audit log against a PROPOSED
policy before it is applied.
