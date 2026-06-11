from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from unlimited_skills.mcp.audit import AuditLog, default_audit_path, redact, scrub_paths
from unlimited_skills.mcp.gateway import (
    UPSTREAM_PROTOCOL_ERROR,
    UPSTREAM_START_FAILED,
    UPSTREAM_TIMEOUT,
    Gateway,
    GatewayConfigError,
    StdioServer,
    UpstreamError,
    build_gateway_registry,
    load_gateway_config,
)
from unlimited_skills.mcp.protocol import ToolError

FAKE_UPSTREAM = r'''
import json
import sys
from pathlib import Path

with open(sys.argv[1], "a", encoding="utf-8") as fh:
    fh.write("spawned\n")

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
                "env_allowlist": ["FAKE_UPSTREAM_TOKEN"],
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
    assert call_row["args"]["arguments"]["text"] == "[redacted]"
    search_row = next(row for row in rows if row["tool"] == "tools_search")
    assert search_row["args"]["query"] == "[redacted]"
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


# Misbehaving upstreams for lifecycle refusal tests. Both complete the MCP
# initialize handshake correctly, then go bad on the next request.
SILENT_UPSTREAM = r'''
import json
import sys

while True:
    line = sys.stdin.readline()
    if not line:
        break
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if msg.get("method") == "initialize" and "id" in msg:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "silent", "version": "0"}}}) + "\n")
        sys.stdout.flush()
    # every other request is swallowed forever
'''

GARBAGE_UPSTREAM = r'''
import json
import sys

while True:
    line = sys.stdin.readline()
    if not line:
        break
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if msg.get("method") == "initialize" and "id" in msg:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "garbage", "version": "0"}}}) + "\n")
        sys.stdout.flush()
    elif "id" in msg:
        sys.stdout.write("<<< THIS IS NOT JSON-RPC >>>\n")
        sys.stdout.flush()
'''


def misbehaving_gateway(tmp_path: Path, source: str, **spec_extra) -> Gateway:
    script = tmp_path / "bad_upstream.py"
    script.write_text(source, encoding="utf-8")
    config = {
        "upstreams": [
            {"name": "bad", "command": sys.executable, "args": [str(script)], **spec_extra}
        ]
    }
    return Gateway(config, AuditLog(tmp_path / "audit.jsonl"))


def test_upstream_lazy_spawn_and_reuse(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths)
    try:
        client = gateway.upstreams["fake"]
        assert not fixture_paths["marker"].exists(), "no upstream process before first need"
        gateway.tools_schema({"tool": "fake.echo"})
        pid = client.process.pid
        gateway.tools_call({"tool": "fake.add", "arguments": {"a": 1, "b": 2}})
        gateway.tools_schema({"tool": "fake.add"})
        gateway.tools_call({"tool": "fake.echo", "arguments": {"text": "again"}})
        assert client.spawn_count == 1, "the upstream must be reused, not respawned"
        assert client.process.pid == pid
        assert fixture_paths["marker"].read_text(encoding="utf-8").count("spawned") == 1
    finally:
        gateway.shutdown()


def test_clean_shutdown_terminates_upstreams(fixture_paths: dict) -> None:
    gateway = make_gateway(fixture_paths)
    gateway.tools_schema({"tool": "fake.echo"})
    process = gateway.upstreams["fake"].process
    assert process.poll() is None, "upstream alive before shutdown"
    gateway.shutdown()
    assert process.poll() is not None, "shutdown must terminate the upstream process"
    assert not gateway.upstreams["fake"].started


def test_failed_upstream_spawn_is_structured_refusal(tmp_path: Path) -> None:
    # Absolute, outside the temp root (temp-dir commands are a -32006 policy
    # refusal at local-restricted), but non-existent: spawning must fail.
    ghost_command = str(Path(sys.executable).parent / "no-such-exe-12345")
    config = {"upstreams": [{"name": "ghost", "command": ghost_command}]}
    gateway = Gateway(config, AuditLog(tmp_path / "audit.jsonl"))
    server = StdioServer(build_gateway_registry(gateway))
    try:
        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "tools_schema", "arguments": {"tool": "ghost.anything"}},
            }
        )
        assert "result" not in response
        assert response["error"]["code"] == UPSTREAM_START_FAILED
        assert "ghost" in response["error"]["message"]
    finally:
        gateway.shutdown()
    rows = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows and rows[-1]["ok"] is False
    assert rows[-1]["error"], "refusals must leave a redacted audit trail"
    assert str(tmp_path) not in json.dumps(rows), "audit must not leak local paths"


def test_upstream_request_timeout_is_structured_refusal(tmp_path: Path) -> None:
    gateway = misbehaving_gateway(tmp_path, SILENT_UPSTREAM, request_timeout_seconds=0.5)
    try:
        client = gateway.upstreams["bad"]
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_schema({"tool": "bad.anything"})
        assert excinfo.value.code == UPSTREAM_TIMEOUT
        assert "timed out" in str(excinfo.value)
        assert not client.started, "a timed-out upstream must be terminated, not reused"
    finally:
        gateway.shutdown()


def test_upstream_malformed_response_is_structured_refusal(tmp_path: Path) -> None:
    gateway = misbehaving_gateway(tmp_path, GARBAGE_UPSTREAM)
    try:
        client = gateway.upstreams["bad"]
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_schema({"tool": "bad.anything"})
        assert excinfo.value.code == UPSTREAM_PROTOCOL_ERROR
        assert "malformed" in str(excinfo.value)
        assert "<<<" not in str(excinfo.value), "garbage must never be propagated"
        assert not client.started, "a garbage-talking upstream must be terminated"
    finally:
        gateway.shutdown()


def test_timeout_configuration_and_validation(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.json"
    config_path.write_text(
        json.dumps(
            {
                "request_timeout_seconds": 9,
                "upstreams": [
                    {"name": "a", "command": "x", "startup_timeout_seconds": 2.5},
                    {"name": "b", "command": "y"},
                ],
            }
        ),
        encoding="utf-8",
    )
    gateway = Gateway(load_gateway_config(config_path), AuditLog(tmp_path / "audit.jsonl"))
    assert gateway.upstreams["a"].startup_timeout == 2.5  # per-upstream override
    assert gateway.upstreams["a"].request_timeout == 9.0  # config-level default
    assert gateway.upstreams["b"].request_timeout == 9.0

    for bad in ({"request_timeout_seconds": "fast"}, {"startup_timeout_seconds": -1}):
        bad_path = tmp_path / "bad.json"
        bad_path.write_text(
            json.dumps({"upstreams": [{"name": "a", "command": "x", **bad}]}), encoding="utf-8"
        )
        with pytest.raises(GatewayConfigError):
            load_gateway_config(bad_path)


def test_audit_file_never_leaks_secrets(fixture_paths: dict) -> None:
    """Representative call with every sensitive category; grep the audit file."""
    secrets = {
        "api_token": "tok-PLAINTEXT-TOKEN-VALUE",
        "Authorization": "Bearer PLAINTEXT-BEARER-VALUE",
        "password": "PLAINTEXT-PASSWORD",
        "proof": "PLAINTEXT-PROOF-VALUE",
        "prompt": "PLAINTEXT private user prompt text",
        "skill_body": "PLAINTEXT SKILL BODY CONTENT",
        "env": {"MY_SERVICE_TOKEN": "PLAINTEXT-ENV-VALUE"},
        "private_key": "-----BEGIN RSA PRIVATE KEY-----PLAINTEXTKEY-----",
    }
    keyless = {
        "note": r"see C:\Users\tedja\private\notes.txt for details",
        "checksum": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        "header_blob": "Bearer PLAINTEXT-UNKEYED-BEARER",
    }
    gateway = make_gateway(fixture_paths)
    registry = build_gateway_registry(gateway)
    try:
        result = registry["tools_call"]["handler"](
            {"tool": "fake.echo", "arguments": {"text": "visible-result", **secrets, **keyless}}
        )
        assert result["content"][0]["text"].startswith("echo:")
        with pytest.raises(ToolError):
            registry["tools_call"]["handler"]({"tool": "fake.nope", "arguments": {}})
    finally:
        gateway.shutdown()

    audit_text = fixture_paths["audit"].read_text(encoding="utf-8")
    assert "PLAINTEXT" not in audit_text, "no token/proof/prompt/body/env value may leak"
    assert "deadbeef" not in audit_text, "secret-shaped values must be redacted even unkeyed"
    assert "tedja" not in audit_text and "private\\notes" not in audit_text, "no local paths"
    assert "echo:" not in audit_text, "tool results are never audited"
    assert "[redacted]" in audit_text and "[path]" in audit_text
    rows = [json.loads(line) for line in audit_text.splitlines() if line.strip()]
    assert any(row["ok"] is False and row.get("error") for row in rows), "failures are audited too"


def test_redact_and_scrub_paths(tmp_path: Path) -> None:
    payload = {
        "api_token": "secretvalue",
        "Authorization": "Bearer abc",
        "PASSWORD": "p",
        "proof_of_work": "x",
        "private_key": "k",
        "client_secret": "s",
        "query": "private search query",
        "text": "ok " + "y" * 500,
        "nested": [{"session_token": "t2", "count": 3}],
    }
    redacted = redact(payload)
    dumped = json.dumps(redacted)
    for secret in ("secretvalue", "Bearer abc", '"p"', '"x"', '"k"', '"s"', '"t2"'):
        assert secret not in dumped
    assert redacted["nested"][0]["count"] == 3
    assert redacted["query"] == "[redacted]"
    assert redacted["text"] == "[redacted]"
    scrubbed = scrub_paths(r"failed at C:\Users\tedja\secret\file.txt and /home/user/x.txt")
    assert "tedja" not in scrubbed and "/home/user" not in scrubbed
    assert "[path]" in scrubbed
    assert default_audit_path(tmp_path) == tmp_path / ".learning" / "mcp-audit.jsonl"
