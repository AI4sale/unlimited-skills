"""Free Money Saved meter v2 (O064-R2-05).

The pull surface that turns the two token-savings halves into REAL
API-equivalent dollars. It binds the runtime model (R2-00), prices it (R2-01),
measures the skills (R2-02) and MCP (R2-03) context savings with the same token
counter, and applies the money formula:

    estimated_money_saved_usd = total_tokens_saved / 1_000_000 * price_per_1m_input_tokens

Money is denominated in API-equivalent dollars EVEN on a subscription (a
subscription still consumes usage limits / context budget). It is explicitly NOT
a provider-invoice reconciliation and NOT a guaranteed bill reduction — see
:func:`claim_boundary`.

Schema ``money-saved-meter-v2``. Skills and MCP money are kept separate and then
summed. ``event_count`` scales the headline (the saving re-enters context on
every session start / compaction); the price class defaults to ``cache_write_5m``
(the standing-context re-write class) unless overridden.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from .mcp_savings import build_mcp_savings, gateway_is_configured
from .model_detect import bind_model, binding_error
from .money_events import MONEY_MODEL_VERSION, default_price_class
from .money_pricing import ModelPrice, money_for_tokens, price_per_1m, pricing_basis
from .skills_savings import build_skills_savings
from .token_counting import make_anthropic_counter

METER_V2_SCHEMA = "money-saved-meter-v2"
REPORT_TYPE = "money_saved_meter"

_DASHED_CLAUDE = re.compile(r"^claude-[a-z]+-\d+(-\d+)+$")


def anthropic_api_model_id(price: ModelPrice) -> str:
    """The dashed API model id (e.g. ``claude-opus-4-8``) for count_tokens."""
    for alias in price.aliases:
        if _DASHED_CLAUDE.match(alias):
            return alias
    return price.model.replace(".", "-")


def claim_boundary() -> dict[str, Any]:
    return {
        "money_kind": "api_equivalent_estimate",
        "not_provider_bill_reconciliation": True,
        "not_guaranteed_bill_reduction": True,
        "not_exact_tokens": True,
    }


def _default_events(event_count: int) -> dict[str, Any]:
    n = max(1, int(event_count))
    return {"event_count": n, "event_types": {"compaction": n}}


def build_meter_v2(
    *,
    model: str | None = None,
    agent: str | None = None,
    include_skills: bool = True,
    include_mcp: bool = True,
    token_counter: str = "anthropic",
    price_class: str | None = None,
    event_count: int = 1,
    root: str | Path | None = None,
    skills_descriptors: list[tuple[str, str]] | None = None,
    skills_block: dict[str, Any] | None = None,
    mcp_block: dict[str, Any] | None = None,
    servers: list | None = None,
    server_payloads: list[dict] | None = None,
    gateway_payload_text: str | None = None,
    gateway_fronting: bool | None = None,
    exact_counter: Callable[[str], int] | None = None,
    events: dict[str, Any] | None = None,
    db: dict[str, Any] | None = None,
    profiles: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the ``money-saved-meter-v2`` report."""
    binding = bind_model(model, agent=agent, db=db, profiles=profiles)
    base: dict[str, Any] = {
        "schema_version": METER_V2_SCHEMA,
        "report_type": REPORT_TYPE,
        "money_model_version": MONEY_MODEL_VERSION,
        "model_binding": binding.as_dict(),
    }
    if generated_at is not None:
        base["generated_at"] = generated_at

    # A supported agent should always bind (cascade falls to its assumption
    # profile). A missing binding is an integration bug, surfaced as a diagnostic.
    if not binding.available or binding.price is None:
        base["available"] = False
        base["diagnostic"] = binding_error(binding)
        return base

    price = binding.price
    provider = price.provider
    pc = price_class or default_price_class("compaction")  # cache_write_5m headline
    rate = price_per_1m(price, pc)

    counter = exact_counter
    if counter is None and token_counter == "anthropic" and provider == "anthropic":
        counter = make_anthropic_counter(anthropic_api_model_id(price))

    skills = None
    if include_skills:
        skills = skills_block or build_skills_savings(
            provider=provider, model_api_id=None, root=root,
            descriptors=skills_descriptors, exact_counter=counter, event_count=event_count,
        )
    # MCP money is honest ONLY when our Unlimited Tools gateway actually fronts the
    # servers. If the caller supplied MCP data explicitly (tests / gateway path) we
    # trust it; otherwise we auto-detect. When the gateway is NOT configured we do
    # NOT report MCP at all — no number, no claim (owner: "если гейтвей не включен —
    # не пишем о нём"). Skills are always realized by the router regardless.
    if gateway_fronting is None:
        gateway_fronting = mcp_block is not None or server_payloads is not None or gateway_is_configured()
    mcp_gated_off = bool(include_mcp) and not gateway_fronting
    mcp = None
    if include_mcp and gateway_fronting:
        mcp = mcp_block or build_mcp_savings(
            provider=provider, model_api_id=None, server_payloads=server_payloads,
            servers=servers, gateway_payload_text=gateway_payload_text,
            exact_counter=counter, event_count=event_count,
        )

    skills_tokens = int(skills["total_tokens_saved"]) if skills else 0
    mcp_tokens = int(mcp["total_tokens_saved"]) if mcp else 0
    total_tokens = skills_tokens + mcp_tokens

    # Each money figure is recomputed independently from its token count and the
    # same rate, so an evidence-pack verifier can reproduce every line exactly.
    savings: dict[str, Any] = {}
    if skills is not None:
        savings["skills"] = {**skills, "estimated_money_saved_usd": money_for_tokens(skills_tokens, price, pc)}
    if mcp is not None:
        savings["mcp"] = {**mcp, "estimated_money_saved_usd": money_for_tokens(mcp_tokens, price, pc)}
    savings["total"] = {
        "tokens_saved": total_tokens,
        "estimated_money_saved_usd": money_for_tokens(total_tokens, price, pc),
    }

    privacy = None
    for block in (skills, mcp):
        if block and isinstance(block.get("token_count_privacy"), dict):
            privacy = block["token_count_privacy"]
            break

    report: dict[str, Any] = {
        **base,
        "available": True,
        "pricing": pricing_basis(price, pc),
        "events": events or _default_events(event_count),
        "savings": savings,
        "claim_boundary": claim_boundary(),
    }
    if "skills" in savings:
        report["skills_savings"] = savings["skills"]
    if "mcp" in savings:
        report["mcp_savings"] = savings["mcp"]
    if mcp_gated_off:
        # Gateway not in the loop -> we make no MCP claim at all.
        report["mcp_status"] = {
            "available": False,
            "reason": "gateway_not_configured",
            "note": (
                "MCP savings are reported only when your MCP servers are routed "
                "through the Unlimited Tools gateway. The gateway is not configured "
                "as an MCP server here, so no MCP saving is claimed."
            ),
        }
    if privacy is not None:
        report["token_count_privacy"] = privacy
    return report
