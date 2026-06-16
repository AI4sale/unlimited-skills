"""Money Saved tier surfaces (O064-MSM tier ladder, v0.6.4).

Privacy-safe, local-only paid-tier surfaces built ON TOP of the Registered Money
Saved export (``money_saved_meter.build_registered_export``, schema
``registered-export-v1``). The Registered export already carries ONLY safe
aggregates — exact gateway-call counts, measured bytes (when local artifacts
expose sizes), and token *estimates* with the estimation method preserved — and
never raw prompts/queries, skill bodies, filesystem paths, secrets, or
machine/install/account ids. These tier surfaces aggregate those safe aggregates
and add nothing the Registered export did not already contain.

Tier ladder (each stacks on the previous):

- Team (O064-MSM-TEAM-IMPL): local rollup over multiple Registered exports.

Dollars are disabled by default at every tier: the underlying meter never
configures a local price, so no tier may emit a dollar value. Every artifact is
run through the fail-closed ``assert_money_saved_safe`` gate before it is
returned or serialized, and incompatible/unsafe inputs are rejected rather than
silently aggregated.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from . import __version__
from .money_saved_meter import (
    REGISTERED_EXPORT_SCHEMA_VERSION,
    assert_money_saved_meter_safe,
)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def assert_money_saved_safe(value: Any) -> None:
    """Fail-closed privacy gate (same recursive contract as feedback reports)."""
    assert_money_saved_meter_safe(value)


class IncompatibleExportError(ValueError):
    """Raised when a tier input is not a compatible Money Saved export."""


def _content_hash(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _privacy() -> dict[str, bool]:
    return {
        "local_only": True,
        "upload": False,
        "hosted_telemetry": False,
        "raw_prompts_included": False,
        "raw_task_text_included": False,
        "skill_bodies_included": False,
        "local_absolute_paths_included": False,
        "tokens_keys_secrets_included": False,
        "customer_names_included": False,
        "private_repo_paths_included": False,
        "raw_mcp_payloads_included": False,
        "machine_id_included": False,
        "install_id_included": False,
        "account_id_included": False,
        "telemetry": False,
        "analytics": False,
    }


def _dollars_disabled() -> dict[str, Any]:
    return {
        "enabled": False,
        "configured_locally": False,
        "reason": "disabled_by_default_no_local_price_config",
        "claim": "dollars are disabled by default; tokens are estimates and never billing math",
    }


# --- Team tier (O064-MSM-TEAM-IMPL): local rollup of Registered exports ---------

MSM_TEAM_ROLLUP_SCHEMA_VERSION = "money-saved-team-rollup-v1"


def _measured_value(block: Any) -> int | None:
    """Return the int value of a measured/estimated sub-block iff it is available."""
    if not isinstance(block, dict) or not block.get("available"):
        return None
    value = block.get("value")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def load_registered_export(path: Path) -> dict[str, Any]:
    """Load + validate one Registered Money Saved export (local file only)."""
    path = Path(path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncompatibleExportError(f"{path.name}: cannot read JSON ({exc.__class__.__name__}).") from exc
    if not isinstance(data, dict):
        raise IncompatibleExportError(f"{path.name}: export is not a JSON object.")
    if data.get("schema_version") != REGISTERED_EXPORT_SCHEMA_VERSION:
        raise IncompatibleExportError(
            f"{path.name}: incompatible schema_version "
            f"{data.get('schema_version')!r} (expected {REGISTERED_EXPORT_SCHEMA_VERSION!r})."
        )
    if data.get("export_type") != "money_saved_registered_export":
        raise IncompatibleExportError(
            f"{path.name}: not a Money Saved registered export (export_type={data.get('export_type')!r})."
        )
    try:
        assert_money_saved_safe(data)  # unsafe export is rejected before aggregation
    except RuntimeError as exc:
        raise IncompatibleExportError(f"{path.name}: unsafe export rejected ({exc}).") from exc
    return data


def _member_from_export(alias: str, data: dict[str, Any]) -> dict[str, Any]:
    body = data.get("body", {}) if isinstance(data.get("body"), dict) else {}
    window = body.get("window", {}) if isinstance(body.get("window"), dict) else {}
    measured = body.get("measured_bytes", {}) if isinstance(body.get("measured_bytes"), dict) else {}
    estimates = body.get("estimates", {}) if isinstance(body.get("estimates"), dict) else {}

    window_calls = window.get("window_call_count")
    window_calls = int(window_calls) if isinstance(window_calls, int) and not isinstance(window_calls, bool) else 0
    context_bytes = _measured_value(measured.get("context_bytes_avoided"))
    tokens_block = estimates.get("estimated_tokens_avoided") if isinstance(estimates.get("estimated_tokens_avoided"), dict) else {}
    est_tokens = _measured_value(tokens_block)
    method = tokens_block.get("method") if est_tokens is not None else None

    return {
        "alias": alias,
        # exact counts
        "window_call_count": window_calls,
        "is_complete_window": bool(window.get("is_complete_window", False)),
        # measured bytes (None when no local artifact exposed sizes)
        "measured_context_bytes_avoided": context_bytes,
        "measured_bytes_available": context_bytes is not None,
        # token estimate (method preserved)
        "estimated_tokens_avoided": est_tokens,
        "estimated_tokens_available": est_tokens is not None,
        "estimated_tokens_method": method,
    }


def build_money_saved_team_rollup(
    inputs: list[Path],
    *,
    aliases: list[str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Team-tier local rollup over multiple Registered Money Saved exports
    (O064-MSM-TEAM-IMPL).

    Inputs are local files gathered out of band; there is NO network fetch. Member
    aliases are local labels (operator-supplied or the input file stem) — never OS
    usernames or emails. Duplicate inputs are detected and counted once; an input
    with an incompatible schema or unsafe content is rejected via
    ``IncompatibleExportError``. Exact gateway-call counts and measured bytes are
    aggregated as facts; token *estimates* are aggregated with the estimation
    method preserved and never presented as exact. Dollars stay disabled by
    default. Fail-closed.
    """
    members: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    methods: set[str] = set()
    for index, raw in enumerate(inputs):
        path = Path(raw).expanduser()
        data = load_registered_export(path)
        alias = aliases[index] if aliases and index < len(aliases) and aliases[index] else path.stem
        digest = _content_hash(data)
        if digest in seen:
            duplicates.append({"alias": alias, "duplicate_of_alias": seen[digest]})
            continue
        seen[digest] = alias
        member = _member_from_export(alias, data)
        if member["estimated_tokens_method"]:
            methods.add(str(member["estimated_tokens_method"]))
        members.append(member)

    members_with_measured = [m for m in members if m["measured_bytes_available"]]
    members_with_estimate = [m for m in members if m["estimated_tokens_available"]]

    rollup: dict[str, Any] = {
        "schema_version": MSM_TEAM_ROLLUP_SCHEMA_VERSION,
        "report_type": "money_saved_team_rollup",
        "tier": "team",
        "export_profile": "team_local_rollup",
        "generated_at": generated_at or now_iso(),
        "source": "registered_money_saved_exports",
        "unlimited_skills_version": __version__,
        "member_count": len(members),
        "members": members,
        "exact_counts": {
            "team_window_call_count": sum(m["window_call_count"] for m in members),
            "complete_window_member_count": sum(1 for m in members if m["is_complete_window"]),
            "explanation": "Gateway-call counts are exact facts straight from each member's local meter.",
        },
        "measured_bytes": {
            "team_context_bytes_avoided": sum(m["measured_context_bytes_avoided"] for m in members_with_measured),
            "members_with_measured_bytes": len(members_with_measured),
            "members_without_measured_bytes": len(members) - len(members_with_measured),
            "explanation": "Measured bytes are summed only over members whose local artifacts exposed sizes.",
        },
        "estimates": {
            "team_estimated_tokens_avoided": sum(m["estimated_tokens_avoided"] for m in members_with_estimate),
            "members_with_estimated_tokens": len(members_with_estimate),
            "estimation_methods": sorted(methods),
            "measurement_kind": "estimated",
            "explanation": "Token totals are estimates (method preserved), never exact and never billing math.",
        },
        "dollars": _dollars_disabled(),
        "duplicate_inputs": duplicates,
        "privacy": {
            **_privacy(),
            "aliases_are_local_labels": True,
            "os_usernames_or_emails_included": False,
        },
        "claim_boundary": {
            "allowed_claims": [
                "Aggregates locally-gathered Registered Money Saved exports into a team view.",
                "All inputs are local files; nothing is fetched over a network.",
                "Bytes are measured when available; tokens are estimates; dollars are disabled by default.",
            ],
            "forbidden_claims": [
                "exact tokens saved",
                "exact money saved",
                "bill reduction guaranteed",
                "hosted team dashboard",
                "live team sync",
                "telemetry-backed team savings",
            ],
        },
        "delivery": {
            "produced_locally": True,
            "stays_local": True,
            "network_fetch": False,
            "hosted_sync": False,
            "upload": False,
            "dashboard": False,
            "note": "Inputs are gathered out of band; this rollup never fetches over a network.",
        },
    }
    assert_money_saved_safe(rollup)
    return rollup


def money_saved_team_rollup_json(rollup: dict[str, Any]) -> str:
    assert_money_saved_safe(rollup)
    return json.dumps(rollup, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
