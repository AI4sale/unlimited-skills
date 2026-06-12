# MCP performance: benchmarks and the warm-start plan

This page covers the E12 performance benchmark pack for the Unlimited Tools
gateway (`unlimited-skills mcp gateway`) and the **design-only** warm-start
optimization plan derived from its measurements. Nothing here changes any
runtime default: the gateway stays lazy, stdio-only, local-only, and
telemetry-free exactly as specified in
[unlimited-tools.md](unlimited-tools.md) and
[mcp-upstream-security-model.md](mcp-upstream-security-model.md).

## Running the benchmarks

```bash
python scripts/run-mcp-performance-benchmarks.py --fixture-mode --json --sizes 40,200,1000
```

- `--fixture-mode` is required: the benchmarks are fully self-contained
  (generated fake stdio upstreams under a temp directory; no network, no real
  upstreams, no telemetry, no hosted calls).
- `--sizes` is the total tool count per run, spread across 4 fake upstreams
  with realistic ~2 KB input schemas (the
  `tests/test_mcp_context_budget.py` fixture shape).
- `--repeats` (default 5) is K, the kept samples per measurement; `--warmup`
  (default 1) iterations are discarded first.
- Reports are written to `--out` (default `build/perf/`, gitignored):
  `mcp-perf-report.json` (shape: `schemas/mcp-perf-report.schema.json`,
  raw samples included) and `mcp-perf-report.md` (human tables). `--json`
  additionally prints the JSON report to stdout.

Timers are the high-resolution monotonic perf counter. Reports never contain
local absolute paths or secret-shaped values
(`tests/test_mcp_performance_benchmarks.py` enforces both, plus schema
validity and context-bytes consistency, on every CI run).

## What each metric means

| Metric | What is measured |
| --- | --- |
| `cold_start.total` | Fresh gateway process: spawn + `initialize` handshake + `tools/list` (the 3 meta-tools). Each sample is a new process. |
| `cold_start.initialize` / `tools_list` | The split: interpreter+import+spawn time vs the (tiny) meta-tool listing round-trip. |
| `warm.first_schema` | First `tools_schema` against an upstream: lazy subprocess spawn + `initialize` + `tools/list` + in-memory indexing of all its tools. |
| `warm.reuse_schema` / `reuse_call` | The same upstream kept alive: one stdio round-trip, no spawn, no re-index. |
| `warm.spawn_vs_reuse_ratio` | median(first) / median(reuse): how much the lazy first call costs relative to steady state. |
| `search.indexed_no_spawn` | `tools_search` over the pre-declared config index; never spawns anything. |
| `search.refresh_all_upstreams` | `tools_search` with `refresh: true`: spawn + handshake + index of every not-yet-spawned upstream. |
| `indexing.upstream_spawn_and_handshake` | In-process split: subprocess spawn + `initialize` for one upstream. |
| `indexing.tools_list_and_index` | In-process split: `tools/list` retrieval + indexing of that upstream's N tools. |
| `audit_overhead.*` | Per-call cost of the audited `tools_schema` handler vs the raw call, at `audit_level` `minimal` and `standard` (batched in-process calls; the audit JSONL goes to a temp path). |
| `context_bytes.*` | The measured context-budget table at this size: full all-schemas dump vs gateway `tools/list`, one `tools_search` response, one `tools_schema` response. |
| `memory` | Best-effort gateway process peak RSS (Windows `GetProcessMemoryInfo` via ctypes, Linux `/proc/<pid>/status` VmHWM; marked unavailable elsewhere; upstream subprocesses not included). |

## Reference run

Measured with the command above (Python 3.11, Windows 11, K=5 after 1
warmup; subprocess spawn is expensive on Windows, which is exactly the cost
the lazy model defers). Cells are min / median / mean in milliseconds.
Timings vary by machine; the JSON report carries raw samples for your own
reference runs.

| Metric (ms, median) | 40 tools | 200 tools | 1000 tools |
| --- | ---: | ---: | ---: |
| Cold start total (spawn + initialize + tools/list) | 700.4 | 746.8 | 706.8 |
| Cold start: tools/list round-trip only | 0.3 | 0.3 | 0.3 |
| First `tools_schema` (lazy spawn + index one upstream) | 147.1 | 164.4 | 195.0 |
| Reused `tools_schema` (upstream kept alive) | 1.2 | 1.3 | 1.3 |
| Reused `tools_call` | 1.1 | 1.3 | 1.3 |
| `tools_search`, pre-declared index (no spawn) | 2.2 | 6.1 | 27.4 |
| `tools_search` `refresh: true` (spawn + index all 4) | 464.8 | 476.7 | 624.1 |
| Upstream spawn + handshake (in-process split) | 144.7 | 136.5 | 134.4 |
| `tools/list` + index of one upstream's tools (in-process split) | 1.2 | 4.9 | 21.6 |
| Audit overhead per call, `minimal` | 0.58 | 0.76 | 0.66 |
| Audit overhead per call, `standard` | 0.61 | 0.68 | 0.76 |

Spawn vs reuse: the first call to an upstream costs roughly **125x to 156x**
a reused call; nearly all of it is subprocess spawn + handshake (~135 to
145 ms), while indexing grows linearly but stays small (~0.09 ms per tool:
1.2 ms for 10 tools, 21.6 ms for 250).

Context bytes (deterministic at every size; the standing cost never grows):

| Payload | 40 tools | 200 tools | 1000 tools |
| --- | ---: | ---: | ---: |
| Full all-schemas dump (what a host pays without the gateway) | 90,580 | 455,420 | 2,285,020 |
| Gateway `tools/list` (3 meta-tools, **standing** cost) | 1,268 | 1,268 | 1,268 |
| One `tools_search` response (limit 8) | 1,338 | 1,338 | 1,338 |
| One `tools_schema` response (exactly one schema) | 2,253 | 2,253 | 2,253 |
| Standing cost as share of the full dump | 1.40% | 0.28% | 0.06% |

Gateway peak RSS stayed ~5.2 MB at every size (gateway process only).

Reading the table:

- **Cold start (~0.7 s) is interpreter + import time**, not protocol work:
  `initialize` absorbs essentially the whole total while the `tools/list`
  round-trip is 0.3 ms, independent of fixture size (the gateway never
  touches upstreams at startup).
- **Reuse works**: once spawned, an upstream answers schema and call
  round-trips in ~1.3 ms. The lazy model pays the ~150 ms spawn exactly once
  per upstream per gateway lifetime.
- **`tools_search` without spawn scales linearly** with the indexed tool
  count (lexical scoring over names + descriptions) but stays cheap even at
  1000 tools (27 ms).
- **Audit costs under 1 ms per call** at either level; `minimal` vs
  `standard` is a wash because the cost is the file append, not redaction.

## Warm-start optimization plan (design only — nothing implemented, nothing default-on)

The measurements above identify three latency pools: gateway process cold
start (~700 ms, interpreter-bound), first-touch upstream spawn (~150 ms per
upstream), and indexing (linear, small). The candidates below target them
**without changing any default**: the lazy spawn model, the no-telemetry
boundary, and the E07 security model are preserved; every optimization is
explicit opt-in and gated on the evidence listed.

### 1. Persistent tool-index cache (opt-in flag, e.g. `--index-cache`)

- **What**: serialize each upstream's indexed tool entries (name,
  description, `inputSchema`, recorded byte sizes, oversized markers) to a
  local cache file under the library runtime dir (next to the audit log,
  e.g. `.learning/mcp-tool-index-cache.json`). On gateway start, load
  matching entries so a restarted gateway answers `tools_schema` (and richer
  `tools_search`) without spawning the upstream at all.
- **Keying / invalidation**: each entry is keyed by the SHA-256 of the
  upstream's canonical spec (name, command, args, `env_allowlist` names,
  cwd, trust level, size limits) plus the upstream's `serverInfo`
  name+version captured at index time. Any config-hash mismatch invalidates
  the entry; a live spawn that reports a different `serverInfo` version
  overwrites it; `tools_search` with `refresh: true` always bypasses and
  rewrites; a max-age (e.g. 7 days) bounds silent drift. `schema_version`
  field on the cache file; unknown versions are discarded, never migrated
  silently.
- **Serialization format**: one JSON document, `schema_version`, then a map
  of config-hash → `{server_info, indexed_at, tools: {name: {description,
  inputSchema | schema_oversized+schema_bytes}}}`. Loaded entries are
  treated as untrusted input: re-validated against the same
  `max_schema_bytes` ceilings as a live index (refuse, never truncate), and
  the file is only ever read from the user-owned runtime dir.
- **Expected impact** (from the reference run): a cache-hit `tools_schema`
  drops from ~147 to 195 ms to ~1 ms — the spawn is deferred until a
  `tools_call` actually needs a live process. Restarted-gateway `refresh`
  searches stop costing ~0.5 to 0.6 s.
- **Risks**: stale schemas after an upstream upgrade the config does not
  reflect (mitigated by `serverInfo` version checks, max-age, and
  `refresh`); a tampered cache file injecting schema text (mitigated by
  size re-validation, runtime-dir-only location, and the fact that schemas
  are data returned to the host, never executed); disk growth (bounded by
  the same rotation philosophy as the audit log).
- **Default**: OFF. Without the flag the gateway behaves byte-for-byte as
  today.

### 2. Pre-spawn of allowlisted upstreams (explicit opt-in flag, e.g. `--pre-spawn`)

- **What**: after the gateway's own `initialize`, spawn and index configured
  spawnable upstreams in background threads so the first `tools_schema` or
  `tools_call` finds them warm. Never honored from config alone — the
  operator must pass the gateway flag, so a tampered config cannot turn
  silent process spawning on.
- **Expected impact**: hides the ~135 to 145 ms per-upstream spawn and the
  index time entirely; first-call latency converges to the ~1.3 ms reuse
  cost. Most valuable for interactive hosts where the first tool use sits on
  a user-visible turn.
- **Risks**: resources spent on upstreams that are never used (4 child
  processes in the reference fixture; real configs may list more); startup
  stampede on battery/CI machines; a behavioral departure from "the gateway
  never spawns what nobody asked for", which is why it stays opt-in and
  per-run explicit. Disabled and `future-remote-placeholder` upstreams are
  never pre-spawned under any flag (E08 enforcement is unchanged).
- **Default**: OFF.

### 3. Lighter gateway entry path (no flag; pure internal work)

- **What**: cold start is ~700 ms of interpreter + import time
  (`initialize` ≈ total; the protocol work is 0.3 ms). A dedicated
  minimal entry module for `mcp gateway` that avoids importing the full CLI
  surface (and any vector-search stack) would cut the standing cost every
  host pays at session start.
- **Expected impact**: bounded by Python interpreter startup (~100 to
  200 ms floor); realistic target is several hundred ms off the ~700 ms
  measured.
- **Risks**: low — refactoring import graphs, no behavior change. Must keep
  the existing `unlimited-skills mcp gateway` invocation working unchanged.

### What stays default-off, and the evidence that gates each step

| Candidate | Stays default-off because | Evidence to flip it on (per machine class, from this benchmark pack) |
| --- | --- | --- |
| Index cache | Current behavior is correct and simple; cache adds staleness surface | First-schema latency matters in real traces AND cache-hit `tools_schema` reproducibly lands near reuse cost with zero stale-schema test failures |
| Pre-spawn | Violates "spawn nothing unasked" unless the operator explicitly opts in | Measured first-call latency on the operator's real upstreams exceeds their interactivity budget; resource cost of idle upstreams measured and accepted |
| Entry-path slimming | Needs no flag, but ships only with proof | Cold-start median drops materially in this benchmark with the full suite green and the smoke (`scripts/run-mcp-smoke.py`) unchanged |

Non-goals, confirmed by measurement: async/buffered audit writes (the audit
append costs under 1 ms per call and durability of the security log wins);
replacing the linear lexical search (27 ms at 1000 tools is far below any
round-trip the host notices; revisit only past ~10k indexed tools).

Re-running `scripts/run-mcp-performance-benchmarks.py` before and after any
of these changes is the acceptance gate: the JSON report's raw samples make
regressions visible per metric and per size.
