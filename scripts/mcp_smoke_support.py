from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SKILL_BODY_MARKER = "SKILL_BODY_MARKER_DO_NOT_LEAK"
PRIVATE_PACK_MARKER = "PRIVATE_PACK_BODY_DO_NOT_LEAK"
TOKEN_MARKER = "TOKEN_MARKER_DO_NOT_LEAK"
PROOF_MARKER = "PROOF_MARKER_DO_NOT_LEAK"
PRIVATE_KEY_MARKER = "PRIVATE_KEY_MARKER_DO_NOT_LEAK"
PROMPT_MARKER = "PROMPT_MARKER_DO_NOT_LEAK"
SEARCH_QUERY_MARKER = "SEARCH_QUERY_DO_NOT_LEAK"
LOCAL_PATH_MARKER = r"C:\Users\tedja\private\mcp-secret.txt"


def write_skill(root: Path, name: str = "debug-build") -> Path:
    skill_file = root / "local" / "skills" / name / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(
        (
            "---\n"
            f"name: {name}\n"
            "description: Debug build failures without leaking bodies\n"
            "---\n\n"
            f"Procedure body. {SKILL_BODY_MARKER}\n"
        ),
        encoding="utf-8",
    )
    return skill_file


def write_fake_upstream(tmp_path: Path) -> tuple[Path, Path]:
    marker = tmp_path / "fake-upstream.spawned"
    script = tmp_path / "fake_upstream.py"
    script.write_text(
        r'''
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text("spawned\n", encoding="utf-8")

TOOLS = {
    "echo": {
        "description": "Echo text back",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        },
    },
    "add": {
        "description": "Add two integers",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
        },
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
'''.lstrip(),
        encoding="utf-8",
    )
    return script, marker


def write_gateway_config(tmp_path: Path, script: Path, marker: Path) -> Path:
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
            },
            {
                "name": "ghost",
                # An absolute non-temp path: the upstream security model refuses
                # temp-dir commands with command_not_allowed before spawning, but
                # this fixture must exercise the spawn-failure refusal instead.
                "command": str(Path(sys.executable).parent / "missing-upstream-executable"),
                "tools": [{"name": "missing", "description": "Unavailable upstream tool"}],
            },
        ],
    }
    config_path = tmp_path / "gateway-config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


class JsonRpcProcess:
    def __init__(self, command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        self.process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=merged_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self._next_id = 0

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._write(message)
        return self._read_response(request_id, timeout=timeout)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._write(message)

    def raw_request(self, message: Any, timeout: float = 10.0) -> dict[str, Any]:
        self._write(message)
        expected = message.get("id") if isinstance(message, dict) else None
        return self._read_response(expected, timeout=timeout)

    def _write(self, message: Any) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def _read_response(self, expected_id: Any, timeout: float = 10.0) -> dict[str, Any]:
        assert self.process.stdout is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if not line:
                break
            payload = json.loads(line)
            if expected_id is None or payload.get("id") == expected_id:
                return payload
        stderr = self.read_stderr()
        raise RuntimeError(f"Timed out waiting for JSON-RPC response id={expected_id}; stderr={stderr}")

    def read_stderr(self) -> str:
        if self.process.stderr is None:
            return ""
        try:
            return self.process.stderr.read()
        except ValueError:
            return ""

    def close(self) -> None:
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


def call_tool(client: JsonRpcProcess, name: str, arguments: dict[str, Any] | None = None) -> tuple[dict[str, Any], Any]:
    response = client.request(
        "tools/call",
        {"name": name, "arguments": arguments or {}},
    )
    if "error" in response:
        return response, None
    result = response["result"]
    text = result["content"][0]["text"]
    try:
        return response, json.loads(text)
    except json.JSONDecodeError:
        return response, text


def assert_no_markers(text: str, *, allow_skill_body: bool = False) -> None:
    forbidden = [
        PRIVATE_PACK_MARKER,
        TOKEN_MARKER,
        PROOF_MARKER,
        PRIVATE_KEY_MARKER,
        PROMPT_MARKER,
        SEARCH_QUERY_MARKER,
        LOCAL_PATH_MARKER,
    ]
    if not allow_skill_body:
        forbidden.append(SKILL_BODY_MARKER)
    leaked = [marker for marker in forbidden if marker in text]
    if leaked:
        raise AssertionError(f"Sensitive marker leaked: {leaked}")
