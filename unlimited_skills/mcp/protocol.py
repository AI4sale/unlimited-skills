"""Minimal JSON-RPC 2.0 over stdio with MCP lifecycle support.

Implemented from scratch on the standard library (no external MCP SDK).
Two framing styles are supported and auto-detected from the first bytes:

- newline-delimited JSON (used by Claude Code and most MCP stdio hosts);
- LSP-style ``Content-Length`` headers.

Responses are written in the same framing style that was detected on read,
so lenient hosts and strict LSP-style clients both work.
"""

from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO, Callable

from .. import __version__

PROTOCOL_VERSION = "2024-11-05"

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

FRAMING_NEWLINE = "newline"
FRAMING_CONTENT_LENGTH = "content-length"

ToolHandler = Callable[[dict], Any]


class ToolError(RuntimeError):
    """Tool execution failed; reported as an MCP tool result with isError."""


class ProtocolParseError(ValueError):
    """An incoming frame could not be parsed as JSON."""


def make_response(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str, data: Any = None) -> dict:
    error: dict[str, Any] = {"code": int(code), "message": str(message)}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def tool_result(payload: Any, is_error: bool = False) -> dict:
    """Wrap a handler return value as an MCP ``tools/call`` result."""
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}


class MessageStream:
    """Read/write JSON-RPC messages over a byte stream pair.

    The framing style is auto-detected from the first bytes read and reused
    for every write. Until detection, writes default to newline-delimited.
    """

    def __init__(self, reader: BinaryIO, writer: BinaryIO, framing: str | None = None) -> None:
        self.reader = reader
        self.writer = writer
        self.framing = framing

    def read(self) -> Any:
        """Return one parsed message, or ``None`` on EOF.

        Raises :class:`ProtocolParseError` when a frame is not valid JSON.
        """
        while True:
            line = self.reader.readline()
            if not line:
                return None
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower().startswith(b"content-length:"):
                if self.framing is None:
                    self.framing = FRAMING_CONTENT_LENGTH
                try:
                    length = int(stripped.split(b":", 1)[1].strip())
                except ValueError as exc:
                    raise ProtocolParseError("Invalid Content-Length header.") from exc
                while True:
                    header = self.reader.readline()
                    if not header or not header.strip():
                        break
                payload = self.reader.read(length)
                if payload is None or len(payload) < length:
                    return None
                return self._parse(payload)
            if self.framing is None:
                self.framing = FRAMING_NEWLINE
            return self._parse(stripped)

    def _parse(self, payload: bytes) -> Any:
        try:
            return json.loads(payload.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise ProtocolParseError("Invalid JSON payload.") from exc

    def write(self, message: dict) -> None:
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
        if self.framing == FRAMING_CONTENT_LENGTH:
            self.writer.write(b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n")
            self.writer.write(payload)
        else:
            self.writer.write(payload + b"\n")
        self.writer.flush()


class StdioServer:
    """A reusable MCP server loop over stdio.

    ``tools`` is a registry mapping tool name to a dict with keys
    ``description`` (str), ``inputSchema`` (JSON Schema dict), and
    ``handler`` (callable taking the arguments dict).
    """

    def __init__(
        self,
        tools: dict[str, dict],
        server_name: str = "unlimited-skills",
        server_version: str | None = None,
        reader: BinaryIO | None = None,
        writer: BinaryIO | None = None,
    ) -> None:
        self.tools = dict(tools)
        self.server_name = server_name
        self.server_version = server_version or __version__
        self.stream = MessageStream(
            reader if reader is not None else sys.stdin.buffer,
            writer if writer is not None else sys.stdout.buffer,
        )
        self.initialized = False

    def list_tools(self) -> list[dict]:
        listing = []
        for name in sorted(self.tools):
            spec = self.tools[name]
            listing.append(
                {
                    "name": name,
                    "description": str(spec.get("description") or ""),
                    "inputSchema": spec.get("inputSchema") or {"type": "object"},
                }
            )
        return listing

    def handle_message(self, message: Any) -> dict | None:
        """Handle one decoded message. Returns a response dict or ``None``."""
        if not isinstance(message, dict):
            return make_error(None, INVALID_REQUEST, "Request must be a JSON object.")
        is_request = "id" in message
        msg_id = message.get("id")
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str) or not method:
            if not is_request:
                return None
            return make_error(msg_id, INVALID_REQUEST, "Expected a JSON-RPC 2.0 request with a method.")
        if not is_request:
            if method == "notifications/initialized":
                self.initialized = True
            return None
        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return make_error(msg_id, INVALID_PARAMS, "params must be an object.")
        if method == "initialize":
            return make_response(
                msg_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": self.server_name, "version": self.server_version},
                },
            )
        if method == "ping":
            return make_response(msg_id, {})
        if method == "tools/list":
            return make_response(msg_id, {"tools": self.list_tools()})
        if method == "tools/call":
            return self._handle_tools_call(msg_id, params)
        return make_error(msg_id, METHOD_NOT_FOUND, f"Unknown method: {method}")

    def _handle_tools_call(self, msg_id: Any, params: dict) -> dict:
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return make_error(msg_id, INVALID_PARAMS, "tools/call requires a string tool name.")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return make_error(msg_id, INVALID_PARAMS, "tools/call arguments must be an object.")
        spec = self.tools.get(name)
        if spec is None:
            return make_error(msg_id, INVALID_PARAMS, f"Unknown tool: {name}")
        try:
            result = spec["handler"](arguments)
        except ToolError as exc:
            return make_response(msg_id, tool_result(str(exc), is_error=True))
        except Exception as exc:  # noqa: BLE001 - tool failures must not kill the server loop
            return make_response(msg_id, tool_result(f"{type(exc).__name__}: {exc}", is_error=True))
        if isinstance(result, dict) and "content" in result:
            return make_response(msg_id, result)
        return make_response(msg_id, tool_result(result))

    def serve_forever(self) -> None:
        while True:
            try:
                message = self.stream.read()
            except ProtocolParseError as exc:
                self.stream.write(make_error(None, PARSE_ERROR, str(exc)))
                continue
            if message is None:
                return
            response = self.handle_message(message)
            if response is not None:
                self.stream.write(response)
