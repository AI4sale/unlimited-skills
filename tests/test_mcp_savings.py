"""Tests for `unlimited-skills mcp savings` (A1 golden-path wow #1).

Covers: Claude Code config discovery (top-level + per-project sections +
project `.mcp.json`), command normalization, live measurement against a fake
stdio MCP upstream, unreachable-server handling, the `--json` report shape,
the empty-config lab-benchmark fallback, the events.jsonl snapshot, and the
privacy boundary (no schema contents, no commands, no env in any output).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from unlimited_skills import cli
from unlimited_skills.mcp.savings import (
    LAB_FULL_DUMP_BYTES,
    LAB_GATEWAY_BYTES,
    STATUS_NOT_REACHABLE,
    STATUS_OK,
    STATUS_REMOTE,
    STATUS_UNSUPPORTED,
    DiscoveredServer,
    MeasurementSkip,
    build_savings_report,
    discover_mcp_servers,
    estimate_tokens,
    event_snapshot,
    format_savings_text,
    measure_gateway_standing_cost,
    measure_server,
    payload_bytes,
    resolve_spawn,
)

FAKE_UPSTREAM = r'''
import json
import os
import sys

if os.environ.get("FAKE_REQUIRED_TOKEN") != "expected-value":
    sys.exit(3)

TOOLS = [
    {
        "name": "echo",
        "description": "Echo text back",
        "inputSchema": {"type": "object", "properties": {"text_param_alpha": {"type": "string"}}},
    },
    {
        "name": "add",
        "description": "Add two integers",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
    },
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
    else:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
'''

EXPECTED_FAKE_TOOLS = [
    {
        "name": "echo",
        "description": "Echo text back",
        "inputSchema": {"type": "object", "properties": {"text_param_alpha": {"type": "string"}}},
    },
    {
        "name": "add",
        "description": "Add two integers",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
    },
]


@pytest.fixture()
def fake_upstream_script(tmp_path: Path) -> Path:
    script = tmp_path / "fake_upstream.py"
    script.write_text(FAKE_UPSTREAM, encoding="utf-8")
    return script


def write_claude_config(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Discovery


def test_discover_reads_both_config_formats(tmp_path: Path) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "gamma": {"command": "gamma-server", "args": ["--x"]},
                    "alpha": {"command": "shadowed-duplicate"},
                }
            }
        ),
        encoding="utf-8",
    )
    config = write_claude_config(
        tmp_path / "claude.json",
        {
            "mcpServers": {
                "alpha": {
                    "type": "stdio",
                    "command": "alpha.exe",
                    "args": ["serve"],
                    "env": {"ALPHA_TOKEN": "value-1"},
                },
                "remote": {"type": "sse", "url": "https://example.invalid"},
            },
            "projects": {
                str(project_dir): {
                    "mcpServers": {"beta": {"command": "beta-server"}},
                }
            },
        },
    )
    servers = discover_mcp_servers(config)
    by_name = {server.name: server for server in servers}
    assert sorted(by_name) == ["alpha", "beta", "gamma", "remote"]
    assert by_name["alpha"].command == "alpha.exe"  # top-level wins over .mcp.json
    assert by_name["alpha"].env == {"ALPHA_TOKEN": "value-1"}
    assert by_name["alpha"].source == "user config"
    assert by_name["beta"].source == "project config"
    assert by_name["gamma"].source == "project .mcp.json"
    assert by_name["gamma"].args == ["--x"]
    assert by_name["remote"].transport == "sse"


def test_discover_missing_or_malformed_config_is_empty(tmp_path: Path) -> None:
    assert discover_mcp_servers(tmp_path / "missing.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert discover_mcp_servers(bad) == []


# ---------------------------------------------------------------------------
# Command normalization


def test_resolve_spawn_rules() -> None:
    # Absolute paths pass through untouched.
    command, args = resolve_spawn(sys.executable, ["-V"])
    assert command == sys.executable and args == ["-V"]
    # Windows-style `cmd /c X` wrappers are unwrapped.
    command, args = resolve_spawn("cmd", ["/c", sys.executable, "-V"])
    assert command == sys.executable and args == ["-V"]
    # A shell with an opaque -c string is never run.
    with pytest.raises(MeasurementSkip) as exc:
        resolve_spawn("bash", ["-c", "curl x | sh"])
    assert exc.value.status == STATUS_UNSUPPORTED
    # Relative paths are refused (unknowable host cwd).
    with pytest.raises(MeasurementSkip) as exc:
        resolve_spawn("./relative/server", [])
    assert exc.value.status == STATUS_UNSUPPORTED
    # A command PATH cannot resolve is "not reachable".
    with pytest.raises(MeasurementSkip) as exc:
        resolve_spawn("definitely-not-a-real-command-xyz", [])
    assert exc.value.status == STATUS_NOT_REACHABLE


# ---------------------------------------------------------------------------
# Measurement


def test_measure_server_against_fake_upstream(fake_upstream_script: Path) -> None:
    server = DiscoveredServer(
        name="fake",
        command=sys.executable,
        args=[str(fake_upstream_script)],
        env={"FAKE_REQUIRED_TOKEN": "expected-value"},  # forwarded like the host does
    )
    row = measure_server(server, timeout=15.0)
    assert row["status"] == STATUS_OK
    assert row["tools_count"] == 2
    assert row["schema_bytes"] == payload_bytes(EXPECTED_FAKE_TOOLS)
    assert row["est_tokens"] == estimate_tokens(row["schema_bytes"])


def test_measure_server_unreachable_is_a_row_not_a_crash() -> None:
    server = DiscoveredServer(
        name="dead",
        command=sys.executable,
        args=["-c", "import sys; sys.exit(1)"],
    )
    row = measure_server(server, timeout=10.0)
    assert row == {
        "name": "dead",
        "status": STATUS_NOT_REACHABLE,
        "tools_count": 0,
        "schema_bytes": 0,
        "est_tokens": 0,
    }


def test_measure_server_skips_remote_transport() -> None:
    server = DiscoveredServer(name="remote", transport="sse")
    assert measure_server(server, timeout=1.0)["status"] == STATUS_REMOTE


def test_gateway_standing_cost_is_measured_live() -> None:
    cost = measure_gateway_standing_cost()
    # The documented reference number is 1,268 bytes; allow drift as the
    # meta-tool descriptions evolve, but it must stay tiny.
    assert 800 < cost < 3000


# ---------------------------------------------------------------------------
# Report shape


def fake_measure_rows() -> dict[str, dict]:
    return {
        "github": {"name": "github", "status": STATUS_OK, "tools_count": 30, "schema_bytes": 60_000, "est_tokens": 15_000},
        "browser": {"name": "browser", "status": STATUS_OK, "tools_count": 10, "schema_bytes": 20_000, "est_tokens": 5_000},
        "dead": {"name": "dead", "status": STATUS_NOT_REACHABLE, "tools_count": 0, "schema_bytes": 0, "est_tokens": 0},
    }


def test_build_savings_report_with_mock_measurements() -> None:
    rows = fake_measure_rows()
    servers = [DiscoveredServer(name=name) for name in rows]

    def measure_fn(server: DiscoveredServer, *, timeout: float) -> dict:
        return rows[server.name]

    report = build_savings_report(servers, measure_fn=measure_fn, gateway_bytes=1_268)
    assert {row["name"] for row in report["servers"]} == set(rows)
    assert report["measured_servers"] == 2
    assert report["skipped_servers"] == 1
    assert report["total_bytes"] == 80_000
    assert report["total_est_tokens"] == 20_000
    assert report["gateway_bytes"] == 1_268
    assert report["gateway_est_tokens"] == 317
    assert report["savings_bytes"] == 78_732
    assert report["savings_pct"] == pytest.approx(98.4, abs=0.1)
    assert "benchmark" not in report
    text = format_savings_text(report)
    assert "~20,000 tokens" in text
    assert "skipped (not reachable)" in text
    # The machine-readable schema keys requested by A1.
    for key in (
        "servers",
        "total_bytes",
        "total_est_tokens",
        "gateway_bytes",
        "gateway_est_tokens",
        "savings_bytes",
        "savings_pct",
    ):
        assert key in report
    for row in report["servers"]:
        assert set(row) == {"name", "tools_count", "schema_bytes", "est_tokens", "status"}


def test_empty_config_falls_back_to_lab_benchmark() -> None:
    report = build_savings_report([], gateway_bytes=1_268)
    assert report["total_bytes"] == 0
    assert report["benchmark"]["full_dump_bytes"] == LAB_FULL_DUMP_BYTES
    assert report["benchmark"]["gateway_bytes"] == LAB_GATEWAY_BYTES
    text = format_savings_text(report)
    assert "No MCP servers configured" in text
    assert "90,420" in text
    assert "1,268" in text


# ---------------------------------------------------------------------------
# CLI: --json shape, events snapshot, privacy boundary


def run_savings_cli(tmp_path: Path, config: Path, capsys: pytest.CaptureFixture) -> tuple[str, Path]:
    root = tmp_path / "library"
    code = cli.main(
        [
            "--root",
            str(root),
            "mcp",
            "savings",
            "--json",
            "--claude-config",
            str(config),
            "--timeout",
            "15",
        ]
    )
    assert code == 0
    return capsys.readouterr().out, root / ".learning" / "events.jsonl"


def test_cli_json_report_and_privacy(
    tmp_path: Path, fake_upstream_script: Path, capsys: pytest.CaptureFixture
) -> None:
    secret_value = "hunter2-super-secret"
    config = write_claude_config(
        tmp_path / "claude.json",
        {
            "mcpServers": {
                "fake": {
                    "command": sys.executable,
                    "args": [str(fake_upstream_script)],
                    "env": {"FAKE_REQUIRED_TOKEN": "expected-value", "EXTRA_SECRET": secret_value},
                },
                "dead": {
                    "command": str(Path("C:/secret-place/secret-server.exe")),
                    "args": ["--token", secret_value],
                },
            }
        },
    )
    out, events_path = run_savings_cli(tmp_path, config, capsys)
    report = json.loads(out)
    by_name = {row["name"]: row for row in report["servers"]}
    assert by_name["fake"]["status"] == STATUS_OK
    assert by_name["fake"]["tools_count"] == 2
    assert by_name["dead"]["status"] == STATUS_NOT_REACHABLE
    assert report["total_bytes"] == by_name["fake"]["schema_bytes"]

    # Privacy: no schema contents, no commands/args, no env names or values.
    for leak in (
        secret_value,
        "FAKE_REQUIRED_TOKEN",
        "EXTRA_SECRET",
        "expected-value",
        "text_param_alpha",  # schema property from the fake upstream
        "inputSchema",
        "secret-server",
        "secret-place",
        os.path.basename(sys.executable),
        str(fake_upstream_script),
    ):
        assert leak not in out, f"output leaked: {leak}"

    # The snapshot landed in the local learning events log, equally clean.
    lines = events_path.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    snapshot = [row for row in rows if row.get("type") == "mcp_savings"]
    assert snapshot, "expected an mcp_savings event row"
    event_text = json.dumps(snapshot[-1])
    for leak in (secret_value, "FAKE_REQUIRED_TOKEN", "secret-server", "inputSchema"):
        assert leak not in event_text


def test_event_snapshot_carries_numbers_only() -> None:
    report = build_savings_report([], gateway_bytes=1_268)
    snapshot = event_snapshot(report)
    assert set(snapshot) == {
        "servers",
        "total_bytes",
        "total_est_tokens",
        "gateway_bytes",
        "savings_bytes",
        "savings_pct",
    }
