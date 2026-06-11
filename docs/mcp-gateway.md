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
  "upstreams": [
    {
      "name": "github",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "%GITHUB_PERSONAL_ACCESS_TOKEN%" },
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

## Lifecycle

Upstreams spawn lazily on first need, stay alive for reuse, and are terminated
when the gateway loop ends. The tool index is cached in-memory per gateway
process.

## Audit log

Every meta-tool call appends one JSON line: `ts`, `tool`, `upstream`,
`duration_ms`, `ok`, plus redacted `args` and a path-scrubbed `error` on
failure. Redaction (pure function `redact()` in
`unlimited_skills/mcp/audit.py`):

- values of argument keys matching token/secret/key/password/proof/
  authorization (case-insensitive) are replaced with `[redacted]`;
- env values are never passed to the audit layer at all;
- skill bodies and upstream tool results are never written — only call shape,
  timing, and status;
- local filesystem paths are scrubbed from error strings.
