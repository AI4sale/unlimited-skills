# Unlimited Tools: 3 meta-tools instead of a context-window full of schemas

## The problem: MCP tool schemas eat your context

Every MCP server an agent host (Claude Code, Codex, Hermes, OpenClaw) connects
to dumps its full tool list — names, descriptions, and complete JSON input
schemas — into the agent's context window at session start. A realistic
multi-server setup (GitHub + filesystem + browser + database + issue tracker)
costs **30,000–200,000 tokens before the agent has read a single line of your
task**. That budget is gone on every turn, whether or not any of those tools
are ever called.

This is the same context-pressure problem Unlimited Skills already solves for
skill libraries: do not preload everything, retrieve on demand.

## The model: 3 meta-tools

`unlimited-skills mcp gateway` is a single stdio MCP server that fronts all of
your upstream MCP servers and exposes exactly three tools:

| Meta-tool | What it returns | What it never returns |
| --- | --- | --- |
| `tools_search` | Matching upstream tool **names + descriptions** (fully qualified as `upstream.tool`) | Input schemas |
| `tools_schema` | The `inputSchema` of exactly **one** tool | Other tools' schemas |
| `tools_call` | The relayed result of **one** upstream call | — |

The agent's standing context cost drops to the three small meta-tool schemas.
Full upstream schemas are retrieved lazily, one at a time, only when the agent
has already decided which tool it needs.

A companion server, `unlimited-skills mcp serve`, applies the same model to the
skill library itself: `skills_search` (metadata-only hits), `skills_view` (one
capped body), `skills_use` (view + a local learning event — never script
execution). See [mcp-server.md](mcp-server.md) and [mcp-gateway.md](mcp-gateway.md).

## Lazy upstream lifecycle

- Upstreams are **not** spawned at gateway startup.
- `tools_search` searches the in-memory index (pre-declared `tools` entries
  from the config plus anything already indexed live) and does **not** spawn
  anything by default; `refresh: true` spawns and indexes every upstream.
- The first `tools_schema` / `tools_call` that targets an upstream spawns it
  (subprocess stdio, `initialize` handshake, `tools/list` to index), then keeps
  it alive for reuse.
- All upstreams are terminated when the gateway shuts down.
- The tool index is cached in-memory per gateway process.

## Privacy boundaries (v1)

- **stdio-only**: the gateway and the skills server speak newline-delimited
  JSON-RPC 2.0 (or LSP-style `Content-Length` framing, auto-detected) on
  stdin/stdout. No sockets, no HTTP listeners.
- **Local-only**: upstreams are local subprocesses from your own config file.
  No hosted calls, no OAuth upstreams in v1.
- **Tools capability only**: no MCP `resources` or `prompts` in v1.
- **Env hygiene**: upstream `env` values may reference `%VAR%` / `$VAR`; they
  are expanded from your local environment at spawn time and are never written
  to any log.
- **Audit with redaction**: every meta-tool call is appended to a local JSONL
  audit log (`<library>/.learning/mcp-audit.jsonl` by default) with `ts`,
  `tool`, `upstream`, `duration_ms`, `ok`. Argument values for keys matching
  token/secret/key/password/proof/authorization are redacted; env values, skill
  bodies, and tool results are never written; local paths are scrubbed from
  error strings. See `unlimited_skills/mcp/audit.py` (`redact()` is a pure,
  testable function).

## Quick start

```bash
# Skills server over your library
unlimited-skills mcp serve

# Gateway over your upstream MCP servers
unlimited-skills mcp gateway --config examples/mcp/gateway-config.example.json
```

Claude Code registration example (`.mcp.json`):

```json
{
  "mcpServers": {
    "unlimited-skills": {
      "command": "unlimited-skills",
      "args": ["mcp", "serve"]
    },
    "unlimited-tools": {
      "command": "unlimited-skills",
      "args": ["mcp", "gateway", "--config", "~/.unlimited-skills/gateway-config.json"]
    }
  }
}
```

## Performance and rewrite path

The v1 server and gateway are intentionally Python: MCP traffic is I/O-bound JSON-RPC glue, per-call overhead is microseconds against seconds of upstream/tool work, and the search core they reuse lives in this package. The protocol boundary is pinned by JSON schemas (`schemas/mcp-*.schema.json`) and fixture tests (`tests/test_mcp_protocol.py` and friends), so if a hosted multi-tenant gateway or single-binary distribution ever justifies it, the protocol/gateway layer can be rewritten in a compiled language (e.g. Rust) as a drop-in behind the same contracts without touching the library/search core. Revisit when (a) the gateway becomes a hosted product or (b) no-Python single-file install becomes a distribution goal.

