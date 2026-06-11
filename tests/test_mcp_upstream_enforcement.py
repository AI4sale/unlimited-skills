"""E08: enforcement tests for the MCP upstream security model (E07 design).

Covers trust levels, the command allowlist, names-only environment
forwarding, schema/response size refusals, bounded timeouts, audit levels,
and audit rotation -- all per docs/mcp-upstream-security-model.md.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from unlimited_skills.mcp.audit import AuditLog
from unlimited_skills.mcp.gateway import (
    BASE_ENV_VARS,
    COMMAND_NOT_ALLOWED,
    ENV_FORWARDING_DENIED,
    KNOWN_RUNNERS,
    MAX_REQUEST_TIMEOUT,
    MAX_STARTUP_TIMEOUT,
    RESPONSE_TOO_LARGE,
    SCHEMA_TOO_LARGE,
    TRUST_LEVEL_VIOLATION,
    UPSTREAM_DISABLED,
    Gateway,
    GatewayConfigError,
    StdioServer,
    UpstreamClient,
    UpstreamError,
    build_gateway_registry,
    load_gateway_config,
)

# One fake upstream covering env, schema-size, and response-size behavior.
# argv[1]: optional marker file appended to on spawn ("" disables).
FAKE_UPSTREAM = r'''
import json
import os
import sys

marker = sys.argv[1] if len(sys.argv) > 1 else ""
if marker:
    with open(marker, "a", encoding="utf-8") as fh:
        fh.write("spawned\n")

TOOLS = [
    {"name": "echo", "description": "Echo text back",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
    {"name": "env_dump", "description": "Return the child process environment",
     "inputSchema": {"type": "object"}},
    {"name": "blob", "description": "Return a large blob of text",
     "inputSchema": {"type": "object"}},
    {"name": "huge_schema", "description": "Tool with an enormous input schema",
     "inputSchema": {"type": "object", "description": "B" * 100000}},
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
            "serverInfo": {"name": "fake", "version": "0.0.1"},
        }})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo":
            text = "echo:" + str(args.get("text", ""))
        elif name == "env_dump":
            text = json.dumps(dict(os.environ))
        elif name == "blob":
            text = "y" * 100000
        else:
            send({"jsonrpc": "2.0", "id": rid,
                  "error": {"code": -32602, "message": "unknown tool"}})
            continue
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "content": [{"type": "text", "text": text}], "isError": False,
        }})
    else:
        send({"jsonrpc": "2.0", "id": rid,
              "error": {"code": -32601, "message": "unknown method"}})
'''


def write_upstream_script(tmp_path: Path) -> Path:
    script = tmp_path / "fake_upstream.py"
    script.write_text(FAKE_UPSTREAM, encoding="utf-8")
    return script


def gateway_from_config(tmp_path: Path, config: dict) -> Gateway:
    """Round-trip the config through load_gateway_config like production."""
    config_path = tmp_path / "gateway-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return Gateway(load_gateway_config(config_path), AuditLog(tmp_path / "audit.jsonl"))


def upstream_spec(script: Path, marker: Path | None = None, **extra) -> dict:
    spec = {
        "name": "fake",
        "command": sys.executable,
        "args": [str(script), str(marker) if marker else ""],
    }
    spec.update(extra)
    return spec


# ---------------------------------------------------------------------------
# Trust levels: disabled / future-remote-placeholder
# ---------------------------------------------------------------------------


def test_disabled_upstream_is_refused_never_spawned_never_indexed(tmp_path: Path) -> None:
    script = write_upstream_script(tmp_path)
    marker = tmp_path / "spawned.marker"
    config = {
        "schema_version": 1,
        "upstreams": [
            upstream_spec(
                script,
                marker,
                enabled=False,
                tools=[{"name": "echo", "description": "Echo text back"}],
            )
        ],
    }
    gateway = gateway_from_config(tmp_path, config)
    server = StdioServer(build_gateway_registry(gateway))
    try:
        # Pre-declared tools never appear in search for a disabled upstream.
        search = gateway.tools_search({"query": "echo text back"})
        assert search["hits"] == []
        # refresh must not spawn it either.
        gateway.tools_search({"query": "echo", "refresh": True})
        assert not marker.exists(), "a disabled upstream must never be spawned"
        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "tools_call", "arguments": {"tool": "fake.echo"}},
            }
        )
        assert response["error"]["code"] == UPSTREAM_DISABLED
        assert "disabled" in response["error"]["message"]
    finally:
        gateway.shutdown()
    rows = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(row["ok"] is False and row.get("error") for row in rows), "refusals are audited"


def test_trust_disabled_level_equals_enabled_false(tmp_path: Path) -> None:
    script = write_upstream_script(tmp_path)
    gateway = gateway_from_config(
        tmp_path,
        {"upstreams": [upstream_spec(script, trust_level="disabled")]},
    )
    try:
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_schema({"tool": "fake.echo"})
        assert excinfo.value.code == UPSTREAM_DISABLED
    finally:
        gateway.shutdown()


def test_future_remote_placeholder_refuses_all_io(tmp_path: Path) -> None:
    script = write_upstream_script(tmp_path)
    marker = tmp_path / "spawned.marker"
    gateway = gateway_from_config(
        tmp_path,
        {
            "upstreams": [
                upstream_spec(
                    script,
                    marker,
                    trust_level="future-remote-placeholder",
                    tools=[{"name": "search_web", "description": "Search the web"}],
                )
            ]
        },
    )
    try:
        assert gateway.tools_search({"query": "search the web"})["hits"] == []
        gateway.tools_search({"query": "web", "refresh": True})  # must not spawn
        assert not marker.exists()
        for meta in (gateway.tools_schema, gateway.tools_call):
            with pytest.raises(UpstreamError) as excinfo:
                meta({"tool": "fake.search_web"})
            assert excinfo.value.code == TRUST_LEVEL_VIOLATION
            assert "gate" in str(excinfo.value).lower(), "message must name the unopened gate"
    finally:
        gateway.shutdown()


# ---------------------------------------------------------------------------
# Command allowlist
# ---------------------------------------------------------------------------


def command_client(command: str, trust_level: str) -> UpstreamClient:
    return UpstreamClient({"name": "u", "command": command, "trust_level": trust_level})


def test_relative_command_path_refused_at_local_restricted(tmp_path: Path) -> None:
    gateway = Gateway(
        {"upstreams": [{"name": "rel", "command": "./server.py"}]},
        AuditLog(tmp_path / "audit.jsonl"),
    )
    try:
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_schema({"tool": "rel.anything"})
        assert excinfo.value.code == COMMAND_NOT_ALLOWED
    finally:
        gateway.shutdown()


def test_bare_known_runner_allowed_at_local_trusted_only() -> None:
    for runner in sorted(KNOWN_RUNNERS):
        assert command_client(runner, "local-trusted")._validate_command() == runner
        with pytest.raises(UpstreamError) as excinfo:
            command_client(runner, "local-restricted")._validate_command()
        assert excinfo.value.code == COMMAND_NOT_ALLOWED


def test_unknown_bare_command_refused_at_local_trusted() -> None:
    for command in ("ruby", "perl", "evil-runner"):
        with pytest.raises(UpstreamError) as excinfo:
            command_client(command, "local-trusted")._validate_command()
        assert excinfo.value.code == COMMAND_NOT_ALLOWED


def test_shell_binaries_refused_at_every_trust_level(tmp_path: Path) -> None:
    shells = ("bash", "sh", "cmd", "powershell", "pwsh", str(tmp_path / "cmd.exe"), "/bin/bash")
    for trust in ("local-restricted", "local-trusted"):
        for command in shells:
            with pytest.raises(UpstreamError) as excinfo:
                command_client(command, trust)._validate_command()
            assert excinfo.value.code == COMMAND_NOT_ALLOWED, (trust, command)


def test_temp_dir_commands_refused_at_local_restricted_only(tmp_path: Path) -> None:
    command = str(tmp_path / "server-bin")  # pytest tmp_path lives under the temp root
    with pytest.raises(UpstreamError) as excinfo:
        command_client(command, "local-restricted")._validate_command()
    assert excinfo.value.code == COMMAND_NOT_ALLOWED
    assert command_client(command, "local-trusted")._validate_command() == command


def test_relative_command_refusal_through_server_dispatch(tmp_path: Path) -> None:
    gateway = Gateway(
        {"upstreams": [{"name": "rel", "command": "..\\x.exe"}]},
        AuditLog(tmp_path / "audit.jsonl"),
    )
    server = StdioServer(build_gateway_registry(gateway))
    try:
        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "tools_schema", "arguments": {"tool": "rel.x"}},
            }
        )
        assert response["error"]["code"] == COMMAND_NOT_ALLOWED
    finally:
        gateway.shutdown()


# ---------------------------------------------------------------------------
# Environment forwarding
# ---------------------------------------------------------------------------


def test_env_forwarding_is_base_set_plus_allowlist_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UT_ALLOWED_VALUE", "forward-me")
    monkeypatch.setenv("UT_SECRET_VALUE", "do-not-forward")
    monkeypatch.delenv("UT_MISSING_VALUE", raising=False)
    script = write_upstream_script(tmp_path)
    gateway = gateway_from_config(
        tmp_path,
        {
            "upstreams": [
                upstream_spec(script, env_allowlist=["UT_ALLOWED_VALUE", "UT_MISSING_VALUE"])
            ]
        },
    )
    try:
        result = gateway.tools_call({"tool": "fake.env_dump", "arguments": {}})
        child_env = json.loads(result["content"][0]["text"])
    finally:
        gateway.shutdown()
    assert child_env.get("UT_ALLOWED_VALUE") == "forward-me"
    assert "UT_SECRET_VALUE" not in child_env, "nothing outside the allowlist is forwarded"
    assert "UT_MISSING_VALUE" not in child_env, "names unset in the parent are skipped silently"
    assert "COMSPEC" not in child_env, "COMSPEC is excluded from the base set (no shell)"
    allowed_names = set(BASE_ENV_VARS) | {"UT_ALLOWED_VALUE"}
    extras = {name for name in child_env if name.upper() not in allowed_names}
    assert extras == set(), f"unexpected variables forwarded: {sorted(extras)}"


def test_invalid_env_allowlist_is_runtime_refusal(tmp_path: Path) -> None:
    # The schema/loader already rejects wildcard-ish names; runtime enforces
    # again for configs that bypass the loader.
    script = write_upstream_script(tmp_path)
    gateway = Gateway(
        {"upstreams": [upstream_spec(script, env_allowlist=["GITHUB_*"])]},
        AuditLog(tmp_path / "audit.jsonl"),
    )
    try:
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_schema({"tool": "fake.echo"})
        assert excinfo.value.code == ENV_FORWARDING_DENIED
    finally:
        gateway.shutdown()


def test_env_wildcard_rejected_at_load(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.json"
    config_path.write_text(
        json.dumps({"upstreams": [{"name": "a", "command": "/x", "env_allowlist": ["AWS_*"]}]}),
        encoding="utf-8",
    )
    with pytest.raises(GatewayConfigError):
        load_gateway_config(config_path)


def test_v1_env_literal_map_rejected_at_load(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.json"
    config_path.write_text(
        json.dumps(
            {
                "upstreams": [
                    {"name": "a", "command": "/x", "env": {"TOKEN": "%TOKEN%"}}
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(GatewayConfigError) as excinfo:
        load_gateway_config(config_path)
    assert "env_allowlist" in str(excinfo.value), "the error must point at the replacement"


# ---------------------------------------------------------------------------
# Size limits: refusal, never truncation
# ---------------------------------------------------------------------------


def test_schema_too_large_is_refused_not_truncated(tmp_path: Path) -> None:
    script = write_upstream_script(tmp_path)
    gateway = gateway_from_config(
        tmp_path,
        {"upstreams": [upstream_spec(script, max_schema_bytes=2048)]},
    )
    try:
        # The small schema still works.
        small = gateway.tools_schema({"tool": "fake.echo"})
        assert small["inputSchema"]["properties"]["text"]["type"] == "string"
        # The oversized one is indexed by name/description (search finds it) ...
        hits = gateway.tools_search({"query": "enormous input schema"})["hits"]
        assert any(hit["tool"] == "fake.huge_schema" for hit in hits)
        # ... but its schema can only ever be refused.
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_schema({"tool": "fake.huge_schema"})
        assert excinfo.value.code == SCHEMA_TOO_LARGE
        message = str(excinfo.value)
        assert "2048" in message, "the refusal names the allowed size"
        assert "BBBB" not in message, "the refusal never embeds schema content"
    finally:
        gateway.shutdown()


def test_response_too_large_is_dropped_not_trimmed(tmp_path: Path) -> None:
    script = write_upstream_script(tmp_path)
    gateway = gateway_from_config(
        tmp_path,
        {"upstreams": [upstream_spec(script, max_response_bytes=65536)]},
    )
    try:
        ok = gateway.tools_call({"tool": "fake.echo", "arguments": {"text": "hi"}})
        assert ok["content"][0]["text"] == "echo:hi"
        with pytest.raises(UpstreamError) as excinfo:
            gateway.tools_call({"tool": "fake.blob", "arguments": {}})
        assert excinfo.value.code == RESPONSE_TOO_LARGE
        message = str(excinfo.value)
        assert "65536" in message
        assert "yyyy" not in message, "the refusal never embeds result content"
    finally:
        gateway.shutdown()


def test_trust_level_ceilings_clamp_and_reject(tmp_path: Path) -> None:
    # local-restricted: limits above the restricted ceilings are a load error.
    for key, value in (("max_schema_bytes", 262144 + 1), ("max_response_bytes", 1048576 + 1)):
        config_path = tmp_path / "cfg.json"
        config_path.write_text(
            json.dumps({"upstreams": [{"name": "a", "command": "/x", key: value}]}),
            encoding="utf-8",
        )
        with pytest.raises(GatewayConfigError) as excinfo:
            load_gateway_config(config_path)
        assert "ceiling" in str(excinfo.value)
    # The same values load fine at local-trusted (within the trusted ceilings).
    config_path = tmp_path / "cfg.json"
    config_path.write_text(
        json.dumps(
            {
                "upstreams": [
                    {
                        "name": "a",
                        "command": "/x",
                        "trust_level": "local-trusted",
                        "max_schema_bytes": 262144 + 1,
                        "max_response_bytes": 1048576 + 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    load_gateway_config(config_path)
    # Runtime clamping protects even loader-bypassing configs.
    client = UpstreamClient({"name": "a", "command": "/x", "max_response_bytes": 8388608})
    assert client.max_response_bytes == 1048576, "restricted ceiling clamps the value"


# ---------------------------------------------------------------------------
# Timeout hard bounds
# ---------------------------------------------------------------------------


def test_timeouts_above_hard_bounds_rejected_at_load(tmp_path: Path) -> None:
    cases = (
        {"request_timeout_seconds": MAX_REQUEST_TIMEOUT + 1},
        {"startup_timeout_seconds": MAX_STARTUP_TIMEOUT + 1},
    )
    for case in cases:
        for placement in ("top", "upstream"):
            config = {"upstreams": [{"name": "a", "command": "/x"}]}
            if placement == "top":
                config.update(case)
            else:
                config["upstreams"][0].update(case)
            config_path = tmp_path / "cfg.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with pytest.raises(GatewayConfigError) as excinfo:
                load_gateway_config(config_path)
            assert "hard bound" in str(excinfo.value), (case, placement)


def test_timeouts_clamped_at_runtime_for_direct_configs() -> None:
    client = UpstreamClient(
        {"name": "a", "command": "/x", "request_timeout_seconds": 9e9, "startup_timeout_seconds": 9e9}
    )
    assert client.request_timeout == MAX_REQUEST_TIMEOUT
    assert client.startup_timeout == MAX_STARTUP_TIMEOUT


# ---------------------------------------------------------------------------
# Audit: levels, rotation, settings validation
# ---------------------------------------------------------------------------


def test_audit_level_minimal_writes_only_the_minimal_fields(tmp_path: Path) -> None:
    script = write_upstream_script(tmp_path)
    audit_path = tmp_path / "audit.jsonl"
    config = {"upstreams": [upstream_spec(script, audit_level="minimal")]}
    config_path = tmp_path / "cfg.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    gateway = Gateway(load_gateway_config(config_path), AuditLog(audit_path))
    registry = build_gateway_registry(gateway)
    try:
        registry["tools_call"]["handler"](
            {"tool": "fake.echo", "arguments": {"text": "sensitive-shape", "api_token": "tok"}}
        )
        with pytest.raises(Exception):
            registry["tools_schema"]["handler"]({"tool": "fake.huge_schema_missing"})
    finally:
        gateway.shutdown()
    rows = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows, "calls are always observable -- there is no 'off'"
    for row in rows:
        assert set(row) == {"ts", "tool", "upstream", "duration_ms", "ok"}, row
    assert any(row["ok"] is False for row in rows), "refusals still leave an ok:false entry"
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "sensitive-shape" not in audit_text and "tok" not in audit_text


def test_audit_rotation_caps_size_and_generations(tmp_path: Path) -> None:
    audit_path = tmp_path / "mcp-audit.jsonl"
    audit = AuditLog(audit_path, max_bytes=400, max_files=2)
    for index in range(60):
        audit.record(tool="tools_call", upstream="fake", duration_ms=1.0, ok=True,
                     arguments={"tool": f"fake.echo_{index}"})
    assert audit_path.exists()
    generation_1 = tmp_path / "mcp-audit.jsonl.1"
    generation_2 = tmp_path / "mcp-audit.jsonl.2"
    generation_3 = tmp_path / "mcp-audit.jsonl.3"
    assert generation_1.exists() and generation_2.exists(), "rotation must produce generations"
    assert not generation_3.exists(), "generations beyond audit_max_files are deleted"
    for path in (audit_path, generation_1, generation_2):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                assert json.loads(line)["tool"] == "tools_call"


def test_gateway_applies_audit_rotation_settings_from_config(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    Gateway(
        {"audit_max_bytes": 65536, "audit_max_files": 1, "upstreams": []},
        audit,
    )
    assert audit.max_bytes == 65536
    assert audit.max_files == 1


def test_audit_settings_validated_at_load(tmp_path: Path) -> None:
    for bad in ({"audit_max_bytes": 1024}, {"audit_max_files": 0}, {"audit_max_files": 21}):
        config_path = tmp_path / "cfg.json"
        config_path.write_text(json.dumps({**bad, "upstreams": []}), encoding="utf-8")
        with pytest.raises(GatewayConfigError):
            load_gateway_config(config_path)


def test_audit_level_off_is_rejected_at_load(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.json"
    config_path.write_text(
        json.dumps({"upstreams": [{"name": "a", "command": "/x", "audit_level": "off"}]}),
        encoding="utf-8",
    )
    with pytest.raises(GatewayConfigError):
        load_gateway_config(config_path)
