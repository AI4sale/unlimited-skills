# MCP skills server (`unlimited-skills mcp serve`)

A zero-dependency stdio MCP server over the local skill library. It is the MCP
twin of the `search` / `view` / `use` CLI commands, built for agent hosts that
speak MCP (Claude Code, Codex, Hermes, OpenClaw). See
[unlimited-tools.md](unlimited-tools.md) for the context-pressure rationale.

## Running

```bash
unlimited-skills mcp serve                 # default library root
unlimited-skills --root D:\skills mcp serve
```

The server reads JSON-RPC 2.0 from stdin and writes responses to stdout.
Startup diagnostics go to stderr only. There is no network listener.

## Protocol

- JSON-RPC 2.0 with the MCP lifecycle: `initialize` (returns
  `protocolVersion` `2024-11-05`, `capabilities: {tools: {}}`, `serverInfo`
  with the package version), `notifications/initialized`, `tools/list`,
  `tools/call`, `ping`.
- Framing is auto-detected from the first bytes: newline-delimited JSON
  (Claude Code and most MCP hosts) or LSP-style `Content-Length` headers.
  Responses use the detected style.

### Error model and hard limits

Shared by this server and the gateway (`unlimited_skills/mcp/protocol.py`):

| Code | When |
| --- | --- |
| `-32700` | Unparseable frame: invalid JSON, invalid/out-of-range `Content-Length` header, frame over the 5 MB limit, header over 8 KB / more than 32 header lines |
| `-32600` | Not a JSON-RPC 2.0 request: missing/wrong `jsonrpc`, missing or non-string `method`, non-object message, or a **batch request** (JSON arrays are rejected cleanly — batching is not supported) |
| `-32601` | Unknown method |
| `-32602` | Malformed params (non-object `params`/`arguments`, unknown tool name) |
| `-32603` | Unexpected internal error; the loop answers and keeps serving (exception details are not leaked) |
| `-32001`…`-32004` | Gateway upstream refusals — see [mcp-gateway.md](mcp-gateway.md) |

Hardened behaviors, each covered in `tests/test_mcp_protocol.py`:

- malformed JSON and oversized frames produce a `-32700` error and the stream
  resynchronizes to the next newline — never a crash, never a hang;
- notifications (no `id`) are never answered; unknown notifications are
  cleanly ignored;
- EOF mid-message is a clean shutdown (no garbage response);
- tool handler failures are MCP tool results with `isError: true`;
  infrastructure refusals (`RefusalError`) are JSON-RPC error responses.

Implementation: `unlimited_skills/mcp/protocol.py` (`StdioServer`) and
`unlimited_skills/mcp/server.py` (tool registry). No external MCP SDK.

## Tools

### `skills_search`

Args: `query` (required), `limit` (1–20, default 8), `mode`
(`lexical` | `hybrid`, default `lexical`).

Returns metadata-only hits: `name`, `collection`, `description`, `score`, and
`library_path` (relative to the library root). **Never** returns skill bodies
or absolute local paths. `hybrid` uses the local vector sidecar when the
optional vector stack is installed and degrades to lexical otherwise.

### `skills_view`

Args: `name` (required).

Returns frontmatter metadata plus the body of exactly one skill, capped at
16,000 characters with an explicit truncation marker.

### `skills_use`

Args: `name` (required), optional `query` and `task` labels.

Same as `skills_view`, plus appends a `skill_used` event to the local
learning log (`<library>/.learning/events.jsonl`, `source: "mcp"`).

**Safety**: `skills_use` only reads SKILL.md text. It never executes scripts,
shell commands, or any code referenced by a skill — the agent decides what to
do with the returned text, exactly as with `unlimited-skills view`.

## Configuration schema

`schemas/mcp-server-config.schema.json` documents the server's tunable shape
(library root, view cap, search limit cap). v1 takes these from the CLI
`--root` flag and built-in defaults.
