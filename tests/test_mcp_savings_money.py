"""Tests for the R2 MCP-savings money block (O064-R2-03).

Uses injected ``server_payloads`` + ``gateway_payload_text`` so nothing spawns a
real MCP server; the deterministic counter is words-per-text.
"""

from __future__ import annotations

from unlimited_skills import mcp_savings as ms
from unlimited_skills.mcp.savings import STATUS_OK, STATUS_NOT_REACHABLE


def _word_counter(text: str) -> int:
    return len(text.split())


# A realistic upstream tools/list dwarfs the 3 gateway meta-tools.
UPSTREAM_ROWS = [
    {"name": "srv-a", "status": STATUS_OK, "tools_count": 40,
     "payload_text": "tool schema text " * 200},
    {"name": "srv-b", "status": STATUS_OK, "tools_count": 25,
     "payload_text": "another big schema blob " * 150},
    {"name": "srv-c", "status": STATUS_NOT_REACHABLE, "tools_count": 0, "payload_text": ""},
]
GATEWAY_TEXT = "tools_search tools_schema tools_call meta tool listing"  # ~8 words


def test_mcp_savings_exact_path_counts_only_ok_servers():
    block = ms.build_mcp_savings(
        provider="anthropic", model_api_id="claude-opus-4-8",
        server_payloads=UPSTREAM_ROWS, gateway_payload_text=GATEWAY_TEXT,
        exact_counter=_word_counter,
    )
    assert block["baseline_server_count"] == 3
    assert block["measured_server_count"] == 2
    assert block["skipped_server_count"] == 1
    assert block["baseline_material"] == "full_upstream_tools_list_for_all_configured_servers"
    assert block["actual_material"] == "gateway_meta_tools_list"
    # baseline = words of the two OK payloads joined; actual = words of gateway text.
    assert block["baseline_tokens"] == _word_counter(
        UPSTREAM_ROWS[0]["payload_text"] + "\n" + UPSTREAM_ROWS[1]["payload_text"]
    )
    assert block["actual_gateway_tokens"] == _word_counter(GATEWAY_TEXT)
    assert block["tokens_saved_per_event"] == block["baseline_tokens"] - block["actual_gateway_tokens"]
    assert block["tokens_saved_per_event"] > 0
    assert block["token_counter"]["exact_for_model"] is True
    assert block["token_counter"]["release_acceptable"] is True
    assert block["token_count_privacy"]["provider_count_tokens_used"] is True


def test_mcp_savings_event_count_scales_total():
    block = ms.build_mcp_savings(
        provider="anthropic", model_api_id="claude-opus-4-8",
        server_payloads=UPSTREAM_ROWS, gateway_payload_text=GATEWAY_TEXT,
        exact_counter=_word_counter, event_count=5,
    )
    assert block["event_count"] == 5
    assert block["total_tokens_saved"] == block["tokens_saved_per_event"] * 5


def test_mcp_savings_fallback_not_release_acceptable():
    block = ms.build_mcp_savings(
        provider="anthropic", model_api_id="claude-opus-4-8",
        server_payloads=UPSTREAM_ROWS, gateway_payload_text=GATEWAY_TEXT,
    )
    assert block["token_counter"]["method"] == "bytes_divided_by_4"
    assert block["token_counter"]["release_acceptable"] is False
    assert block["token_count_privacy"]["provider_count_tokens_used"] is False


def test_mcp_savings_no_servers_clamps_to_zero():
    block = ms.build_mcp_savings(
        provider="anthropic", model_api_id="claude-opus-4-8",
        server_payloads=[], gateway_payload_text=GATEWAY_TEXT,
        exact_counter=_word_counter,
    )
    assert block["baseline_server_count"] == 0
    assert block["measured_server_count"] == 0
    assert block["baseline_tokens"] == 0
    assert block["tokens_saved_per_event"] == 0
    assert block["total_tokens_saved"] == 0


def test_mcp_savings_discovers_and_measures_via_injected_fns():
    # No server_payloads: drive discovery + measurement through injected fns.
    class FakeServer:
        def __init__(self, name):
            self.name = name

    def fake_measure(server, *, timeout):
        return {"name": server.name, "status": STATUS_OK, "tools_count": 10,
                "payload_text": "schema " * 100}

    block = ms.build_mcp_savings(
        provider="anthropic", model_api_id="claude-opus-4-8",
        servers=[FakeServer("one"), FakeServer("two")],
        measure_fn=fake_measure, gateway_payload_text=GATEWAY_TEXT,
        exact_counter=_word_counter,
    )
    assert block["baseline_server_count"] == 2
    assert block["measured_server_count"] == 2
    assert block["tokens_saved_per_event"] > 0
