from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from unlimited_skills.mcp.audit import AuditLog, default_audit_path, redact, scrub_paths
from unlimited_skills.mcp.gateway import (
    Gateway,
    GatewayConfigError,
    StdioServer,
    build_gateway_registry,
    load_gateway_config,
)
from unlimited_skills.mcp.protocol import ToolError

FAKE_UPSTREAM = r'''
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text("spawned", encoding="utf-8")

TOOLS = {
    "echo": {
        "description": "Echo text back",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    "add": {
        "description": "Add two integers",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
    },
}


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
            "serverInfo": {"name": "fake", "version": "0.0.1"},
        }})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "tools": [{"name": name, **info} for name, info in TOOLS.items()],
        }})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": "echo:" + str(args.get("text", ""))}],
                "isError": False,
            }})
        elif name == "add":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": str(int(args.get("a", 0)) + int(args.get("b", 0)))}],
                "isError": False,
            }})
        else:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "unknown tool"}})
    else:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
'''


@pytest.fixture()
def fixture_paths(tmp_path: Path) -> dict:
    script = tmp_path / "fake_upstream.py"
    script.write_text(FAKE_UPSTREAM, encoding="utf-8")
    marker = tmp_path / "spawned.marker"
    config = {
        "schema_version": 1,
        "upstreams": [
            {
                "name": "fake",
                "command": sys.executable,
                "args": [str(script), str(marker)],
                "env": {"FAKE_UPSTREAM_TOKEN": "%FAKE_UPSTREAM_TOKEN%"},
                "tools": [
                    {"name": "echo", "description": "Echo text back"},
                    {"name": "add", "description": "Add two integers"},
                ],
            }
        ],
    }
    config_path = tmp_path / "gateway-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return {"config_path": config_path, "marker": marker, "audit": tmp_path / "mcp-audit.jsonl"}


def make_gateway(fixture_paths: dict) -> Gateway:
    config = load_gateway_config(fixture_paths["config_path"])
    return Gateway(config, AuditLog(fixture_paths["audit"]))


def test_config_validation(tmp_path: Path) -> None:
    with pytest.raises(GatewayConfigError):
        load_gateway_config(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(GatewayConfigError):
        load_gateway_config(bad)
    dupe = tmp_path / "dupe.json"
    dupe.write_text(
        json.dumps({"upstreams": [{"name": "a", "command": "x"}, {"name": "a", "command": "y"}]}),
        encoding="utf-8",
    )
    with pytest.raises(GatewayConfigError):
        load_gateway_config(dupe)


def test_tools_search_does_not_spawn_and_has_no_schemas(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths)
    try:
        result = gateway.tools_search({"query": "echo text"})
        assert not fixture_paths["marker"].exists(), "tools_search must not spawn upstreams"
        assert not gateway.upstreams["fake"].started
        dumped = json.dumps(result)
        assert "inputSchema" not in dumped
        top = result["hits"][0]
        assert top["tool"] == "fake.echo"
        assert top["upstream"] == "fake"
        assert top["description"] == "Echo text back"
        assert top["score"] > 0
        with pytest.raises(ToolError):
            gateway.tools_search({"query": ""})
    finally:
        gateway.shutdown()


def test_tools_schema_lazily_spawns_one_upstream(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths)
    try:
        assert not fixture_paths["marker"].exists()
        result = gateway.tools_schema({"tool": "fake.add"})
        assert fixture_paths["marker"].exists(), "tools_schema must spawn the upstream"
        assert gateway.upstreams["fake"].started
        assert result["tool"] == "fake.add"
        assert result["inputSchema"]["properties"]["a"]["type"] == "integer"
        with pytest.raises(ToolError):
            gateway.tools_schema({"tool": "fake.missing"})
        with pytest.raises(ToolError):
            gateway.tools_schema({"tool": "unknown.echo"})
        with pytest.raises(ToolError):
            gateway.tools_schema({"tool": "not-qualified"})
    finally:
        gateway.shutdown()
        assert not gateway.upstreams["fake"].started


def test_tools_call_routes_and_audit_redacts(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths)
    registry = build_gateway_registry(gateway)
    try:
        result = registry["tools_call"]["handler"](
            {"tool": "fake.echo", "arguments": {"text": "hello", "api_token": "secretvalue"}}
        )
        assert result["isError"] is False
        assert result["content"][0]["text"] == "echo:hello"
        add_result = registry["tools_call"]["handler"]({"tool": "fake.add", "arguments": {"a": 2, "b": 3}})
        assert add_result["content"][0]["text"] == "5"
        registry["tools_search"]["handler"]({"query": "add integers"})
        registry["tools_schema"]["handler"]({"tool": "fake.echo"})
    finally:
        gateway.shutdown()

    audit_text = fixture_paths["audit"].read_text(encoding="utf-8")
    assert "secretvalue" not in audit_text, "audit log must redact token values"
    rows = [json.loads(line) for line in audit_text.splitlines() if line.strip()]
    tools = [row["tool"] for row in rows]
    assert "tools_call" in tools and "tools_search" in tools and "tools_schema" in tools
    for row in rows:
        assert set(row) >= {"ts", "tool", "upstream", "duration_ms", "ok"}
        assert row["ok"] is True
    call_row = next(row for row in rows if row["tool"] == "tools_call")
    assert call_row["upstream"] == "fake"
    assert call_row["args"]["arguments"]["api_token"] == "[redacted]"
    # Results must never be audited.
    assert "echo:hello" not in audit_text


def test_gateway_through_stdio_server_dispatch(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths)
    server = StdioServer(build_gateway_registry(gateway), server_name="unlimited-tools-gateway")
    try:
        listing = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        assert [tool["name"] for tool in listing] == ["tools_call", "tools_schema", "tools_search"]
        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "tools_call", "arguments": {"tool": "fake.echo", "arguments": {"text": "rpc"}}},
            }
        )
        assert response["result"]["isError"] is False
        assert response["result"]["content"][0]["text"] == "echo:rpc"
    finally:
        gateway.shutdown()


def test_redact_and_scrub_paths(tmp_path: Path) -> None:
    payload = {
        "api_token": "secretvalue",
        "Authorization": "Bearer abc",
        "PASSWORD": "p",
        "proof_of_work": "x",
        "private_key": "k",
        "client_secret": "s",
        "text": "ok " + "y" * 500,
        "nested": [{"session_token": "t2", "count": 3}],
    }
    redacted = redact(payload)
    dumped = json.dumps(redacted)
    for secret in ("secretvalue", "Bearer abc", '"p"', '"x"', '"k"', '"s"', '"t2"'):
        assert secret not in dumped
    assert redacted["nested"][0]["count"] == 3
    assert len(redacted["text"]) <= 120
    scrubbed = scrub_paths(r"failed at C:\Users\tedja\secret\file.txt and /home/user/x.txt")
    assert "tedja" not in scrubbed and "/home/user" not in scrubbed
    assert "[path]" in scrubbed
    assert default_audit_path(tmp_path) == tmp_path / ".learning" / "mcp-audit.jsonl"
