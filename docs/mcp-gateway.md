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
