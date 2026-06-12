# Quickstart: the one-command golden path

```bash
pip install unlimited-skills
unlimited-skills quickstart
```

`unlimited-skills quickstart` walks a fresh install through the whole value
loop in one command. Every step is idempotent: rerunning it on a configured
system reports status and changes nothing. Everything is local — no
registration, no hosted calls, no uploads.

## What it does

1. **Library** — when the library root (`~/.unlimited-skills/library` by
   default) has zero skills, the bundled `ecc` and `superpowers` packs from
   the installed package or repo checkout are imported and the lexical index
   is rebuilt. A non-empty library is left untouched.
2. **First search** — one lexical search (your query or a demo query) with
   the top 3 hits, proving retrieval works end to end. Pass your own query:
   `unlimited-skills quickstart "postgres migration locks"`.
3. **MCP context savings** — your real numbers: how many bytes/tokens of MCP
   tool schemas your Claude Code configuration loads into every session, and
   what the same session costs behind the Unlimited Tools gateway
   (3 meta-tools). See below.
4. **Next steps** — the exact commands to register the gateway with Claude
   Code and to run the guided setup wizard.

Flags: `--json` (machine-readable report), `--skip-mcp-check`,
`--timeout SECONDS` and `--claude-config PATH` for the savings step.

## `unlimited-skills mcp savings`

The savings step is also a standalone command:

```bash
unlimited-skills mcp savings
unlimited-skills mcp savings --json
```

It reads your real Claude Code MCP configuration — the top-level
`mcpServers` in `~/.claude.json`, every per-project `mcpServers` section,
and each known project's `.mcp.json` — then, for each stdio server, spawns
it exactly the way the host would (same command, args, and configured env),
runs the MCP `initialize` handshake, requests `tools/list`, and measures the
full listing payload in bytes. That payload (names + descriptions + complete
input schemas) is what the host injects into your context at session start.
The summed standing cost is compared against the gateway's own `tools/list`
(only the 3 meta-tool schemas), measured live.

Example output:

```text
MCP context savings (measured locally; nothing is uploaded)

Configured MCP servers:
  codex    2 tools      2,577 bytes  (~644 tokens)

Right now: ~644 tokens of MCP tool schemas load into every session.
With the Unlimited Tools gateway: ~317 tokens (3 meta-tools).
Savings: ~327 tokens per session (50.8%).
```

Notes:

- **Token heuristic**: `est_tokens = bytes / 4` — roughly 4 bytes per token
  for English JSON payloads. It is an orientation estimate, not an exact
  tokenizer count.
- **Unreachable servers** become a `skipped (not reachable)` row, never a
  failure; remote (`sse`/`http`) servers are `skipped (remote server; not
  measured)`; opaque shell-string commands are `skipped (unsupported
  command)` (a measurement never runs a shell).
- **No MCP servers configured**: the command prints the lab benchmark
  instead (40 realistic tools: 90,420 bytes full dump vs 1,268 bytes gateway
  standing cost — see [unlimited-tools.md](unlimited-tools.md)).
- **Privacy**: everything runs locally and nothing is uploaded. The output
  contains only server names, tool counts, byte sizes, and fixed status
  strings — never schema contents, never spawn commands or args, never env
  names or values. Configured env values are forwarded to the measured child
  process exactly like the host forwards them and are never logged or
  printed. A numbers-only snapshot is appended to the local learning log
  (`<library>/.learning/events.jsonl`).

## After quickstart

Register the gateway with Claude Code. Start with a redacted dry-run so you
can inspect the planned `.mcp.json` change before any write:

```bash
unlimited-skills mcp install --claude-code --dry-run
unlimited-skills mcp install --claude-code
unlimited-skills mcp install status
```

The installer validates JSON before and after writes, creates a timestamped
backup before changing an existing config, preserves other `mcpServers`, and
redacts env values and local paths in dry-run output. It creates an empty
gateway config on first install. Add upstream MCP servers there with
`env_allowlist` variable names, not literal secret values; see
[unlimited-tools.md](unlimited-tools.md) and [mcp-gateway.md](mcp-gateway.md).

Remove the Claude Code gateway entry with:

```bash
unlimited-skills mcp uninstall --claude-code
```

Run the guided first-run wizard and diagnostics:

```bash
unlimited-skills setup --local-only
unlimited-skills doctor
```

For agent-specific installers (router skill, `CLAUDE.md`/`AGENTS.md`
patching, migrations), see the [README](../README.md) and
[first-run-setup.md](first-run-setup.md).
