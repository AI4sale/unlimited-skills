from __future__ import annotations

import io
import json

from unlimited_skills import __version__
from unlimited_skills.mcp.protocol import (
    FRAMING_CONTENT_LENGTH,
    FRAMING_NEWLINE,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    MAX_FRAME_BYTES,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    MessageStream,
    RefusalError,
    StdioServer,
    ToolError,
    make_error,
    make_response,
)


def echo_registry() -> dict:
    def echo(arguments: dict) -> dict:
        return {"echoed": arguments.get("text", "")}

    def boom(arguments: dict) -> dict:
        raise ToolError("boom failed")

    return {
        "echo": {"description": "Echo text back.", "inputSchema": {"type": "object"}, "handler": echo},
        "boom": {"description": "Always fails.", "inputSchema": {"type": "object"}, "handler": boom},
    }


def make_server(reader: io.BytesIO, writer: io.BytesIO) -> StdioServer:
    return StdioServer(echo_registry(), server_name="test-server", reader=reader, writer=writer)


def request(request_id, method, params=None) -> dict:
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def newline_frames(messages: list[dict]) -> bytes:
    return b"".join(json.dumps(m).encode("utf-8") + b"\n" for m in messages)


def content_length_frames(messages: list[dict]) -> bytes:
    out = b""
    for message in messages:
        payload = json.dumps(message).encode("utf-8")
        out += b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" + payload
    return out


def parse_newline_responses(raw: bytes) -> list[dict]:
    return [json.loads(line) for line in raw.split(b"\n") if line.strip()]


def parse_content_length_responses(raw: bytes) -> list[dict]:
    stream = MessageStream(io.BytesIO(raw), io.BytesIO())
    responses = []
    while True:
        message = stream.read()
        if message is None:
            break
        responses.append(message)
    assert stream.framing == FRAMING_CONTENT_LENGTH
    return responses


def run_session(frames: bytes) -> tuple[list[dict], StdioServer]:
    reader = io.BytesIO(frames)
    writer = io.BytesIO()
    server = make_server(reader, writer)
    server.serve_forever()
    if server.stream.framing == FRAMING_CONTENT_LENGTH:
        return parse_content_length_responses(writer.getvalue()), server
    return parse_newline_responses(writer.getvalue()), server


LIFECYCLE = [
    request(1, "initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}}),
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    request(2, "tools/list"),
    request(3, "ping"),
]


def assert_lifecycle(responses: list[dict]) -> None:
    by_id = {item.get("id"): item for item in responses}
    init = by_id[1]["result"]
    assert init["protocolVersion"] == PROTOCOL_VERSION
    assert init["capabilities"] == {"tools": {}}
    assert init["serverInfo"]["name"] == "test-server"
    assert init["serverInfo"]["version"] == __version__
    tools = by_id[2]["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["boom", "echo"]
    assert all("description" in tool and "inputSchema" in tool for tool in tools)
    assert by_id[3]["result"] == {}


def test_newline_framing_lifecycle() -> None:
    responses, server = run_session(newline_frames(LIFECYCLE))
    assert server.stream.framing == FRAMING_NEWLINE
    assert server.initialized is True
    assert_lifecycle(responses)


def test_content_length_framing_lifecycle() -> None:
    responses, server = run_session(content_length_frames(LIFECYCLE))
    assert server.stream.framing == FRAMING_CONTENT_LENGTH
    assert server.initialized is True
    assert_lifecycle(responses)


def test_tools_call_success_and_tool_error() -> None:
    frames = newline_frames(
        [
            request(1, "tools/call", {"name": "echo", "arguments": {"text": "hi"}}),
            request(2, "tools/call", {"name": "boom", "arguments": {}}),
        ]
    )
    responses, _ = run_session(frames)
    ok = responses[0]["result"]
    assert ok["isError"] is False
    assert json.loads(ok["content"][0]["text"]) == {"echoed": "hi"}
    failed = responses[1]["result"]
    assert failed["isError"] is True
    assert "boom failed" in failed["content"][0]["text"]


def test_error_codes() -> None:
    frames = newline_frames(
        [
            request(1, "no/such/method"),
            request(2, "tools/call", {"name": "missing-tool"}),
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": "not-an-object"},
            {"jsonrpc": "1.0", "id": 4, "method": "tools/list"},
        ]
    )
    responses, _ = run_session(frames)
    by_id = {item.get("id"): item for item in responses}
    assert by_id[1]["error"]["code"] == METHOD_NOT_FOUND
    assert by_id[2]["error"]["code"] == INVALID_PARAMS
    assert by_id[3]["error"]["code"] == INVALID_PARAMS
    assert by_id[4]["error"]["code"] == INVALID_REQUEST


def test_parse_error_keeps_serving() -> None:
    frames = b"this is not json\n" + newline_frames([request(1, "ping")])
    responses, _ = run_session(frames)
    assert responses[0]["error"]["code"] == PARSE_ERROR
    assert responses[0]["id"] is None
    assert responses[1]["result"] == {}


def test_notifications_get_no_response() -> None:
    frames = newline_frames(
        [
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "method": "notifications/unknown-thing"},
        ]
    )
    responses, _ = run_session(frames)
    assert responses == []


def test_make_helpers() -> None:
    assert make_response(5, {"a": 1}) == {"jsonrpc": "2.0", "id": 5, "result": {"a": 1}}
    error = make_error(6, INVALID_PARAMS, "bad", data={"k": "v"})
    assert error["error"] == {"code": INVALID_PARAMS, "message": "bad", "data": {"k": "v"}}


def test_missing_method_and_missing_jsonrpc_rejected() -> None:
    frames = newline_frames(
        [
            {"jsonrpc": "2.0", "id": 1},  # no method
            {"id": 2, "method": "ping"},  # no jsonrpc
            {"jsonrpc": "2.0", "id": 3, "method": 42},  # non-string method
            request(4, "ping"),
        ]
    )
    responses, _ = run_session(frames)
    by_id = {item.get("id"): item for item in responses}
    assert by_id[1]["error"]["code"] == INVALID_REQUEST
    assert by_id[2]["error"]["code"] == INVALID_REQUEST
    assert by_id[3]["error"]["code"] == INVALID_REQUEST
    assert by_id[4]["result"] == {}


def test_batch_requests_rejected_cleanly() -> None:
    batch = json.dumps([request(1, "ping"), request(2, "ping")]).encode("utf-8") + b"\n"
    frames = batch + newline_frames([request(3, "ping")])
    responses, _ = run_session(frames)
    assert responses[0]["error"]["code"] == INVALID_REQUEST
    assert "batch" in responses[0]["error"]["message"].lower()
    assert responses[0]["id"] is None
    assert responses[1]["result"] == {}  # the loop keeps serving


def test_non_object_request_rejected() -> None:
    frames = b'"just a string"\n' + b"12345\n" + newline_frames([request(1, "ping")])
    responses, _ = run_session(frames)
    assert responses[0]["error"]["code"] == INVALID_REQUEST
    assert responses[1]["error"]["code"] == INVALID_REQUEST
    assert responses[2]["result"] == {}


def test_oversized_newline_frame_refused_then_recovers() -> None:
    huge = b'{"pad":"' + b"a" * MAX_FRAME_BYTES + b'"}\n'
    frames = huge + newline_frames([request(1, "ping")])
    responses, _ = run_session(frames)
    assert responses[0]["error"]["code"] == PARSE_ERROR
    assert "limit" in responses[0]["error"]["message"]
    assert responses[1]["result"] == {}


def test_invalid_content_length_header_refused_then_recovers() -> None:
    frames = b"Content-Length: banana\r\n\r\n" + content_length_frames([request(1, "ping")])
    responses, _ = run_session(frames)
    assert responses[0]["error"]["code"] == PARSE_ERROR
    assert responses[1]["result"] == {}


def test_out_of_range_content_length_refused() -> None:
    for raw in (b"Content-Length: 99999999999\r\n\r\n", b"Content-Length: -5\r\n\r\n"):
        responses, _ = run_session(raw)
        assert responses[0]["error"]["code"] == PARSE_ERROR
        assert "out of range" in responses[0]["error"]["message"]


def test_eof_mid_content_length_payload_is_clean_shutdown() -> None:
    frames = b"Content-Length: 100\r\n\r\n" + b'{"jsonrpc"'
    writer = io.BytesIO()
    server = make_server(io.BytesIO(frames), writer)
    server.serve_forever()  # must return promptly: no crash, no hang
    assert writer.getvalue() == b""  # and no garbage response


def test_refusal_error_maps_to_jsonrpc_error() -> None:
    def refuse(arguments: dict) -> dict:
        raise RefusalError(-32001, "upstream unavailable")

    registry = {"refuse": {"description": "", "inputSchema": {"type": "object"}, "handler": refuse}}
    server = StdioServer(registry, reader=io.BytesIO(), writer=io.BytesIO())
    response = server.handle_message(request(1, "tools/call", {"name": "refuse"}))
    assert "result" not in response
    assert response["error"] == {"code": -32001, "message": "upstream unavailable"}


def test_unexpected_internal_error_keeps_serving() -> None:
    reader = io.BytesIO(newline_frames([request(1, "ping"), request(2, "ping")]))
    writer = io.BytesIO()
    server = make_server(reader, writer)
    original = server.handle_message
    calls = {"n": 0}

    def flaky(message):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("handler exploded with /home/user/secret context")
        return original(message)

    server.handle_message = flaky
    server.serve_forever()
    responses = parse_newline_responses(writer.getvalue())
    assert responses[0]["error"]["code"] == INTERNAL_ERROR
    assert "secret" not in json.dumps(responses[0])  # exception details are not leaked
    assert responses[1]["result"] == {}
