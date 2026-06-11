# MCP gateway (`unlimited-skills mcp gateway`)

The Unlimited Tools gateway is one stdio MCP server that fronts many upstream
MCP servers with three meta-tools, so agent hosts stop paying 30–200K context
tokens for tool schemas they may never call. Rationale and the privacy model:
[unlimited-tools.md](unlimited-tools.md).

## Running

```bash
unlimited-skills mcp gateway --config ~/.unlimited-skills/gateway-config.json
unlimited-skills mcp gateway --config cfg.json --audit-log D:\logs\mcp-audit.jsonl
```

`--config` is required. `--audit-log` overrides the default audit location
(`<library root>/.learning/mcp-audit.jsonl`).

## Config file

Validated against `schemas/mcp-upstream-config.schema.json` (the upstream
security model format — [mcp-upstream-security-model.md](mcp-upstream-security-model.md)
is the full specification); annotated samples are at
`examples/mcp/upstreams.example.json` and
`examples/mcp/gateway-config.example.json`:

```json
{
  "schema_version": 1,
  "startup_timeout_seconds": 20,
  "request_timeout_seconds": 30,
  "upstreams": [
    {
      "name": "github",
      "trust_level": "local-trusted",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env_allowlist": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
      "request_timeout_seconds": 60,
      "tools": [
        { "name": "create_issue", "description": "Create a GitHub issue in a repository" }
      ]
    }
  ]
}
```

- `name` — unique id; tools are addressed as `<name>.<tool>`.
- `command` / `args` — the upstream stdio MCP server process, spawned as an
  argv vector (never a shell). stdio only: no URLs, no OAuth upstreams. This
  is not a hosted gateway.
- `trust_level` — `disabled`, `local-restricted` (default), `local-trusted`,
  or `future-remote-placeholder`; `enabled: false` forces `disabled`
  semantics. Governs command form, environment, and size ceilings — see
  below.
- `env_allowlist` — **names** of environment variables copied from the local
  environment into the upstream, on top of a fixed minimal base set. Never
  wildcards, never literal values; the v1 `env` value map is rejected at
  load. Values are **never logged**.
- `tools` — optional pre-declared names + descriptions so `tools_search` can
  match this upstream **before it is ever spawned**. Without it, an upstream
  becomes searchable after its first lazy spawn or a `tools_search` call with
  `refresh: true`.
- `startup_timeout_seconds` / `request_timeout_seconds` — per-upstream
  deadlines, bounded to (0, 120] s / (0, 300] s (out-of-range values are a
  load error). May also be set at the top level as defaults for all
  upstreams. Built-in defaults: **20 s** for spawn + `initialize` handshake,
  **30 s** per request.
- `max_schema_bytes` / `max_response_bytes` — size caps (defaults 64 KiB /
  256 KiB) with trust-level ceilings: 256 KiB / 1 MiB at `local-restricted`,
  1 MiB / 8 MiB at `local-trusted`. Exceeding a cap is a structured refusal,
  never truncation.
- `audit_level` (`standard` default, or `minimal`), top-level
  `audit_max_bytes` / `audit_max_files` — see "Audit log" below.

## Config enforcement (upstream security model)

`v0.4.3-alpha` verifies this MCP upstream enforcement with fixture-mode
tests and release evidence.

The gateway enforces [mcp-upstream-security-model.md](mcp-upstream-security-model.md)
— that document is the authoritative contract; in short:

- **Trust levels.** `disabled` upstreams are never spawned, never indexed
  (including pre-declared `tools`), and any call addressing them is refused
  with `-32005`. `future-remote-placeholder` refuses every operation with
  `-32010` until the OAuth/remote gate opens.
- **Command allowlist.** No shell, ever. At `local-restricted` the command
  must be an absolute path (not under a temp directory); at `local-trusted`
  it may instead be a bare known-runner name (`node`, `npx`, `bunx`, `deno`,
  `python`, `python3`, `uv`, `uvx` — a frozen list in code, not extensible
  via config). Shell binaries and relative paths are refused at every level
  with `-32006`.
- **Environment.** Upstreams are spawned with a from-scratch environment:
  a fixed minimal base set (`PATH`, `HOME`, temp/locale variables, Windows
  process essentials — `COMSPEC` excluded) plus the `env_allowlist` names
  present in the local environment. Anything broader is refused with
  `-32007`. The gateway's own working directory is never inherited
  (per-upstream scratch directory, or an explicit absolute `cwd`).
- **Size limits.** An oversized tool schema is refused with `-32008` (the
  tool stays searchable by name/description); an oversized `tools/call`
  result is dropped and refused with `-32009`. Nothing is ever truncated.
- **Bounded timeouts and ceilings** are rejected at config load time
  (`GatewayConfigError`) before any process is spawned.

MCP v1 schemas/configs are alpha and may break before v0.6.

## Meta-tools

### `tools_search`

Args: `query` (required), `limit` (1–20, default 8), `refresh` (default
`false`).

Lexically scores indexed upstream tool **names and descriptions** (no vector
stack required) and returns hits shaped per
`schemas/mcp-tool-index.schema.json`: `tool` (`upstream.tool`), `upstream`,
`name`, `description`, `score`. Input schemas are **never** included — that is
the whole point. By default it does not spawn anything; `refresh: true` spawns
and indexes every configured upstream first.

### `tools_schema`

Args: `tool` — fully qualified `upstream.tool`.

Lazily ensures that one upstream is spawned (subprocess stdio, `initialize`
handshake, `tools/list` to index) and returns that **one** tool's
`inputSchema` with its description. Upstream schemas are never dumped
wholesale.

### `tools_call`

Args: `tool` (`upstream.tool`), `arguments` (object).

Routes the call to the owning upstream's `tools/call` and relays the result
(`examples/mcp/tools-call-request.example.json` shows a full request).

## Lifecycle and timeouts

- **Lazy spawn**: no upstream process exists until the first
  `tools_schema`/`tools_call` that needs it (or `tools_search` with
  `refresh: true`). Proven by `tests/test_mcp_gateway.py::test_upstream_lazy_spawn_and_reuse`.
- **Reuse**: a spawned upstream stays alive and is reused for every later
  call; the tool index is cached in-memory per gateway process.
- **Deadlines**: every upstream interaction has a hard deadline
  (`startup_timeout_seconds` for spawn + `initialize`,
  `request_timeout_seconds` per request). Upstream stdout is consumed by a
  background reader thread, so a silent upstream can never hang the gateway.
- **Poisoned upstreams are dropped**: after a timeout or a malformed response
  the upstream's stdio stream is out of sync, so the process is terminated
  immediately and respawned lazily on next need.
- **Clean shutdown**: when the gateway loop ends (stdin EOF), every live
  upstream is terminated; a process that ignores terminate for 5 s is killed.

## Error model: refusals vs tool errors

The gateway never relays garbage and never fails silently. Two failure
channels, consistent with the skills server:

1. **Caller mistakes** (bad `query`, unknown tool name, unqualified `tool`,
   non-object `arguments`) are domain errors: returned as MCP tool results
   with `isError: true`, like every MCP tool failure.
2. **Infrastructure refusals** are structured JSON-RPC **error responses**
   with explicit codes:

| Code | Meaning |
| --- | --- |
| `-32001` | `UPSTREAM_START_FAILED` — upstream could not be spawned or failed its `initialize` handshake |
| `-32002` | `UPSTREAM_TIMEOUT` — upstream did not answer within the deadline (upstream is terminated) |
| `-32003` | `UPSTREAM_PROTOCOL_ERROR` — upstream wrote malformed/garbage output; nothing is relayed (upstream is terminated) |
| `-32004` | `UPSTREAM_FAILED` — upstream returned a JSON-RPC error or died mid-call |
| `-32005` | `UPSTREAM_DISABLED` — upstream exists in config but is `disabled` (or `enabled: false`) |
| `-32006` | `COMMAND_NOT_ALLOWED` — command violates the allowlist policy for its trust level |
| `-32007` | `ENV_FORWARDING_DENIED` — environment forwarding beyond the names-only allowlist |
| `-32008` | `SCHEMA_TOO_LARGE` — one tool's `inputSchema` exceeds `max_schema_bytes`; refused, never truncated |
| `-32009` | `RESPONSE_TOO_LARGE` — a `tools/call` result exceeds `max_response_bytes`; dropped, never trimmed |
| `-32010` | `TRUST_LEVEL_VIOLATION` — operation not permitted at the upstream's trust level (e.g. `future-remote-placeholder`) |

Standard JSON-RPC codes (`-32700` parse error, `-32600` invalid request —
including unsupported batch requests, `-32601` unknown method, `-32602`
invalid params, `-32603` internal error) are documented in
[mcp-server.md](mcp-server.md) and shared by both servers.

Every refusal path also appends a redacted audit entry (`ok: false` with a
path-scrubbed `error` string), so there are no silent failures.

## Audit log

Every meta-tool call — success or refusal — appends one JSON line: `ts`,
`tool`, `upstream`, `duration_ms`, `ok`, plus redacted `args` and a
path-scrubbed `error` on failure. Redaction (pure functions `redact()` /
`looks_secret()` / `scrub_paths()` in `unlimited_skills/mcp/audit.py`):

- values of argument keys matching token/secret/key/password/proof/auth/
  credential/cookie/session/signature/cert/private/prompt/env/body/content/
  query/text
  (case-insensitive) are replaced with `[redacted]`, recursively through
  nested dicts and lists;
- string **values** that look like secrets are redacted even under harmless
  keys: `Bearer …`/`Basic …` headers, JWTs, PEM private-key/certificate
  blocks, long hex or base64-like blobs;
- env values are never passed to the audit layer at all (and env-shaped keys
  are redacted as defense in depth);
- prompts, search queries, free-form text inputs, skill bodies, and upstream
  tool results are never written — only call shape, timing, and status;
- local filesystem paths (drive, UNC, `~/…`, POSIX home/tmp) are scrubbed
  from every audited string, including error strings.

The gateway does not expose resources or prompts, does not send telemetry,
and does not provide a hosted gateway mode in v1.

Proven by `tests/test_mcp_gateway.py::test_audit_file_never_leaks_secrets`,
which greps a generated audit file for token/bearer/password/proof/prompt/
skill-body/env/local-path plaintext after a representative call.

Per-upstream `audit_level`: `standard` (default, as above) or `minimal`
(only `ts`/`tool`/`upstream`/`duration_ms`/`ok` — no args shape, no error
string), for upstreams whose argument *shapes* are themselves sensitive.
There is deliberately no `off`.

Rotation: when the active JSONL file exceeds `audit_max_bytes` (default
10 MiB) it is renamed to `.1` (shifting `.1`→`.2`, …) and generations beyond
`audit_max_files` (default 5) are deleted. Local renames only — no
compression, no upload, no telemetry.

## Upstream security model

Trust levels, the command allowlist, environment forwarding, size caps,
audit policy, the refusal codes `-32005`…`-32010`, the 9-vector threat
model, and the future OAuth/remote and resources/prompts gates are specified
in [mcp-upstream-security-model.md](mcp-upstream-security-model.md). The
gateway enforces that model; the "Config enforcement" section above is the
summary.

## Inspecting the audit log

`unlimited-skills mcp audit-report` turns this audit log (including rotated
generations) into local read-only reports: call summary with duration
percentiles, refusal breakdown by named code, per-upstream health, profile
usage (when profile fields are present), and a redaction self-check. See
[mcp-audit-inspector.md](mcp-audit-inspector.md).

## Permissioned tool profiles (enforced)

[mcp-permissioned-tool-profiles.md](mcp-permissioned-tool-profiles.md)
(designed in E09, enforced since E10; that document is the authoritative
contract) specifies named tool profiles on top of the model above:
default-deny visibility rules filtering `tools_search`/`tools_schema` and
callability rules gating `tools_call` (callable is always a subset of
visible), restriction-only `extends` inheritance, profile selection via
`--profile` / `UNLIMITED_SKILLS_MCP_PROFILE` / `default_profile`, and the
refusal codes `-32011`…`-32014`. Without a profile file the gateway keeps the
open behavior documented above (no-profiles mode, the default until v0.6).

Enforcement summary (opt-in, profiles file format:
`schemas/mcp-tool-profile.schema.json`, annotated example
`examples/mcp/tool-profile.example.json`):

```bash
unlimited-skills mcp gateway --config cfg.json --profiles ~/.unlimited-skills/tool-profiles.json --profile reviewer
```

- `--profiles FILE` configures the profile file (read exactly once at
  startup — no hot reload; restart is the revocation procedure). Absent =
  no-profiles mode, exactly the behavior documented above. `--profile NAME`
  selects the profile; precedence is `--profile` >
  `UNLIMITED_SKILLS_MCP_PROFILE` > the file's `default_profile`, and an
  unresolved selection never falls back to anything wider.
- With a profile active: `tools_search` returns only visible tools (hidden
  tools are simply absent, pre-declared and live-indexed alike) and marks
  each hit `callable: true|false`; a search `refresh` never spawns an
  upstream that cannot contribute a visible tool; `tools_schema` and
  `tools_call` refuse invisible tools with the existence-neutral `-32011`
  `tool_not_visible` *before* any existence check or lazy spawn (a hidden
  tool is indistinguishable from a nonexistent one); `tools_call` refuses
  visible-but-not-callable tools with `-32012` `tool_not_callable` (no spawn;
  their schemas stay readable via `tools_schema`).
- Fail closed: a missing/unresolvable profile (`-32013` `profile_not_found`)
  or an invalid profile file (`-32014` `profile_invalid` — schema violation,
  bad rule string, `extends` self-reference/cycle/depth > 8/dangling parent,
  uncovered `callable` rule) keeps the gateway serving the three meta-tools
  but refuses **every** call with that code; interactive starts also report
  the condition on stderr. There is no warn-but-allow mode.
- Audit: while profiles are active every row (success or refusal, at both
  audit levels) carries the non-sensitive `profile` name; startup appends one
  `profile_loaded` row with the profile file's SHA-256 and rule counts
  (numbers only). Rule evaluation matches fully qualified tool names only and
  never receives call arguments; the redaction floor above is unchanged.

## Warm tool-index cache (`--index-cache`, opt-in)

Implements candidate 1 of the warm-start plan in
[mcp-performance.md](mcp-performance.md). **Default OFF**: without the flag
the gateway behaves byte-for-byte as documented above — no cache file is
ever read or written.

```bash
unlimited-skills mcp gateway --config cfg.json --index-cache
unlimited-skills mcp gateway --config cfg.json --index-cache D:\cache\mcp
```

- **What it does**: persists each upstream's indexed tool entries (names,
  descriptions, `inputSchema`s, oversized markers) to one local JSON file —
  `<library root>/.learning/mcp-tool-index-cache.json` by default, or
  `<DIR>/mcp-tool-index-cache.json` when the flag is given a directory. On
  the next gateway start with the flag, valid entries are loaded into the
  in-memory index **without spawning anything**: `tools_search` matches the
  cached tools and `tools_schema` answers from the cache at roughly the
  reuse cost (~1 ms) instead of paying the ~150 ms first-touch spawn.
  `tools_call` still spawns lazily exactly as before — a live process is
  created only when a call actually needs one.
- **Keying and invalidation**: each entry is keyed by the SHA-256 of the
  upstream's canonical spec (name, command, args, `env_allowlist`, `cwd`,
  trust level, enabled, size limits) plus the upstream's `serverInfo`
  name/version captured at index time. Any config change yields a different
  hash, so the stale entry is simply never matched. Every live spawn
  re-indexes from the real `tools/list` and overwrites the entry (this is
  also how a changed `serverInfo` version is resolved); `tools_search` with
  `refresh: true` spawns, re-indexes, and rewrites entries; entries older
  than 7 days are ignored at load; a corrupt or unknown-`schema_version`
  cache file is ignored and counted, never a crash and never a silent
  migration.
- **Safety**: cached entries are untrusted input — schemas are re-validated
  against the same `max_schema_bytes` ceilings as a live index at load
  (oversized → searchable name-only marker, schema refused with `-32008`,
  never truncated). The cache contains only what the gateway already held
  in memory (tool names, descriptions, input schemas from upstreams) —
  never environment values, credentials, call arguments, or results.
  Disabled and `future-remote-placeholder` upstreams never receive cached
  tools. Writes are atomic (temp file + `os.replace`) and best-effort: a
  cache write failure never breaks a live call.
- **Audit**: with the cache enabled, startup appends one `cache_loaded` row
  (counts of loaded/corrupt/expired entries, loaded upstream names, the
  cache file's basename and SHA-256) and every cache rewrite appends a
  `cache_refresh` row (upstream, tool count, upstream server version, new
  file SHA-256). Schema bodies and local paths are never written.

Proven by `tests/test_mcp_warm_cache.py`, including the default-off proof
(no cache file is touched without the flag) and the no-spawn cache-hit
proof (the spawn marker stays absent while `tools_search`/`tools_schema`
answer from cache).
