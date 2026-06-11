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

Validated against `schemas/mcp-gateway-config.schema.json`; a working sample
is at `examples/mcp/gateway-config.example.json`:

```json
{
  "schema_version": 1,
  "startup_timeout_seconds": 20,
  "request_timeout_seconds": 30,
  "upstreams": [
    {
      "name": "github",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "%GITHUB_PERSONAL_ACCESS_TOKEN%" },
      "request_timeout_seconds": 60,
      "tools": [
        { "name": "create_issue", "description": "Create a GitHub issue in a repository" }
      ]
    }
  ]
}
```

- `name` — unique id; tools are addressed as `<name>.<tool>`.
- `command` / `args` — the upstream stdio MCP server process. stdio only:
  no URLs, no OAuth upstreams in v1.
- `env` — extra environment for the upstream. Values may reference local
  environment variables (`%VAR%` or `$VAR`); they are expanded from
  `os.environ` at spawn time and **never logged**.
- `tools` — optional pre-declared names + descriptions so `tools_search` can
  match this upstream **before it is ever spawned**. Without it, an upstream
  becomes searchable after its first lazy spawn or a `tools_search` call with
  `refresh: true`.
- `startup_timeout_seconds` / `request_timeout_seconds` — per-upstream
  deadlines (positive numbers). May also be set at the top level as defaults
  for all upstreams. Built-in defaults: **20 s** for spawn + `initialize`
  handshake, **30 s** per request.

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
  credential/cookie/session/signature/cert/private/prompt/env/body/content
  (case-insensitive) are replaced with `[redacted]`, recursively through
  nested dicts and lists;
- string **values** that look like secrets are redacted even under harmless
  keys: `Bearer …`/`Basic …` headers, JWTs, PEM private-key/certificate
  blocks, long hex or base64-like blobs;
- env values are never passed to the audit layer at all (and env-shaped keys
  are redacted as defense in depth);
- prompts, skill bodies, and upstream tool results are never written — only
  call shape, timing, and status;
- local filesystem paths (drive, UNC, `~/…`, POSIX home/tmp) are scrubbed
  from every audited string, including error strings.

Proven by `tests/test_mcp_gateway.py::test_audit_file_never_leaks_secrets`,
which greps a generated audit file for token/bearer/password/proof/prompt/
skill-body/env/local-path plaintext after a representative call.

## Upstream security model (E07 design)

How upstreams *should* be configured, allowlisted, isolated, limited, and
audited going forward — trust levels (`disabled` / `local-restricted` /
`local-trusted` / `future-remote-placeholder`), a names-only env allowlist
replacing the `env` value map above, command allowlisting, size caps with
refusal-not-truncation, audit rotation, the extended refusal codes
`-32005`…`-32010`, and the 9-vector threat model — is specified in
[mcp-upstream-security-model.md](mcp-upstream-security-model.md)
(design only; this page documents the implemented v1 behavior).
