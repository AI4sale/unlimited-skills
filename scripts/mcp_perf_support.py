"""Fixture builders and measurement helpers for the MCP performance benchmarks.

Everything here is fixture-only, mirroring ``mcp_smoke_support``: fake stdio
upstreams generated under a temp directory, no network, no real upstreams,
no telemetry. The fake upstreams serve a parameterized number of tools with
realistic ~2 KB input schemas (the same shape as
``tests/test_mcp_context_budget.py``) so byte and latency measurements scale
with the fixture size.
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

N_PARAMS = 8
DEFAULT_UPSTREAM_COUNT = 4


def tool_name(index: int) -> str:
    return f"tool_{index:04d}"


def tool_description(index: int) -> str:
    return f"Fake tool {index:04d} that performs operation {index} on widgets"


def fat_schema(tool_index: int, n_params: int = N_PARAMS) -> dict:
    """A realistic mid-size JSON input schema (~2 KB), like real MCP servers ship.

    Same shape as ``tests/test_mcp_context_budget.py``; kept in sync with the
    literal copy inside the generated fake upstream script below.
    """
    return {
        "type": "object",
        "required": [f"param_0_of_tool_{tool_index}"],
        "properties": {
            f"param_{j}_of_tool_{tool_index}": {
                "type": "string",
                "description": (
                    f"Parameter {j} of fake tool {tool_index}. "
                    + "Detailed usage notes, constraints, examples and caveats. " * 3
                ),
            }
            for j in range(n_params)
        },
    }


def build_tools(start: int, count: int) -> list[dict]:
    """Deterministic tool listing for global tool indices [start, start+count)."""
    return [
        {
            "name": tool_name(index),
            "description": tool_description(index),
            "inputSchema": fat_schema(index),
        }
        for index in range(start, start + count)
    ]


def split_tools(n_tools: int, upstream_count: int = DEFAULT_UPSTREAM_COUNT) -> list[tuple[int, int]]:
    """Spread ``n_tools`` across upstreams as (start, count) slices."""
    upstream_count = max(1, min(upstream_count, n_tools))
    base, remainder = divmod(n_tools, upstream_count)
    slices: list[tuple[int, int]] = []
    start = 0
    for index in range(upstream_count):
        count = base + (1 if index < remainder else 0)
        slices.append((start, count))
        start += count
    return slices


# The fake upstream serves tools/list for its slice and answers tools/call
# with a tiny fixed-shape result. The schema builder is a literal copy of
# fat_schema() above so upstream payload sizes match the in-process builder.
PERF_UPSTREAM_SOURCE = r'''
import json
import sys

START = int(sys.argv[1])
COUNT = int(sys.argv[2])
N_PARAMS = int(sys.argv[3])


def fat_schema(tool_index):
    return {
        "type": "object",
        "required": ["param_0_of_tool_%d" % tool_index],
        "properties": {
            ("param_%d_of_tool_%d" % (j, tool_index)): {
                "type": "string",
                "description": (
                    "Parameter %d of fake tool %d. " % (j, tool_index)
                    + "Detailed usage notes, constraints, examples and caveats. " * 3
                ),
            }
            for j in range(N_PARAMS)
        },
    }


def listing():
    return [
        {
            "name": "tool_%04d" % index,
            "description": "Fake tool %04d that performs operation %d on widgets" % (index, index),
            "inputSchema": fat_schema(index),
        }
        for index in range(START, START + COUNT)
    ]


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


while True:
    line = sys.stdin.readline()
    if not line:
        break
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "id" not in msg:
        continue
    rid = msg["id"]
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "perf-fixture", "version": "0.0.1"},
        }})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": listing()}})
    elif method == "tools/call":
        params = msg.get("params") or {}
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": "ok:" + str(params.get("name", ""))}],
            "isError": False,
        }})
    else:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
'''.lstrip()


def write_perf_upstream_script(root: Path) -> Path:
    script = root / "perf_upstream.py"
    script.write_text(PERF_UPSTREAM_SOURCE, encoding="utf-8")
    return script


def upstream_specs(script: Path, n_tools: int, upstream_count: int = DEFAULT_UPSTREAM_COUNT) -> list[dict]:
    """Gateway upstream specs (one per slice) with pre-declared tool entries.

    The pre-declared ``tools`` entries (names + descriptions only, exactly
    what the config format allows) make ``tools_search`` answerable without
    spawning anything -- the behavior the no-spawn search benchmark measures.
    """
    specs: list[dict] = []
    for upstream_index, (start, count) in enumerate(split_tools(n_tools, upstream_count)):
        specs.append(
            {
                "name": f"u{upstream_index:02d}",
                "command": sys.executable,
                "args": [str(script), str(start), str(count), str(N_PARAMS)],
                "tools": [
                    {"name": tool_name(index), "description": tool_description(index)}
                    for index in range(start, start + count)
                ],
            }
        )
    return specs


def stat_block(samples_ms: list[float]) -> dict:
    """min/median/mean over raw millisecond samples (warmup already removed)."""
    return {
        "unit": "ms",
        "samples": [round(sample, 3) for sample in samples_ms],
        "min": round(min(samples_ms), 3),
        "median": round(statistics.median(samples_ms), 3),
        "mean": round(statistics.fmean(samples_ms), 3),
    }


def peak_rss_bytes(pid: int) -> int | None:
    """Best-effort peak RSS of a process; ``None`` when not measurable.

    psutil is deliberately not a dependency: on Windows this reads
    ``PeakWorkingSetSize`` via ``GetProcessMemoryInfo`` (ctypes); on Linux it
    reads ``VmHWM`` from ``/proc/<pid>/status``. Anywhere else it cleanly
    reports unavailable.
    """
    try:
        if sys.platform == "win32":
            return _windows_peak_rss(pid)
        status = Path(f"/proc/{pid}/status")
        if status.is_file():
            for line in status.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
        return None
    except Exception:
        return None


def _windows_peak_rss(pid: int) -> int | None:
    import ctypes
    from ctypes import wintypes

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    try:
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.windll.psapi
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.PeakWorkingSetSize)
    finally:
        kernel32.CloseHandle(handle)
