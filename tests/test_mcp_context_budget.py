"""Context-budget evidence for the Unlimited Tools gateway.

Proves, with measured byte sizes, that the gateway never injects all upstream
tool schemas into the host's context:

- the gateway's own ``tools/list`` exposes ONLY the 3 meta-tools;
- ``tools_search`` returns compact metadata (no input schemas);
- ``tools_schema`` returns exactly ONE schema;
- all of the above are a small fraction of the full all-schemas dump a host
  would otherwise pay for at session start.

The numbers are printed so they can be quoted as evidence
(run with ``pytest -s tests/test_mcp_context_budget.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.mcp.audit import AuditLog
from unlimited_skills.mcp.gateway import Gateway, build_gateway_registry
from unlimited_skills.mcp.protocol import StdioServer

N_TOOLS = 40
N_PARAMS = 8


def fat_schema(tool_index: int) -> dict:
    """A realistic mid-size JSON input schema (~2 KB), like real MCP servers ship."""
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
            for j in range(N_PARAMS)
        },
    }


def loaded_gateway(tmp_path: Path) -> Gateway:
    """A gateway whose single upstream is already indexed with N_TOOLS fat tools.

    The upstream is never spawned: its in-memory index is populated directly
    and ``start`` is stubbed out, so this test measures payload sizes only.
    """
    config = {"upstreams": [{"name": "fake", "command": "unused"}]}
    gateway = Gateway(config, AuditLog(tmp_path / "audit.jsonl"))
    client = gateway.upstreams["fake"]
    for i in range(N_TOOLS):
        client.tools[f"tool_{i:02d}"] = {
            "description": f"Fake tool {i:02d} that performs operation {i} on widgets",
            "inputSchema": fat_schema(i),
        }
    client.indexed = True
    client.start = lambda: None  # the index is already in memory; never spawn
    return gateway


def payload_bytes(value) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def test_context_budget_gateway_never_dumps_all_schemas(tmp_path: Path) -> None:
    gateway = loaded_gateway(tmp_path)
    client = gateway.upstreams["fake"]

    # What a host would pay without the gateway: every schema, up front.
    full_dump = [
        {"name": name, "description": info["description"], "inputSchema": info["inputSchema"]}
        for name, info in sorted(client.tools.items())
    ]
    full_bytes = payload_bytes(full_dump)

    # The gateway's standing context cost: tools/list with ONLY 3 meta-tools.
    server = StdioServer(build_gateway_registry(gateway), server_name="unlimited-tools-gateway")
    listing = server.list_tools()
    listing_bytes = payload_bytes(listing)
    assert [tool["name"] for tool in listing] == ["tools_call", "tools_schema", "tools_search"]
    listing_text = json.dumps(listing)
    assert "param_0_of_tool" not in listing_text and "Fake tool" not in listing_text

    # tools_search: compact metadata for N indexed tools, never schemas.
    search = gateway.tools_search({"query": "widgets operation", "limit": 8})
    search_bytes = payload_bytes(search)
    assert search["hits"], "expected search hits over the fake index"
    assert "inputSchema" not in json.dumps(search)

    # tools_schema: exactly ONE schema, on demand.
    schema = gateway.tools_schema({"tool": "fake.tool_07"})
    schema_bytes = payload_bytes(schema)
    assert schema["tool"] == "fake.tool_07"
    assert "param_0_of_tool_7" in json.dumps(schema)
    assert "param_0_of_tool_8" not in json.dumps(schema), "only the requested schema"

    print()
    print(f"[context-budget] upstream tools indexed:            {N_TOOLS}")
    print(f"[context-budget] full all-schemas dump (no gateway): {full_bytes:,} bytes")
    print(f"[context-budget] gateway tools/list (3 meta-tools):  {listing_bytes:,} bytes")
    print(f"[context-budget] tools_search response (limit 8):    {search_bytes:,} bytes")
    print(f"[context-budget] tools_schema response (one tool):   {schema_bytes:,} bytes")
    print(
        "[context-budget] standing cost ratio: "
        f"{listing_bytes / full_bytes:.1%} of the full dump; "
        f"search {search_bytes / full_bytes:.1%}, one schema {schema_bytes / full_bytes:.1%}"
    )

    assert full_bytes > 40_000, "fixture sanity: the full dump must be context-heavy"
    assert listing_bytes < full_bytes * 0.10
    assert search_bytes < full_bytes * 0.10
    assert schema_bytes < full_bytes * 0.10
