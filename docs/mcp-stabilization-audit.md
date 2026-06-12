# MCP profile stack stabilization audit

**Status: implemented (E22).** A read-only **consistency map** of the whole
MCP profile stack — the E06–E21 layers plus the E12B warm cache — audited
over the repository itself by
`scripts/run-mcp-profile-stack-stabilization-audit.py`. It is NOT a new
runtime module: nothing here changes gateway, profile, bundle, trust,
library, or audit semantics. It proves that the *names* every layer uses —
refusal codes, CLI subcommands and flags, schema files, docs
cross-references, audit field names, security boundary phrases — stay
consistent with each other as the stack grows.

The audit is offline and local-only by construction: no network, no
telemetry, no subprocess, no hosted calls, and it never writes outside an
explicit `--out` directory. The user's library root, trust store, bundle
library, and audit log are never touched in any mode.

## Running

```bash
python scripts/run-mcp-profile-stack-stabilization-audit.py --fixture-mode --json
python scripts/run-mcp-profile-stack-stabilization-audit.py --fixture-mode --out build/audit
```

- `--fixture-mode` — pins determinism for CI use; the audit is read-only
  either way (the flag exists so fixture harnesses can say so explicitly).
- `--json` — print the machine report, one JSON document validating against
  `schemas/mcp-stabilization-audit-report.schema.json` (draft 2020-12;
  generated example `examples/mcp/stabilization-audit-report.example.json`).
- `--out DIR` — also write `stabilization-audit-report.json` and
  `stabilization-audit-report.txt` into DIR (created if missing).
- Exit codes: `0` no problem-severity findings (warnings allowed), `1`
  problems found, `2` usage errors.

## Reading findings

Every finding is `severity` + `check` + `subject` + `message`:

- **problem** — a contradiction between two sources of truth (a duplicated
  or renamed refusal code, an undocumented subcommand, an example that
  fails its schema, an unresolved docs link, a missing boundary phrase, a
  network import inside `unlimited_skills/mcp/`). Problems fail the run and
  are meant to be fixed before a release.
- **warning** — a gap rather than a contradiction: a legacy draft-07 schema
  straggler, a schema without an example or test/doc reference, a flag
  naming deviation, an audit field no doc names. Warnings do not fail the
  run; they are the backlog the next stabilization pass works from.
- **info** — inventory notes (subcommand/flag counts, examples that map to
  no schema, forward-compatible reader-only audit fields).

Subjects are repo-relative names, `mcp ...` command paths, field names, or
refusal codes — never absolute local paths, key material, or hashes, so the
report itself is safe to share.

## The six dimensions

### 1. `refusal_codes` — the reserved code registry

Collects every reserved JSON-RPC code in the claimed `-32001`…`-32019`
range from the code constants (`unlimited_skills/mcp/gateway.py`,
`profiles.py`, `bundles.py`), the E11 inspector's code→NAME→meaning table
(`audit_inspector.py`), the E16/E19 name tables (`profile_rollout.py`,
`bundle_publisher.py`), and every naming claim in the stack docs' tables.
Asserts: no duplicate definitions, no gaps inside the claimed range, the
same name for the same code everywhere a name is claimed, every code
referenced by docs exists in code, and every code in code is documented
somewhere. The canonical names are the code constants; everything else must
agree with them.

### 2. `cli_taxonomy` — the `mcp ...` command surface

Walks the real argparse tree (`unlimited_skills.cli.build_parser`) under
`mcp` and asserts every subcommand has a docs mention (the pipe-list style
`status|list|add` used by the stack docs counts) and a CHANGELOG mention,
offers `--json` wherever machine output makes sense (`mcp serve` and
`mcp gateway` are long-running stdio servers and exempt), and that the flag
vocabulary stays uniform: `--out DIR` (never `--out-dir`), directory flags
follow `--store-dir`/`--library-dir`. Flag inconsistencies are REPORTED as
warnings, never auto-fixed — renaming a shipped flag is a breaking change
that needs its own decision.

### 3. `schemas` — the schema inventory

Every `schemas/mcp-*.schema.json` must be valid JSON and declare draft
2020-12 (the two pre-E07 draft-07 files are flagged as stragglers, not
problems), have at least one validating example under `examples/mcp/`
(checked with the repo's self-contained validator — no `jsonschema`
dependency), and be referenced from at least one test and one doc. Missing
examples/references on legacy schemas are warnings (gaps); an example that
FAILS its schema is a problem (contradiction).

### 4. `docs_map` — the documentation graph

Every relative link in `docs/mcp-*.md` (plus `docs/unlimited-tools.md`)
must resolve to an existing file; every module under
`unlimited_skills/mcp/` must be mentioned by name in some doc; and the
boundary phrases required by `scripts/verify-mcp-boundaries.py` must be
present — the audit invokes that script's own `verify_static_docs`
programmatically, so the two can never drift apart.

### 5. `audit_fields` — the audit log vocabulary

Statically collects the field names the redacted audit writer
(`unlimited_skills/mcp/audit.py`) and its gateway call sites produce — the
base row (`ts`, `tool`, `upstream`, `duration_ms`, `ok`, optional
`profile`/`args`/`error`), the `profile_loaded` provenance fields, and the
E12B `cache_loaded`/`cache_refresh` event fields — and asserts the E11
inspector and E17 replay read the base fields, every written field is named
by some doc, every documented `*_sha256` field is exempted by the
inspector's redaction self-check (`KNOWN_HASH_KEYS`), and every gateway
event row is known to the inspector so it is never miscounted as a
meta-tool call. Fields read but never written are reported as info
(forward-compatible accessors such as `code`).

### 6. `security_boundaries` — the no-go invariants

Bundle-layer docs must carry explicit fail-closed language; every stack doc
must carry at least one of the no-go/locality phrases (no OAuth, no remote
upstreams, no MCP resources/prompts, no hosted gateway, no telemetry,
offline/local-only/stdio); and no module under `unlimited_skills/mcp/` may
import a network-capable library (`socket`, `http`, `urllib`, `requests`,
…) — the stack is offline by construction and this check keeps it provable.

## Policy: release-gate candidate

This runner is a **release-gate candidate**: the intent is that future
`v0.4.x` integration gates run it in fixture mode and require exit 0, the
same way `scripts/verify-mcp-boundaries.py` is required today. Until it is
wired into a gate, the rule of thumb is: run it before publishing any
change that adds a layer, a subcommand, a schema, a refusal code, or an
audit field to the MCP stack, fix the problems it reports, and either fix
or consciously accept the warnings.

Proven by `tests/test_mcp_stabilization_audit.py`: a clean run over the
current tree, report schema validation, shipped-example validation and
sync, injected-inconsistency detection (duplicated refusal code, renamed
docs table entry, corrupted example), output leak-grep with the audit
writer's own heuristics, and `--out` containment.
