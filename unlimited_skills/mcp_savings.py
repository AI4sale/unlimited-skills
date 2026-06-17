"""MCP context savings for the Money Saved meter (O064-R2-03).

Half B of the value model (the other half is Skills, R2-02). The gateway
collapses every configured upstream server's full ``tools/list`` (names +
descriptions + complete input schemas) down to 3 meta-tools, so the standing
context a session carries is:

    baseline = full upstream tools/list of ALL configured MCP servers
    actual   = the gateway's own tools/list (3 meta-tools)
    mcp_tokens_saved (per event) = baseline_tokens - actual_gateway_tokens

Both sides are counted with the SAME counter as skills (Anthropic ``count_tokens``
for Claude; ``bytes // 4`` fallback flagged not-release-acceptable). The byte
heuristic that the legacy ``mcp savings`` report used is FORBIDDEN as the primary
token source here — schemas are JSON-dense and Claude's tokenizer diverges from
4 bytes/token, so we count real tokens.

Discovery and measurement are reused verbatim from :mod:`unlimited_skills.mcp.savings`
(``discover_mcp_servers`` / ``measure_server_payload`` spawn the user's own
configured servers locally). Only token COUNTS land in the output block; the
schema text is fed to the counter and never persisted (see
:func:`unlimited_skills.token_counting.token_count_privacy`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .mcp.savings import (
    DEFAULT_SERVER_TIMEOUT,
    STATUS_OK,
    discover_mcp_servers,
    gateway_tools_list_payload_text,
    measure_server_payload,
)
from .token_counting import count_tokens, token_count_privacy

BASELINE_MATERIAL = "full_upstream_tools_list_for_all_configured_servers"
ACTUAL_MATERIAL = "gateway_meta_tools_list"


def gateway_is_configured(
    *,
    home: Path | None = None,
    claude_json_path: Path | None = None,
    servers: list | None = None,
) -> bool:
    """True only if the Unlimited Tools gateway actually fronts the MCP servers.

    MCP money is honest ONLY when our gateway is the configured MCP front — then
    we proxy every upstream and the baseline/savings are both real and measured.
    Otherwise the host talks to its servers directly (we are not in the loop), so
    we must not report any MCP saving. Detected by scanning the host's configured
    MCP servers for our gateway entrypoint.
    """
    discovered = servers if servers is not None else discover_mcp_servers(claude_json_path, home=home)
    for server in discovered:
        name = (getattr(server, "name", "") or "").lower()
        cmd = (getattr(server, "command", "") or "").lower()
        args = " ".join(str(a) for a in getattr(server, "args", []) or []).lower()
        blob = f"{name} {cmd} {args}"
        if ("unlimited-skills" in blob or "unlimited_skills" in blob) and "gateway" in blob:
            return True
        if name in {"unlimited-tools", "unlimited-tools-gateway", "unlimited-skills-gateway"}:
            return True
    return False


def inventory_server_payloads(
    *,
    servers: list | None = None,
    measure_fn: Callable[..., dict] | None = None,
    timeout: float = DEFAULT_SERVER_TIMEOUT,
    home: Path | None = None,
    claude_json_path: Path | None = None,
) -> list[dict]:
    """Measure every configured MCP server's ``tools/list`` payload text."""
    discovered = servers if servers is not None else discover_mcp_servers(claude_json_path, home=home)
    measure = measure_fn or measure_server_payload
    return [measure(server, timeout=timeout) for server in discovered]


def build_mcp_savings(
    *,
    provider: str,
    model_api_id: str | None = None,
    server_payloads: list[dict] | None = None,
    servers: list | None = None,
    measure_fn: Callable[..., dict] | None = None,
    gateway_payload_text: str | None = None,
    exact_counter: Callable[[str], int] | None = None,
    event_count: int = 1,
    timeout: float = DEFAULT_SERVER_TIMEOUT,
    home: Path | None = None,
    claude_json_path: Path | None = None,
) -> dict[str, Any]:
    """Build the ``mcp_savings`` block (R2 spec §3).

    ``server_payloads`` may be supplied directly (tests / cached measurement);
    else the configured servers are discovered and measured. ``gateway_payload_text``
    defaults to the gateway's live ``tools/list``. ``event_count`` scales
    ``total_tokens_saved`` (the events module supplies the real count).
    """
    rows = (
        server_payloads
        if server_payloads is not None
        else inventory_server_payloads(
            servers=servers, measure_fn=measure_fn, timeout=timeout, home=home, claude_json_path=claude_json_path
        )
    )
    ok_rows = [row for row in rows if row.get("status") == STATUS_OK]
    baseline_text = "\n".join(row.get("payload_text", "") for row in ok_rows)
    actual_text = (
        gateway_payload_text if gateway_payload_text is not None else gateway_tools_list_payload_text()
    )

    baseline_tc = count_tokens(
        baseline_text, provider=provider, model_api_id=model_api_id, exact_counter=exact_counter
    )
    actual_tc = count_tokens(
        actual_text, provider=provider, model_api_id=model_api_id, exact_counter=exact_counter
    )
    saved_per_event = max(0, baseline_tc.tokens - actual_tc.tokens)
    events = max(1, int(event_count))

    return {
        "baseline_server_count": len(rows),
        "measured_server_count": len(ok_rows),
        "skipped_server_count": len(rows) - len(ok_rows),
        "baseline_material": BASELINE_MATERIAL,
        "baseline_tokens": baseline_tc.tokens,
        "actual_material": ACTUAL_MATERIAL,
        "actual_gateway_tokens": actual_tc.tokens,
        "tokens_saved_per_event": saved_per_event,
        "event_count": events,
        "total_tokens_saved": saved_per_event * events,
        "token_counter": baseline_tc.descriptor(),
        "token_count_privacy": token_count_privacy(
            provider_count_tokens_used=baseline_tc.used_provider_api
        ),
    }
