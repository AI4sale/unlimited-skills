# MCP upstream configuration and security model

**Status: DESIGN (E07).** This document specifies how Unlimited Tools
configures, allowlists, isolates, limits, and audits upstream MCP servers.
Nothing in this document is implemented by the E07 change itself — it is the
security-reviewed contract that future implementation work (and the OAuth /
remote / resources / prompts gates) must satisfy. The current implemented
behavior is documented in [mcp-gateway.md](mcp-gateway.md) and
[unlimited-tools.md](unlimited-tools.md); this design strictly tightens it and
never weakens any existing guarantee (redaction, structured refusals,
no-schema-dump).

Artifacts in this change:

- this document;
- `schemas/mcp-upstream-config.schema.json` — JSON Schema (draft 2020-12) for
  the upstream config format below;
- `examples/mcp/upstreams.example.json` — an annotated example that validates
  against the schema (`tests/test_mcp_upstream_config_schema.py`).

Compatibility note: the project has almost no users and backward compatibility
before v0.6 is explicitly not required. This design replaces the v1
`env` value-expansion map with a strictly safer allowlist model and adds
mandatory trust levels; there are no legacy shims.

## Design goals

1. **Default deny.** An upstream gets nothing it was not explicitly granted:
   no environment variables, no working directory of the gateway, no shell,
   no network expectations, no unbounded payloads.
2. **Refuse loudly, never degrade silently.** Every limit violation is a
   structured JSON-RPC refusal with a named code — never truncation, never
   garbage relay, never a hang.
3. **The agent context stays small and clean.** Upstream schemas enter the
   agent's context one at a time, size-capped, and only on request.
4. **Everything observable, nothing sensitive.** Every meta-tool call is
   audited; secrets, prompts, results, env values, and local paths are never
   written, even redacted.

## Trust levels

Every upstream carries exactly one `trust_level`. The default is
`local-restricted` — the most restrictive level under which a correctly
packaged local upstream still works. Levels only ever *remove* restrictions
relative to the level below; nothing is permitted at a lower level that a
higher level refuses.

### `disabled`

The upstream is configuration-only. It is never spawned, never indexed, and
never appears in `tools_search` results (including its pre-declared `tools`
entries). Any `tools_schema` / `tools_call` addressing it is refused with
`upstream_disabled` (`-32005`). Setting `enabled: false` on any upstream is
equivalent to forcing this level regardless of its declared `trust_level`.

Use for: keeping an upstream's config around while it is under review.

### `local-restricted` (default)

A local stdio subprocess with the tightest constraints that still run a
correctly installed server:

- `command` **must be an absolute path** to an existing file. Bare binary
  names (PATH lookup) are refused with `command_not_allowed` (`-32006`).
- Environment: the child process receives the **minimal base environment**
  (see "Environment forwarding") plus only the variables named in
  `env_allowlist`. An empty or absent allowlist forwards nothing beyond the
  base set.
- `cwd`: a gateway-managed per-upstream scratch directory by default; an
  explicit `cwd` must be an absolute path to an existing directory.
- Size limits: `max_schema_bytes` and `max_response_bytes` may be set up to
  the restricted ceilings (256 KiB / 1 MiB); higher values are refused at
  config load time.
- Timeouts: per-upstream overrides allowed within the global hard bounds.

Use for: any upstream you did not author yourself. This is the level a new
config entry should start at.

### `local-trusted`

Everything `local-restricted` allows, plus:

- `command` may be a **bare known-binary name** resolved via PATH, drawn from
  the gateway's built-in known-runner list: `node`, `npx`, `bunx`, `deno`,
  `python`, `python3`, `uv`, `uvx`. Anything else still requires an absolute
  path. The list is fixed in code — it is not user-extensible via config,
  so a tampered config cannot promote `bash`, `cmd`, or `powershell` into a
  "known binary".
- Size limits may be raised up to the trusted ceilings (1 MiB schema /
  8 MiB response).

Still **never**: shell interpretation, wildcard env forwarding, network
transports, resources/prompts.

Use for: upstreams you maintain or have reviewed, launched through a standard
runtime launcher.

### `future-remote-placeholder`

A reserved enum value so that configs can be written ahead of the remote /
OAuth gates without inventing a new schema. The gateway treats it as
**stricter than `disabled` in messaging**: every operation addressing such an
upstream — including indexing its pre-declared `tools` — is refused with
`trust_level_violation` (`-32010`) and an error message naming the unopened
gate. No code path may spawn, connect, or perform any I/O for this level
until the corresponding gate (see "Future gates") ships and defines its own
semantics.

### Trust level comparison

| Capability | `disabled` | `local-restricted` | `local-trusted` | `future-remote-placeholder` |
| --- | --- | --- | --- | --- |
| Appears in `tools_search` | no | yes | yes | no |
| Spawned as subprocess | never | lazily | lazily | never |
| `command` form | — | absolute path only | absolute path or known-binary name | — |
| Env beyond base set | — | `env_allowlist` names only | `env_allowlist` names only | — |
| Schema size ceiling | — | 256 KiB | 1 MiB | — |
| Response size ceiling | — | 1 MiB | 8 MiB | — |
| Refusal when addressed | `upstream_disabled` | per-limit codes | per-limit codes | `trust_level_violation` |

## Upstream config file format

Validated against `schemas/mcp-upstream-config.schema.json` (draft 2020-12).
Unknown keys are rejected (`additionalProperties: false`), so a typo like
`env_alowlist` fails at load time instead of silently forwarding nothing.
`comment` fields are accepted everywhere an object is and carry no semantics —
JSON has no comments, annotations live there.

Complete annotated example (also at `examples/mcp/upstreams.example.json`):

```json
{
  "schema_version": 1,
  "comment": "Upstream config for the Unlimited Tools gateway. Defaults below apply to every upstream unless overridden per entry.",
  "startup_timeout_seconds": 20,
  "request_timeout_seconds": 30,
  "audit_max_bytes": 10485760,
  "audit_max_files": 5,
  "upstreams": [
    {
      "name": "github",
      "comment": "Reviewed first-party server, launched via npx -> local-trusted. Forwards exactly one secret by NAME; the gateway never logs its value.",
      "trust_level": "local-trusted",
      "enabled": true,
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env_allowlist": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
      "request_timeout_seconds": 60,
      "max_schema_bytes": 131072,
      "max_response_bytes": 2097152,
      "audit_level": "standard",
      "tools": [
        { "name": "create_issue", "description": "Create a GitHub issue in a repository" },
        { "name": "search_repositories", "description": "Search GitHub repositories" }
      ]
    },
    {
      "name": "filesystem",
      "comment": "Third-party server -> default local-restricted: absolute command path, no env forwarding, explicit cwd, tight response cap.",
      "trust_level": "local-restricted",
      "enabled": true,
      "command": "/usr/bin/node",
      "args": ["/opt/mcp/server-filesystem/index.js", "/home/user/projects"],
      "cwd": "/home/user/projects",
      "env_allowlist": [],
      "max_schema_bytes": 65536,
      "max_response_bytes": 524288,
      "audit_level": "standard"
    },
    {
      "name": "hosted-search",
      "comment": "Reserved slot for a remote upstream. Refused with trust_level_violation until the OAuth/remote gate opens; enabled:false keeps it inert either way.",
      "trust_level": "future-remote-placeholder",
      "enabled": false,
      "command": "/usr/bin/false",
      "audit_level": "minimal"
    }
  ]
}
```

### Field reference

Top level:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `schema_version` | const `1` | required | Format version. |
| `startup_timeout_seconds` | number, 0 < n ≤ 120 | 20 | Default spawn + `initialize` deadline (matches the implemented `DEFAULT_STARTUP_TIMEOUT`). |
| `request_timeout_seconds` | number, 0 < n ≤ 300 | 30 | Default per-request deadline (matches `DEFAULT_REQUEST_TIMEOUT`). |
| `audit_max_bytes` | integer, 64 KiB – 100 MiB | 10 MiB | Rotate the JSONL audit log when it exceeds this size. |
| `audit_max_files` | integer, 1–20 | 5 | Rotated generations kept (`mcp-audit.jsonl.1` … `.N`). |
| `comment` | string | — | Annotation, ignored. |
| `upstreams` | array | required | Upstream entries, unique `name` each. |

Per upstream:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `name` | `^[A-Za-z0-9][A-Za-z0-9_-]*$` | required | Unique id; tools addressed as `<name>.<tool>`. |
| `enabled` | boolean | `true` | `false` forces `disabled` semantics regardless of `trust_level`. |
| `trust_level` | enum (4 values above) | `local-restricted` | Governs command form, env, ceilings. |
| `command` | string, min length 1 | required | Executable. Absolute path, or known-binary name at `local-trusted` only. Never a shell line. |
| `args` | array of strings | `[]` | Passed verbatim as an argv vector. No shell expansion, no splitting. |
| `cwd` | string | managed scratch dir | Absolute path to an existing directory. Relative paths are refused at load time. |
| `env_allowlist` | array of `^[A-Za-z_][A-Za-z0-9_]*$`, unique, ≤ 32 | `[]` | Names of variables copied from the gateway's environment into the child. **Names only — never values, never wildcards.** The pattern itself makes `*` and `PREFIX_*` unrepresentable. |
| `startup_timeout_seconds` | number, 0 < n ≤ 120 | top-level | Per-upstream override, bounded. |
| `request_timeout_seconds` | number, 0 < n ≤ 300 | top-level | Per-upstream override, bounded. |
| `max_schema_bytes` | integer, 1 KiB – 1 MiB | 64 KiB | Cap on one tool's serialized `inputSchema`; restricted ceiling 256 KiB. |
| `max_response_bytes` | integer, 1 KiB – 8 MiB | 256 KiB | Cap on one serialized `tools/call` result; restricted ceiling 1 MiB. |
| `audit_level` | `"minimal"` \| `"standard"` | `"standard"` | See "Audit". There is deliberately no `"off"`. |
| `tools` | array of `{name, description?}` | `[]` | Pre-declared index so `tools_search` matches before first spawn. |
| `comment` | string | — | Annotation, ignored. |

The JSON Schema enforces the hard bounds (every numeric ceiling above);
the **trust-level ceilings** (256 KiB / 1 MiB at `local-restricted`) are
semantic rules enforced by the gateway at config load time, refused as
`GatewayConfigError` before any process is spawned.

## Command allowlist model

Which executables may run as upstreams:

1. **No shell, ever.** The command is spawned as an argv vector
   (`[command, *args]`), exactly as the implemented gateway already does.
   There is no `shell=True` equivalent, no string concatenation into a shell
   line, no interpretation of `|`, `&&`, `%VAR%`, `$(...)`, or quoting in
   either `command` or `args`.
2. **Absolute-path-or-known-binary.** At `local-restricted` the command must
   be an absolute path to an existing file. At `local-trusted` it may instead
   be one of the fixed known-runner names (`node`, `npx`, `bunx`, `deno`,
   `python`, `python3`, `uv`, `uvx`) resolved via PATH. Everything else is
   refused with `command_not_allowed` (`-32006`) at spawn time, and flagged
   at config load time where statically detectable.
3. **Explicitly refused command shapes** at every trust level: empty or
   whitespace command; relative paths (`./server`, `..\\x.exe`); shell
   binaries as upstream commands (`sh`, `bash`, `zsh`, `cmd`, `cmd.exe`,
   `powershell`, `pwsh`, `powershell.exe`) — an MCP server is never a shell;
   paths under world-writable temp directories at `local-restricted`.
4. **The known-runner list lives in code, not config.** A config file cannot
   extend it; widening it requires a reviewed code change.

## Local command execution constraints

- **Process model:** plain subprocess with piped stdin/stdout; stderr is
  discarded (never relayed into the protocol stream or the agent context).
  One reader thread per upstream enforces hard deadlines, exactly as
  implemented in `unlimited_skills/mcp/gateway.py`.
- **Argument passing:** `args` strings are passed through byte-for-byte as
  argv entries. The gateway performs no templating, no `%VAR%`/`$VAR`
  expansion anywhere (this *removes* the v1 env-value expansion — see
  "Environment forwarding"), and no path rewriting.
- **Working directory:** the gateway's own cwd is never inherited. Default is
  a per-upstream scratch directory created under the library's runtime dir;
  an explicit `cwd` must be absolute and existing. This keeps a hostile
  upstream from discovering the user's project location through `getcwd()`.
- **No network expectations:** the gateway makes no network connections on
  behalf of upstreams, opens no listeners, and provides no proxy. If an
  upstream itself reaches the network (e.g. the GitHub server calling the
  GitHub API), that is the upstream's own documented behavior under the
  user's OS controls — the trust-level decision is where the user accepts
  that. Nothing in the gateway facilitates or hides it.
- **Lifecycle:** lazy spawn on first need, reuse while alive, terminate on
  shutdown (terminate, then kill after 5 s); a timed-out or garbage-talking
  upstream is terminated immediately and never reused mid-stream.

## Environment forwarding

Forward **nothing** by default. The child environment is built from scratch:

1. **Minimal base set** required for processes to function at all, copied
   from the gateway's environment when present: `PATH`, `HOME`, `TMPDIR`,
   `TEMP`, `TMP`, `LANG`, `LC_ALL`, and on Windows `SYSTEMROOT`,
   `SYSTEMDRIVE`, `COMSPEC` is **excluded** (no shell), `USERPROFILE`,
   `APPDATA`, `LOCALAPPDATA`, `PATHEXT`, `NUMBER_OF_PROCESSORS`. The base
   set is fixed in code and documented; it never includes credential-shaped
   variables.
2. **Plus the `env_allowlist` names**, copied verbatim from the gateway's
   own environment. Names only: the config never contains a secret value, so
   a leaked or committed config file leaks no credential. A name listed but
   unset in the parent environment is simply absent in the child (not an
   error — but it is noted in the audit entry shape as `env_missing` count).
3. **No wildcards, no prefixes, no value literals.** The schema pattern for
   allowlist entries makes `*` unrepresentable; there is no `env` map of
   literal values at all in this format. Requests that would require broader
   forwarding are refused with `env_forwarding_denied` (`-32007`).

This deliberately drops v1's `env: {"X": "%X%"}` literal-with-expansion map:
the allowlist expresses the same intent ("forward this one variable") with a
strictly smaller attack surface and zero chance of a value ending up in a
config file. (No compat shim — pre-v0.6 break, accepted.)

## Schema and response size limits

Caps exist so one hostile or buggy upstream cannot flood the agent's context
window or the gateway's memory. **On exceed, the gateway refuses the call
with a structured error — it never silently truncates**, because a truncated
JSON schema or half a tool result is worse than no result: the agent would
act on corrupt data without knowing it.

- `max_schema_bytes` (default 64 KiB): measured on the serialized
  `inputSchema` of the one tool requested by `tools_schema`, after
  `tools/list` indexing. Oversized schema → refusal `schema_too_large`
  (`-32008`); the refusal message includes the actual and allowed sizes so
  the agent can report it, but never the schema content itself.
- `max_response_bytes` (default 256 KiB): measured on the serialized
  `tools/call` result before relay. Oversized result → refusal
  `response_too_large` (`-32009`); the result is dropped, not trimmed.
- During indexing (`tools/list`), an individual tool whose schema exceeds the
  cap is indexed by name and description only and marked oversized; its
  schema can never be fetched, only refused — search still finds it so the
  agent gets an explanatory refusal rather than a mysterious absence.
- Hard schema ceilings: 1 MiB schema / 8 MiB response, with the tighter
  trust-level ceilings at `local-restricted` (256 KiB / 1 MiB).

## Timeouts and resource limits

Tied to the implemented defaults in `gateway.py`
(`DEFAULT_STARTUP_TIMEOUT = 20.0`, `DEFAULT_REQUEST_TIMEOUT = 30.0`):

- **Startup** (spawn + `initialize` handshake): default 20 s, per-upstream
  override bounded to (0, 120] s.
- **Request** (every `tools/list`, `tools/call`): default 30 s, per-upstream
  override bounded to (0, 300] s. On timeout the upstream is terminated (its
  stream is out of sync) and the call refused with `-32002`, as today.
- **Bounded overrides** are new: v1 accepted any positive number; this design
  caps overrides so a config cannot effectively disable deadlines with
  `request_timeout_seconds: 9e9`. Values above the bound are a load-time
  config error.
- **One process per upstream, spawned lazily** — a config with 50 upstreams
  costs zero processes until tools are actually used, and at most one process
  per upstream ever (respawn only after termination).

## Audit

### Levels

| Level | Per call writes | Never writes |
| --- | --- | --- |
| `minimal` | `ts`, `tool`, `upstream`, `duration_ms`, `ok` | everything else |
| `standard` (default) | minimal + redacted `args` shape + path-scrubbed, length-capped `error` | see below |

There is intentionally **no `off`**: refusals and calls are always
observable. `minimal` exists for upstreams whose argument *shapes* are
themselves sensitive.

### Never written, even redacted, at any level

- environment variable **values** (the audit layer never receives them);
- upstream tool **results** and result fragments (only sizes/status);
- skill bodies and prompts;
- raw `inputSchema` content;
- unscrubbed local filesystem paths;
- the audit log never embeds another log's lines (control characters in
  audited strings are escaped by JSON encoding — one record is always
  exactly one line).

These extend the implemented redaction in `unlimited_skills/mcp/audit.py`
(`redact()`, `looks_secret()`, `scrub_paths()`), which stays in force
unchanged underneath both levels.

### Retention and rotation

The audit log is local-only JSONL (`<library>/.learning/mcp-audit.jsonl` by
default). Design: size-based rotation, configured by `audit_max_bytes`
(default 10 MiB) and `audit_max_files` (default 5). When the active file
exceeds the cap it is renamed to `.1` (shifting `.1`→`.2`, …), and the oldest
generation beyond `audit_max_files` is deleted. Rotation is local file
renames only; no compression dependency, no upload, no telemetry. Guidance:
keep defaults; raise `audit_max_files` rather than `audit_max_bytes` if you
need longer history, so any single file stays grep-friendly.

## Refusal codes

JSON-RPC `error.code` values, extending the implemented `-32001`…`-32004`
family in `gateway.py` contiguously (all within the JSON-RPC
implementation-defined server-error range):

| Code | Name | Meaning | Suggested agent behavior |
| --- | --- | --- | --- |
| `-32001` | `upstream_start_failed` | Upstream could not be spawned or failed its `initialize` handshake. | Report; do not retry more than once; suggest the user check the upstream's installation. |
| `-32002` | `upstream_timeout` | Upstream did not answer within its deadline; it has been terminated. | Retry once (the upstream respawns lazily); if it repeats, treat the upstream as down. |
| `-32003` | `upstream_protocol_error` | Upstream wrote malformed output; nothing was relayed; it has been terminated. | Do not retry with the same arguments; report the upstream as misbehaving. |
| `-32004` | `upstream_failed` | Upstream returned a JSON-RPC error or died mid-call. | Inspect the message; may be a per-call domain failure worth one retry with corrected arguments. |
| `-32005` | `upstream_disabled` | Upstream exists in config but is `disabled` (or `enabled: false`). | Do not retry. Tell the user the upstream is configured but switched off. |
| `-32006` | `command_not_allowed` | Upstream command violates the allowlist policy for its trust level (relative path, unknown bare name, shell binary, …). | Never retry. Surface to the user verbatim — this is a config security stop, not a transient fault. |
| `-32007` | `env_forwarding_denied` | A spawn would require environment forwarding beyond the allowlist (or a forbidden wildcard/literal-value form was configured). | Never retry. The user must extend `env_allowlist` deliberately. |
| `-32008` | `schema_too_large` | One tool's `inputSchema` exceeds `max_schema_bytes`; nothing was returned or truncated. | Do not fetch this schema again; call the tool only if its use is obvious from the description, otherwise tell the user. |
| `-32009` | `response_too_large` | A `tools/call` result exceeds `max_response_bytes`; it was dropped, not trimmed. | Retry only with arguments that plausibly shrink the result (filters, pagination, limits). |
| `-32010` | `trust_level_violation` | The operation is not permitted at the upstream's trust level (e.g. anything on `future-remote-placeholder`). | Never retry. Tell the user which gate/trust change would be required. |

Caller mistakes (unknown tool name, unqualified `tool`, non-object
`arguments`) remain MCP tool results with `isError: true`, not refusals, as
in the implemented error model. Every refusal still appends an `ok: false`
audit entry — no silent failures.

## Threat model

Nine vectors, each with the mitigating controls from this design:

| # | Vector | Description | Impact | Mitigations |
| --- | --- | --- | --- | --- |
| 1 | **Schema injection** | A hostile upstream embeds adversarial instructions ("ignore previous instructions…") in tool names, descriptions, or `inputSchema` text that the agent will read. | Agent manipulation, exfiltration via subsequent tool calls. | Schemas enter context only one at a time, on explicit request, size-capped (`max_schema_bytes`); `tools_search` returns names + descriptions only; `tools_schema` returns exactly one schema; no full dump ever; trust levels make "who wrote this schema" an explicit user decision. Residual risk: the one fetched schema is still attacker-authored text — hosts should render it as data, not instructions. |
| 2 | **Prompt leakage** | Agent prompts or task text flowing to an upstream or into logs. | Disclosure of user/business context to a third-party process or a file. | The gateway forwards only the explicit `arguments` object of one `tools_call` — never conversation context; audit redacts `prompt`-keyed and secret-shaped values and never writes prompts or bodies; `minimal` audit level for argument-sensitive upstreams. |
| 3 | **Tool output leakage** | Upstream results copied into the audit log or relayed to parties other than the caller. | Sensitive results (file contents, API data) persisted to disk or cross-leaked. | Results are never audited (only size/status/timing); results are relayed only to the requesting host over stdio; no telemetry, no hosted gateway; `max_response_bytes` bounds what can transit at all. |
| 4 | **Arbitrary command execution** | A tampered or careless config turns the gateway into a command runner (shell lines, relative paths, `cmd /c …`). | Full local code execution as the user. | No shell, ever (argv vector spawn); absolute-path-or-known-binary policy; shell binaries explicitly refused as commands; known-runner list fixed in code; `command_not_allowed` refusal; `additionalProperties: false` rejects smuggled keys. |
| 5 | **Env secret leakage** | The child inherits the gateway's full environment (cloud keys, tokens) or env values land in config/logs. | Credential theft by any upstream. | Forward-nothing default with a names-only `env_allowlist` (wildcards unrepresentable by schema pattern); fixed minimal base set; no literal env values in config at all; env values never written to any log (existing invariant, kept); `env_forwarding_denied` refusal. |
| 6 | **Local path leakage** | Working directory, library root, or user paths exposed to upstreams or written to logs. | Profiling of the user's machine and projects. | Upstreams never inherit the gateway cwd (managed scratch dir default); audit scrubs drive/UNC/POSIX-home paths from every string including errors (existing `scrub_paths`, kept); search hits contain no paths. |
| 7 | **Tool-name shadowing / confused deputy** | Upstream B registers a tool named like upstream A's (`create_issue`) hoping calls or trust meant for A route to B. | Calls and their arguments delivered to the wrong, hostile upstream. | All addressing is fully qualified `upstream.tool`; upstream names are unique (load-time duplicate rejection, implemented); the gateway never auto-selects an upstream for a bare tool name; search results always show the owning upstream. |
| 8 | **Resource exhaustion by hostile upstream** | Endless output, giant schemas/results, never-answering processes, spawn storms. | Gateway memory/CPU exhaustion, agent context flooding, denial of service. | Hard deadlines on every interaction (20 s / 30 s defaults, overrides bounded); reader-thread model means a silent upstream cannot hang the gateway (implemented); size caps with refusal-not-truncation; poisoned upstreams terminated immediately; one process per upstream, lazily. |
| 9 | **Audit log tampering / poisoning** | An attacker-influenced string injects fake JSONL lines (newlines/control chars) or unbounded data into the audit trail. | Forged audit history, log-based parser exploits, disk exhaustion. | One JSON-encoded object per line (encoding escapes newlines/control chars by construction); audited strings length-capped (`MAX_STRING_CHARS`/`MAX_ERROR_CHARS`, implemented); size-based rotation caps total disk; append-only writer; logs live under the local library, not a shared world-writable path. |

## Future gates

Both gates are **explicitly out of scope** for E07 and for any implementation
of this design. Until a gate ships, the corresponding config is refused
(`trust_level_violation`), not ignored.

### Gate A: OAuth / remote upstreams

May only open when all of the following hold:

1. A reviewed design exists for token storage (OS keychain or equivalent —
   never plaintext in config or library), token redaction in audit
   (`looks_secret` already catches bearer/JWT shapes; the gate must prove
   coverage for its token formats), and token lifetime/refresh handling.
2. A remote trust level with its own ceilings (TLS-only, host allowlist by
   exact name, no redirect-following across hosts) replaces
   `future-remote-placeholder` — the placeholder itself never becomes
   functional.
3. The no-telemetry and local-audit invariants are re-verified: remote
   transport must not introduce any callback, beacon, or hosted log path.
4. A leak-grep test in the style of `test_audit_file_never_leaks_secrets`
   passes for OAuth material (access/refresh tokens, auth codes, PKCE
   verifiers).

### Gate B: MCP `resources` and `prompts`

May only open when:

1. Per-trust-level capability flags exist (a `local-restricted` upstream does
   not get resources just because the gateway gains the feature).
2. Resource contents and prompt templates get the same treatment as tool
   results today: size-capped with refusal-not-truncation, never audited,
   never dumped wholesale into context (list metadata first, fetch one item
   on demand — the same shape as `tools_search`/`tools_schema`).
3. Prompt templates from upstreams are threat-modeled as vector 1 (schema
   injection) — they are attacker-authored text destined directly for the
   agent, which is strictly more dangerous than schemas.

## Invariants preserved

This design keeps every standing guarantee; an implementation that violates
any of these is wrong even if it matches the rest of the document:

- **stdio, local subprocess upstreams only** — no sockets, no HTTP, no OAuth
  until Gate A.
- **No telemetry** — nothing leaves the machine; the audit log is local and
  rotation never uploads.
- **No hosted gateway** — this is a local tool fronting local processes.
- **No full schema dump into agent context** — `tools_search` never returns
  schemas; `tools_schema` returns exactly one, size-capped.
- **No secret forwarding by default** — empty env allowlist forwards nothing;
  no secret values in config files; env values never logged.
- **Refusals over silence** — every denial is a coded JSON-RPC error plus an
  `ok: false` audit line; no truncation, no garbage relay.
- **Existing redaction stays in force** — `redact()` / `looks_secret()` /
  `scrub_paths()` semantics are a floor, never relaxed.
