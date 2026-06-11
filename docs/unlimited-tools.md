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

## Why this reduces context load — measured

`tests/test_mcp_context_budget.py` indexes 40 fake upstream tools with
realistic ~2 KB input schemas and measures the JSON payload sizes
(`pytest -s tests/test_mcp_context_budget.py` reprints them):

| Payload | Bytes | Share of full dump |
| --- | ---: | ---: |
| Full all-schemas dump (what a host pays without the gateway) | 90,420 | 100% |
| Gateway `tools/list` — the **standing** cost, only 3 meta-tools | 1,268 | 1.4% |
| One `tools_search` response (limit 8, metadata only) | 1,306 | 1.4% |
| One `tools_schema` response (exactly one schema) | 2,250 | 2.5% |

The test also asserts the structural guarantees behind the numbers: the
gateway's `tools/list` exposes **only** `tools_search` / `tools_schema` /
`tools_call` (no upstream schema text), `tools_search` responses never
contain an `inputSchema`, and `tools_schema` returns exactly one schema.
The gap widens with every additional upstream: the standing cost stays
constant at the three meta-tool schemas.

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
- Every upstream interaction has a hard deadline (startup 20 s, request 30 s
  by default; configurable globally or per upstream). A timed-out or
  garbage-talking upstream is terminated and the call is refused with a
  structured JSON-RPC error (`-32001`…`-32010`, see
  [mcp-gateway.md](mcp-gateway.md)) — garbage is never relayed.
- All upstreams are terminated when the gateway shuts down (terminate, then
  kill after 5 s).
- The tool index is cached in-memory per gateway process.

## Privacy boundaries (v1)

- **stdio-only**: the gateway and the skills server speak newline-delimited
  JSON-RPC 2.0 (or LSP-style `Content-Length` framing, auto-detected) on
  stdin/stdout. No sockets, no HTTP listeners.
- **Local-only**: upstreams are local subprocesses from your own config file.
  No hosted calls, no hosted gateway, no OAuth upstreams in v1.
- **Tools capability only**: no MCP resources or prompts in v1.
- **No automatic telemetry**: the gateway writes only the local redacted
  audit log you configure; it does not send usage, prompts, queries, tool
  inputs, or results to hosted services.
- **Env hygiene**: upstreams get a from-scratch environment — a fixed minimal
  base set plus only the variable **names** in `env_allowlist`, copied from
  your local environment at spawn time and never written to any log. There is
  no literal env value map (the v1 `env` map is rejected at config load).
- **E07 security model contract**: the upstream config format is specified in
  [mcp-upstream-security-model.md](mcp-upstream-security-model.md) and
  `schemas/mcp-upstream-config.schema.json` and enforced by the gateway:
  `local-restricted` by default, no shell execution, names-only
  `env_allowlist` forwarding (wildcards impossible), over-limit
  schema/response payloads refused instead of truncated, startup/request
  timeouts capped, and OAuth, remote upstreams, MCP resources, and MCP
  prompts out of scope. MCP v1 schemas/configs are alpha and may break before
  v0.6.
- **Audit with redaction**: every meta-tool call — success or refusal — is
  appended to a local JSONL audit log
  (`<library>/.learning/mcp-audit.jsonl` by default) with `ts`, `tool`,
  `upstream`, `duration_ms`, `ok`. Argument values under sensitive keys
  (token/secret/key/password/proof/auth/credential/cookie/session/signature/
  cert/private/prompt/env/body/content/query/text) are redacted recursively; string
  values that *look* like secrets (`Bearer …`, JWTs, PEM blocks, long
  hex/base64 blobs) are redacted even under harmless keys; env values, skill
  bodies, prompts, and tool results are never written; local paths are
  scrubbed from every audited string. See `unlimited_skills/mcp/audit.py`
  (`redact()` is a pure, testable function) and the leak-grep test
  `tests/test_mcp_gateway.py::test_audit_file_never_leaks_secrets`.

## Upstream security model

`v0.4.3-alpha` is the MCP upstream enforcement integration gate. It verifies
disabled and future remote upstream refusals before spawn, command allowlists,
names-only environment forwarding, schema/response size refusals, startup
timeout and request timeout bounds, audit rotation, audit redaction, and the
continued absence of OAuth, remote upstreams, resources, prompts, hosted
gateway mode, production hosted calls, automatic telemetry, and shell
execution.

The contract for upstream trust levels, command and environment
allowlisting, size/timeout bounds, audit retention, extended refusal codes
(`-32005`…`-32010`), the threat model, and the OAuth / resources+prompts
gates is specified in
[mcp-upstream-security-model.md](mcp-upstream-security-model.md) and
enforced by the gateway (see the "Config enforcement" section of
[mcp-gateway.md](mcp-gateway.md)). It strictly tightens the v1 boundaries
above and never weakens them.

## Permissioned tool profiles (design)

[mcp-permissioned-tool-profiles.md](mcp-permissioned-tool-profiles.md) (E09,
design only — not yet enforced) adds named per-agent / per-team / per-runtime
tool profiles on top of the upstream security model: a profile controls which
upstream tools an agent can see (`tools_search` / `tools_schema`) and which
it can call (`tools_call`), default-deny when active, fail-closed when
missing or invalid. The open behavior above remains the default (no-profiles
mode) until v0.6.

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

## Auditing what the gateway did

The redacted local audit log the gateway writes can be inspected with
`unlimited-skills mcp audit-report` — a read-only local report (summary,
refusal codes, upstream health, profile usage, redaction self-check) over
the active file and its rotated generations. See
[mcp-audit-inspector.md](mcp-audit-inspector.md).
