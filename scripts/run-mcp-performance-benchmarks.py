"""Fixture-only MCP performance benchmark pack (E12).

Measures, per fixture size (default 40/200/1000 tools spread across 4 fake
stdio upstreams):

- cold start: gateway process spawn -> initialize handshake -> tools/list;
- warm behavior: first ``tools_schema`` (lazy spawn + index) vs repeated
  ``tools_schema`` / ``tools_call`` on the same upstream (reuse);
- ``tools_search`` against the pre-declared index (no spawn) and with
  ``refresh: true`` (spawn + index everything);
- schema indexing cost: spawn/handshake vs tools/list-and-index, in-process;
- audit write overhead: the same call sequence unaudited vs audit_level
  ``minimal`` vs ``standard``;
- context bytes: gateway standing cost / search / one schema vs the full
  all-schemas dump (the ``tests/test_mcp_context_budget.py`` methodology);
- best-effort gateway peak RSS (no psutil: OS facilities only).

Fixture mode is fully self-contained: temp dirs, generated fake upstreams,
no network, no real upstreams, no telemetry, and no runtime default changes.
Timings use the monotonic high-resolution perf counter, each measurement repeats K times (default 5)
after a discarded warmup, and the JSON report carries the raw samples.
The report never contains local absolute paths or secret-shaped values.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_perf_support import (  # noqa: E402
    DEFAULT_UPSTREAM_COUNT,
    build_tools,
    peak_rss_bytes,
    split_tools,
    stat_block,
    tool_name,
    upstream_specs,
    write_perf_upstream_script,
)
from mcp_smoke_support import JsonRpcProcess  # noqa: E402

from unlimited_skills.mcp.audit import AuditLog  # noqa: E402
from unlimited_skills.mcp.gateway import (  # noqa: E402
    Gateway,
    UpstreamClient,
    build_gateway_registry,
)
from unlimited_skills.mcp.protocol import StdioServer  # noqa: E402

DEFAULT_SIZES = (40, 200, 1000)
DEFAULT_REPEATS = 5
DEFAULT_WARMUP = 1
REUSE_CALLS = 3  # reuse samples collected inside each warm gateway process
AUDIT_BATCH = 20  # in-process calls per audit-overhead sample (microsecond ops)
SEARCH_QUERY = "widgets operation"
REPORT_BASENAME = "mcp-perf-report"


def _ms(start: float, end: float) -> float:
    return (end - start) * 1000.0


def _spawn_gateway(config_path: Path, library: Path, audit_path: Path) -> JsonRpcProcess:
    return JsonRpcProcess(
        [
            sys.executable,
            "-m",
            "unlimited_skills.cli",
            "--root",
            str(library),
            "mcp",
            "gateway",
            "--config",
            str(config_path),
            "--audit-log",
            str(audit_path),
        ],
        cwd=REPO,
        env={"PYTHONPATH": str(REPO)},
    )


def _meta_call(gateway: JsonRpcProcess, name: str, arguments: dict) -> dict:
    response = gateway.request("tools/call", {"name": name, "arguments": arguments}, timeout=120.0)
    if "error" in response:
        raise RuntimeError(f"gateway refused {name}: {response['error']}")
    return response["result"]


def _write_size_fixture(temp_root: Path, n_tools: int) -> tuple[Path, Path, Path, list[dict]]:
    size_root = temp_root / f"size-{n_tools}"
    library = size_root / "library"
    library.mkdir(parents=True, exist_ok=True)
    script = write_perf_upstream_script(size_root)
    specs = upstream_specs(script, n_tools)
    config_path = size_root / "gateway-config.json"
    config_path.write_text(
        json.dumps({"schema_version": 1, "upstreams": specs}, indent=2), encoding="utf-8"
    )
    audit_path = size_root / "mcp-audit.jsonl"
    return config_path, library, audit_path, specs


def bench_cold_start(
    config_path: Path, library: Path, audit_path: Path, repeats: int, warmup: int
) -> dict:
    totals: list[float] = []
    init_samples: list[float] = []
    list_samples: list[float] = []
    for _ in range(warmup + repeats):
        start = time.perf_counter()
        gateway = _spawn_gateway(config_path, library, audit_path)
        try:
            gateway.request("initialize", {"capabilities": {}}, timeout=120.0)
            after_init = time.perf_counter()
            gateway.notify("notifications/initialized")
            gateway.request("tools/list", timeout=120.0)
            after_list = time.perf_counter()
        finally:
            gateway.close()
        totals.append(_ms(start, after_list))
        init_samples.append(_ms(start, after_init))
        list_samples.append(_ms(after_init, after_list))
    return {
        "total": stat_block(totals[warmup:]),
        "initialize": stat_block(init_samples[warmup:]),
        "tools_list": stat_block(list_samples[warmup:]),
    }


def bench_warm_behavior(
    config_path: Path,
    library: Path,
    audit_path: Path,
    specs: list[dict],
    repeats: int,
    warmup: int,
) -> tuple[dict, dict, dict]:
    """Warm spawn-vs-reuse, search latency, and gateway peak RSS in one pass."""
    first_upstream = specs[0]["name"]
    first_tools = [tool["name"] for tool in specs[0]["tools"]]
    first_schema: list[float] = []
    reuse_schema: list[float] = []
    reuse_call: list[float] = []
    search_indexed: list[float] = []
    search_refresh: list[float] = []
    rss_samples: list[int] = []
    for iteration in range(warmup + repeats):
        keep = iteration >= warmup
        gateway = _spawn_gateway(config_path, library, audit_path)
        try:
            gateway.request("initialize", {"capabilities": {}}, timeout=120.0)
            gateway.notify("notifications/initialized")
            # tools_search against the pre-declared index: never spawns.
            for search_round in range(1 + REUSE_CALLS):
                start = time.perf_counter()
                _meta_call(gateway, "tools_search", {"query": SEARCH_QUERY, "limit": 8})
                if keep and search_round > 0:  # first round is an in-process warmup
                    search_indexed.append(_ms(start, time.perf_counter()))
            # First tools_schema: lazy spawn + handshake + full index of one upstream.
            start = time.perf_counter()
            _meta_call(gateway, "tools_schema", {"tool": f"{first_upstream}.{first_tools[0]}"})
            if keep:
                first_schema.append(_ms(start, time.perf_counter()))
            # Reuse: the same upstream stays alive; no spawn, no re-index.
            for index in range(REUSE_CALLS):
                target = first_tools[(index + 1) % len(first_tools)]
                start = time.perf_counter()
                _meta_call(gateway, "tools_schema", {"tool": f"{first_upstream}.{target}"})
                if keep:
                    reuse_schema.append(_ms(start, time.perf_counter()))
            for index in range(REUSE_CALLS):
                target = first_tools[index % len(first_tools)]
                start = time.perf_counter()
                _meta_call(
                    gateway,
                    "tools_call",
                    {"tool": f"{first_upstream}.{target}", "arguments": {}},
                )
                if keep:
                    reuse_call.append(_ms(start, time.perf_counter()))
            # refresh: true spawns and indexes every remaining upstream.
            start = time.perf_counter()
            _meta_call(gateway, "tools_search", {"query": SEARCH_QUERY, "limit": 8, "refresh": True})
            if keep:
                search_refresh.append(_ms(start, time.perf_counter()))
            if keep:
                rss = peak_rss_bytes(gateway.process.pid)
                if rss is not None:
                    rss_samples.append(rss)
        finally:
            gateway.close()
    warm = {
        "first_schema": stat_block(first_schema),
        "reuse_schema": stat_block(reuse_schema),
        "reuse_call": stat_block(reuse_call),
        "spawn_vs_reuse_ratio": round(
            stat_block(first_schema)["median"] / max(stat_block(reuse_schema)["median"], 0.001), 1
        ),
    }
    search = {
        "indexed_no_spawn": stat_block(search_indexed),
        "refresh_all_upstreams": stat_block(search_refresh),
    }
    memory = {
        "available": bool(rss_samples),
        "gateway_peak_rss_bytes": max(rss_samples) if rss_samples else None,
        "source": (
            "GetProcessMemoryInfo" if sys.platform == "win32" else "proc-status"
        )
        if rss_samples
        else "unavailable",
        "note": "Gateway process only; spawned upstream subprocesses are not included.",
    }
    return warm, search, memory


def bench_indexing(temp_root: Path, specs: list[dict], repeats: int, warmup: int) -> dict:
    """In-process spawn/handshake vs tools/list-and-index split for one upstream."""
    spec = dict(specs[0])
    tools_in_upstream = len(spec["tools"])
    defaults = {"scratch_root": str(temp_root / "scratch")}
    spawn_samples: list[float] = []
    index_samples: list[float] = []
    for _ in range(warmup + repeats):
        client = UpstreamClient(spec, defaults)
        try:
            start = time.perf_counter()
            client.start()
            after_spawn = time.perf_counter()
            client.ensure_indexed()
            after_index = time.perf_counter()
        finally:
            client.terminate()
        spawn_samples.append(_ms(start, after_spawn))
        index_samples.append(_ms(after_spawn, after_index))
    return {
        "tools_indexed": tools_in_upstream,
        "upstream_spawn_and_handshake": stat_block(spawn_samples[warmup:]),
        "tools_list_and_index": stat_block(index_samples[warmup:]),
    }


def _in_memory_gateway(temp_root: Path, n_tools: int, audit_level: str, tag: str) -> Gateway:
    """A gateway whose upstreams are pre-indexed in memory; never spawned."""
    slices = split_tools(n_tools, DEFAULT_UPSTREAM_COUNT)
    config = {
        "upstreams": [
            {"name": f"u{index:02d}", "command": "unused", "audit_level": audit_level}
            for index in range(len(slices))
        ]
    }
    gateway = Gateway(config, AuditLog(temp_root / f"audit-{tag}.jsonl"))
    for index, (start, count) in enumerate(slices):
        client = gateway.upstreams[f"u{index:02d}"]
        for tool in build_tools(start, count):
            client.tools[tool["name"]] = {
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
            }
        client.indexed = True
        client.start = lambda: None  # the index is already in memory; never spawn
    return gateway


def bench_audit_overhead(temp_root: Path, n_tools: int, repeats: int, warmup: int) -> dict:
    """Per-call cost of the audited handler vs the raw call, per audit level.

    Each sample is a batch of AUDIT_BATCH identical ``tools_schema`` calls
    (microsecond-scale work) divided by the batch size.
    """
    target = {"tool": f"u00.{tool_name(0)}"}

    def batch_samples(callable_) -> list[float]:
        samples: list[float] = []
        for _ in range(warmup + repeats):
            start = time.perf_counter()
            for _ in range(AUDIT_BATCH):
                callable_(dict(target))
            samples.append(_ms(start, time.perf_counter()) / AUDIT_BATCH)
        return samples[warmup:]

    raw_gateway = _in_memory_gateway(temp_root, n_tools, "standard", "raw")
    raw = batch_samples(raw_gateway.tools_schema)

    standard_gateway = _in_memory_gateway(temp_root, n_tools, "standard", "standard")
    standard_handler = build_gateway_registry(standard_gateway)["tools_schema"]["handler"]
    standard = batch_samples(standard_handler)

    minimal_gateway = _in_memory_gateway(temp_root, n_tools, "minimal", "minimal")
    minimal_handler = build_gateway_registry(minimal_gateway)["tools_schema"]["handler"]
    minimal = batch_samples(minimal_handler)

    raw_stats = stat_block(raw)
    minimal_stats = stat_block(minimal)
    standard_stats = stat_block(standard)
    return {
        "calls_per_sample": AUDIT_BATCH,
        "no_audit": raw_stats,
        "audit_minimal": minimal_stats,
        "audit_standard": standard_stats,
        "minimal_overhead_ms_per_call": round(minimal_stats["median"] - raw_stats["median"], 3),
        "standard_overhead_ms_per_call": round(standard_stats["median"] - raw_stats["median"], 3),
    }


def bench_context_bytes(temp_root: Path, n_tools: int) -> dict:
    """The context-budget methodology, deterministic, at this fixture size."""

    def payload_bytes(value) -> int:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    gateway = _in_memory_gateway(temp_root, n_tools, "standard", "bytes")
    full_dump = []
    for client in gateway.upstreams.values():
        for name, info in sorted(client.tools.items()):
            full_dump.append(
                {
                    "name": name,
                    "description": info["description"],
                    "inputSchema": info["inputSchema"],
                }
            )
    full_bytes = payload_bytes(full_dump)
    server = StdioServer(build_gateway_registry(gateway), server_name="unlimited-tools-gateway")
    listing_bytes = payload_bytes(server.list_tools())
    search_bytes = payload_bytes(gateway.tools_search({"query": SEARCH_QUERY, "limit": 8}))
    schema_bytes = payload_bytes(gateway.tools_schema({"tool": f"u00.{tool_name(0)}"}))
    return {
        "full_all_schemas_dump": full_bytes,
        "gateway_tools_list": listing_bytes,
        "tools_search_response": search_bytes,
        "tools_schema_response": schema_bytes,
        "standing_cost_share": round(listing_bytes / full_bytes, 4),
        "search_share": round(search_bytes / full_bytes, 4),
        "schema_share": round(schema_bytes / full_bytes, 4),
    }


def bench_size(temp_root: Path, n_tools: int, repeats: int, warmup: int) -> dict:
    config_path, library, audit_path, specs = _write_size_fixture(temp_root, n_tools)
    cold = bench_cold_start(config_path, library, audit_path, repeats, warmup)
    warm, search, memory = bench_warm_behavior(
        config_path, library, audit_path, specs, repeats, warmup
    )
    indexing = bench_indexing(temp_root / f"size-{n_tools}", specs, repeats, warmup)
    audit = bench_audit_overhead(temp_root / f"size-{n_tools}", n_tools, repeats, warmup)
    context = bench_context_bytes(temp_root / f"size-{n_tools}", n_tools)
    return {
        "tools_total": n_tools,
        "upstreams": len(specs),
        "tools_per_upstream": len(specs[0]["tools"]),
        "cold_start": cold,
        "warm": warm,
        "search": search,
        "indexing": indexing,
        "audit_overhead": audit,
        "context_bytes": context,
        "memory": memory,
    }


def run_benchmarks(sizes: list[int], repeats: int, warmup: int) -> dict:
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="uls-mcp-perf-") as temp:
        temp_root = Path(temp)
        size_reports = [bench_size(temp_root, size, repeats, warmup) for size in sizes]
    return {
        "schema_version": 1,
        "status": "passed",
        "fixture_mode": True,
        "generated_at": round(started, 3),
        "duration_seconds": round(time.time() - started, 3),
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "platform": sys.platform,
        "repeats": repeats,
        "warmup": warmup,
        "sizes": size_reports,
    }


def _md_stat(stat: dict) -> str:
    return f"{stat['min']:.1f} / {stat['median']:.1f} / {stat['mean']:.1f}"


def render_markdown(report: dict) -> str:
    lines = [
        "# MCP performance benchmark report",
        "",
        f"Fixture mode: {report['fixture_mode']} -- fake stdio upstreams only, no network, no telemetry.",
        f"Python {report['python_version']} on {report['platform']}; "
        f"{report['repeats']} repeats per measurement after {report['warmup']} discarded warmup.",
        "Latency cells are min / median / mean in milliseconds.",
        "",
    ]
    for size in report["sizes"]:
        lines.extend(
            [
                f"## {size['tools_total']} tools across {size['upstreams']} upstreams",
                "",
                "| Metric | min / median / mean (ms) |",
                "| --- | ---: |",
                f"| Cold start total (spawn -> initialize -> tools/list) | {_md_stat(size['cold_start']['total'])} |",
                f"| Cold start: initialize | {_md_stat(size['cold_start']['initialize'])} |",
                f"| Cold start: tools/list | {_md_stat(size['cold_start']['tools_list'])} |",
                f"| First tools_schema (lazy spawn + index, {size['tools_per_upstream']} tools) | {_md_stat(size['warm']['first_schema'])} |",
                f"| Reused tools_schema (same upstream) | {_md_stat(size['warm']['reuse_schema'])} |",
                f"| Reused tools_call (same upstream) | {_md_stat(size['warm']['reuse_call'])} |",
                f"| tools_search, pre-declared index (no spawn) | {_md_stat(size['search']['indexed_no_spawn'])} |",
                f"| tools_search refresh=true (spawn + index all) | {_md_stat(size['search']['refresh_all_upstreams'])} |",
                f"| Upstream spawn + handshake (in-process) | {_md_stat(size['indexing']['upstream_spawn_and_handshake'])} |",
                f"| tools/list + index of {size['indexing']['tools_indexed']} tools (in-process) | {_md_stat(size['indexing']['tools_list_and_index'])} |",
                "",
                f"Spawn vs reuse: the first call costs ~{size['warm']['spawn_vs_reuse_ratio']}x a reused call.",
                "",
                "| Audit overhead (per call) | min / median / mean (ms) |",
                "| --- | ---: |",
                f"| No audit (raw handler) | {_md_stat(size['audit_overhead']['no_audit'])} |",
                f"| audit_level minimal | {_md_stat(size['audit_overhead']['audit_minimal'])} |",
                f"| audit_level standard | {_md_stat(size['audit_overhead']['audit_standard'])} |",
                "",
                f"Median per-call audit overhead: minimal {size['audit_overhead']['minimal_overhead_ms_per_call']} ms, "
                f"standard {size['audit_overhead']['standard_overhead_ms_per_call']} ms.",
                "",
                "| Context payload | Bytes | Share of full dump |",
                "| --- | ---: | ---: |",
                f"| Full all-schemas dump (no gateway) | {size['context_bytes']['full_all_schemas_dump']:,} | 100% |",
                f"| Gateway tools/list (3 meta-tools, standing) | {size['context_bytes']['gateway_tools_list']:,} | {size['context_bytes']['standing_cost_share']:.2%} |",
                f"| One tools_search response (limit 8) | {size['context_bytes']['tools_search_response']:,} | {size['context_bytes']['search_share']:.2%} |",
                f"| One tools_schema response | {size['context_bytes']['tools_schema_response']:,} | {size['context_bytes']['schema_share']:.2%} |",
                "",
            ]
        )
        memory = size["memory"]
        if memory["available"]:
            lines.append(
                f"Gateway peak RSS: {memory['gateway_peak_rss_bytes']:,} bytes "
                f"(source: {memory['source']}; upstream subprocesses not included)."
            )
        else:
            lines.append("Gateway peak RSS: unavailable on this platform (best-effort).")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the fixture-only MCP performance benchmarks (no hosted calls)."
    )
    parser.add_argument(
        "--fixture-mode",
        action="store_true",
        help="Required explicit fixture mode; benchmarks never touch real upstreams.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON report to stdout.")
    parser.add_argument(
        "--sizes",
        default=",".join(str(size) for size in DEFAULT_SIZES),
        help="Comma-separated fixture sizes (total tools per run), e.g. 40,200,1000.",
    )
    parser.add_argument(
        "--repeats", type=int, default=DEFAULT_REPEATS, help="Samples per measurement (K)."
    )
    parser.add_argument(
        "--warmup", type=int, default=DEFAULT_WARMUP, help="Discarded warmup iterations."
    )
    parser.add_argument(
        "--out",
        default=str(REPO / "build" / "perf"),
        help="Output directory for the JSON and Markdown reports (default: build/perf).",
    )
    args = parser.parse_args(argv)
    if not args.fixture_mode:
        raise SystemExit(
            "--fixture-mode is required; the MCP performance benchmarks never call "
            "production hosted services or real upstreams."
        )
    try:
        sizes = [int(part) for part in str(args.sizes).split(",") if part.strip()]
    except ValueError:
        raise SystemExit("--sizes must be a comma-separated list of integers.")
    if not sizes or any(size < 4 for size in sizes):
        raise SystemExit("--sizes entries must be integers >= 4 (tools are spread over 4 upstreams).")
    if args.repeats < 1 or args.warmup < 0:
        raise SystemExit("--repeats must be >= 1 and --warmup >= 0.")

    report = run_benchmarks(sizes, args.repeats, args.warmup)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    (out_dir / f"{REPORT_BASENAME}.json").write_text(json_text + "\n", encoding="utf-8")
    (out_dir / f"{REPORT_BASENAME}.md").write_text(render_markdown(report), encoding="utf-8")
    if args.json:
        print(json_text)
    else:
        print("MCP performance benchmarks passed (fixture mode)")
        for size in report["sizes"]:
            print(
                f"- {size['tools_total']} tools: cold start median "
                f"{size['cold_start']['total']['median']:.0f} ms; first schema "
                f"{size['warm']['first_schema']['median']:.0f} ms vs reuse "
                f"{size['warm']['reuse_schema']['median']:.1f} ms; search "
                f"{size['search']['indexed_no_spawn']['median']:.1f} ms"
            )
        print(f"Reports written to {REPORT_BASENAME}.json / {REPORT_BASENAME}.md under --out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
