"""Money-bearing tier ladder v2: Registered / Team / Business (O064-R2-06).

Builds on the Free meter v2 (``money-saved-meter-v2``). Unlike the v0.6.4 proxy
ladder (dollars disabled), every v2 export carries REAL money and the full
8-field money-BASIS so downstream tiers can decide what is safe to sum.

- **Registered** (`registered-export`): wraps one meter report in a
  schema-versioned envelope. Money is non-null; skills and MCP are kept separate;
  the basis travels with it. No raw prompts, skill bodies, or local paths; no
  install/machine/account id; produced locally and stays local.
- **Team** (`team-rollup`): groups members by the 8-field basis_key and sums money
  ONLY within a compatible group. Incompatible bases are shown as separate groups,
  never falsely summed. Exact duplicates are de-duped; unsafe/unavailable inputs
  are rejected. ``contains_assumptions`` is surfaced per group.
- **Business** (`admin-export`): a flat per-member table (CSV + matching JSON) with
  the exact §12 columns, including ``money_basis_compatible`` so an admin can see
  which rows actually combine.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .money_events import MONEY_MODEL_VERSION, basis_key

REGISTERED_EXPORT_V2_SCHEMA = "money-saved-registered-export-v2"
TEAM_ROLLUP_V2_SCHEMA = "money-saved-team-rollup-v2"
ADMIN_EXPORT_V2_SCHEMA = "money-saved-admin-export-v2"


class IncompatibleExportError(ValueError):
    """A loaded export is the wrong schema/type or carries no money."""


# --- basis + savings extraction from a meter-v2 report -------------------------

def _token_counter_method(meter: dict[str, Any]) -> str:
    savings = meter.get("savings") or {}
    for half in ("skills", "mcp"):
        counter = ((savings.get(half) or {}).get("token_counter")) or {}
        if counter.get("method"):
            return str(counter["method"])
    return ""


def meter_basis(meter: dict[str, Any]) -> dict[str, Any]:
    """The 8-field money-basis of a meter-v2 report (same shape as event_basis)."""
    binding = meter.get("model_binding") or {}
    pricing = meter.get("pricing") or {}
    return {
        "provider": str(binding.get("provider", "")),
        "model": str(binding.get("model", "")),
        "model_source": str(binding.get("source", "")),
        "currency": str(pricing.get("currency", "")),
        "price_class": str(pricing.get("price_class", "")),
        "price_source_date": str(pricing.get("source_date", "")),
        "token_counter_method": _token_counter_method(meter),
        "money_model_version": str(meter.get("money_model_version", MONEY_MODEL_VERSION)),
    }


def _member_summary(alias: str, meter: dict[str, Any]) -> dict[str, Any]:
    """Flat per-member figures used by Team + Business (no raw content)."""
    savings = meter.get("savings") or {}
    skills = savings.get("skills") or {}
    mcp = savings.get("mcp") or {}
    total = savings.get("total") or {}
    pricing = meter.get("pricing") or {}
    binding = meter.get("model_binding") or {}
    basis = meter_basis(meter)
    return {
        "alias": alias,
        "agent_class": str(binding.get("agent", "")),
        "provider": basis["provider"],
        "model": basis["model"],
        "model_source": basis["model_source"],
        "currency": basis["currency"],
        "price_class": basis["price_class"],
        "price_per_1m_input_tokens": pricing.get("price_per_1m_input_tokens"),
        "pricing_source": pricing.get("source", ""),
        "pricing_source_date": basis["price_source_date"],
        "token_counter_method": basis["token_counter_method"],
        "skills_tokens_saved": int(skills.get("total_tokens_saved", 0)),
        "mcp_tokens_saved": int(mcp.get("total_tokens_saved", 0)),
        "total_tokens_saved": int(total.get("tokens_saved", 0)),
        "skills_estimated_money_saved_usd": float(skills.get("estimated_money_saved_usd", 0.0)),
        "mcp_estimated_money_saved_usd": float(mcp.get("estimated_money_saved_usd", 0.0)),
        "total_estimated_money_saved_usd": float(total.get("estimated_money_saved_usd", 0.0)),
        "contains_assumption": str(binding.get("confidence", "")) == "assumed",
        "basis_key": basis_key(basis),
    }


# --- Registered ----------------------------------------------------------------

def build_registered_export_v2(meter: dict[str, Any], *, alias: str = "unknown", generated_at: str | None = None) -> dict[str, Any]:
    """Wrap a money-saved-meter-v2 report as a Registered export."""
    if meter.get("schema_version") != "money-saved-meter-v2" or not meter.get("available"):
        raise IncompatibleExportError("registered export requires an available money-saved-meter-v2 report")
    export: dict[str, Any] = {
        "schema_version": REGISTERED_EXPORT_V2_SCHEMA,
        "export_type": "money_saved_registered_export_v2",
        "tier": "registered",
        "alias": alias,
        "money_model_version": meter.get("money_model_version", MONEY_MODEL_VERSION),
        "model_binding": meter.get("model_binding"),
        "pricing": meter.get("pricing"),
        "basis": meter_basis(meter),
        "basis_key": basis_key(meter_basis(meter)),
        "events": meter.get("events"),
        "savings": meter.get("savings"),
        "member": _member_summary(alias, meter),
        "claim_boundary": meter.get("claim_boundary"),
        "token_count_privacy": meter.get("token_count_privacy"),
        "identity": {"install_id_included": False, "machine_id_included": False, "account_id_included": False},
        "delivery": {"produced_locally": True, "stays_local": True, "upload": False, "sync": False, "hosted_submit": False},
    }
    if generated_at is not None:
        export["generated_at"] = generated_at
    return export


def load_registered_export_v2(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != REGISTERED_EXPORT_V2_SCHEMA:
        raise IncompatibleExportError(f"not a {REGISTERED_EXPORT_V2_SCHEMA}: {path}")
    return data


def _content_hash(export: dict[str, Any]) -> str:
    stable = {k: v for k, v in export.items() if k != "generated_at"}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


# --- Team ----------------------------------------------------------------------

def build_team_rollup_v2(exports: list[dict[str, Any]], *, generated_at: str | None = None) -> dict[str, Any]:
    """Group members by basis and sum money only within a compatible group."""
    rejected: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    groups: dict[str, dict[str, Any]] = {}

    for export in exports:
        if not isinstance(export, dict) or export.get("schema_version") != REGISTERED_EXPORT_V2_SCHEMA:
            rejected.append({"reason": "wrong_schema_or_type", "schema_version": (export or {}).get("schema_version")})
            continue
        member = export.get("member") or {}
        if not member or export.get("savings") is None:
            rejected.append({"reason": "no_money_available", "alias": member.get("alias")})
            continue
        digest = _content_hash(export)
        if digest in seen_hashes:
            continue  # exact duplicate
        seen_hashes.add(digest)

        key = str(export.get("basis_key") or member.get("basis_key") or "")
        group = groups.get(key)
        if group is None:
            group = {
                "basis_key": key,
                "basis": export.get("basis"),
                "members": [],
                "member_count": 0,
                "skills_estimated_money_saved_usd": 0.0,
                "mcp_estimated_money_saved_usd": 0.0,
                "total_estimated_money_saved_usd": 0.0,
                "total_tokens_saved": 0,
                "contains_assumptions": False,
            }
            groups[key] = group
        group["members"].append(member)
        group["member_count"] += 1
        group["skills_estimated_money_saved_usd"] += member["skills_estimated_money_saved_usd"]
        group["mcp_estimated_money_saved_usd"] += member["mcp_estimated_money_saved_usd"]
        group["total_estimated_money_saved_usd"] += member["total_estimated_money_saved_usd"]
        group["total_tokens_saved"] += member["total_tokens_saved"]
        group["contains_assumptions"] = group["contains_assumptions"] or bool(member.get("contains_assumption"))

    group_list = sorted(groups.values(), key=lambda g: g["total_tokens_saved"], reverse=True)
    rollup: dict[str, Any] = {
        "schema_version": TEAM_ROLLUP_V2_SCHEMA,
        "report_type": "money_saved_team_rollup",
        "money_model_version": MONEY_MODEL_VERSION,
        "group_count": len(group_list),
        "single_compatible_basis": len(group_list) <= 1,
        "groups": group_list,
        "rejected": rejected,
        "contains_assumptions": any(g["contains_assumptions"] for g in group_list),
        "note": (
            "Money is summed only within a single compatible basis. Multiple groups "
            "are reported separately and are NOT summed across incompatible bases."
        ),
    }
    if generated_at is not None:
        rollup["generated_at"] = generated_at
    return rollup


# --- Business (admin) ----------------------------------------------------------

ADMIN_CSV_COLUMNS = (
    "alias", "team", "workspace", "agent_class", "project", "provider", "model",
    "currency", "price_class", "price_per_1m_input_tokens",
    "skills_tokens_saved", "mcp_tokens_saved", "total_tokens_saved",
    "skills_estimated_money_saved_usd", "mcp_estimated_money_saved_usd",
    "total_estimated_money_saved_usd", "pricing_source", "pricing_source_date",
    "token_counter_method", "money_basis_compatible",
)


def _label(labels: dict[str, Any] | None, alias: str, field: str) -> str:
    entry = (labels or {}).get(alias) if isinstance(labels, dict) else None
    if isinstance(entry, dict) and entry.get(field):
        return str(entry[field])
    return ""


def build_admin_export_v2(team_rollup: dict[str, Any], *, labels: dict[str, Any] | None = None, generated_at: str | None = None) -> dict[str, Any]:
    """Flatten a team rollup into the §12 per-member table (rows + totals)."""
    if team_rollup.get("schema_version") != TEAM_ROLLUP_V2_SCHEMA:
        raise IncompatibleExportError(f"admin export requires a {TEAM_ROLLUP_V2_SCHEMA}")
    groups = team_rollup.get("groups") or []
    # The largest group is the "primary" compatible basis; rows outside it cannot
    # be summed with the majority, so they are flagged money_basis_compatible=False.
    primary_key = groups[0]["basis_key"] if groups else ""
    rows: list[dict[str, Any]] = []
    for group in groups:
        compatible = group["basis_key"] == primary_key
        for member in group["members"]:
            alias = member["alias"]
            rows.append({
                "alias": alias,
                "team": _label(labels, alias, "team"),
                "workspace": _label(labels, alias, "workspace"),
                "agent_class": member.get("agent_class", "") or _label(labels, alias, "agent_class"),
                "project": _label(labels, alias, "project"),
                "provider": member["provider"],
                "model": member["model"],
                "currency": member["currency"],
                "price_class": member["price_class"],
                "price_per_1m_input_tokens": member["price_per_1m_input_tokens"],
                "skills_tokens_saved": member["skills_tokens_saved"],
                "mcp_tokens_saved": member["mcp_tokens_saved"],
                "total_tokens_saved": member["total_tokens_saved"],
                "skills_estimated_money_saved_usd": member["skills_estimated_money_saved_usd"],
                "mcp_estimated_money_saved_usd": member["mcp_estimated_money_saved_usd"],
                "total_estimated_money_saved_usd": member["total_estimated_money_saved_usd"],
                "pricing_source": member["pricing_source"],
                "pricing_source_date": member["pricing_source_date"],
                "token_counter_method": member["token_counter_method"],
                "money_basis_compatible": compatible,
            })
    export: dict[str, Any] = {
        "schema_version": ADMIN_EXPORT_V2_SCHEMA,
        "report_type": "money_saved_admin_export",
        "money_model_version": MONEY_MODEL_VERSION,
        "columns": list(ADMIN_CSV_COLUMNS),
        "row_count": len(rows),
        "rows": rows,
        "group_count": team_rollup.get("group_count", len(groups)),
        "single_compatible_basis": team_rollup.get("single_compatible_basis", len(groups) <= 1),
        "contains_assumptions": team_rollup.get("contains_assumptions", False),
    }
    if generated_at is not None:
        export["generated_at"] = generated_at
    return export


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if any(ch in text for ch in [",", '"', "\n"]):
        text = '"' + text.replace('"', '""') + '"'
    return text


def admin_export_v2_csv(export: dict[str, Any]) -> str:
    lines = [",".join(ADMIN_CSV_COLUMNS)]
    for row in export.get("rows", []):
        lines.append(",".join(_csv_cell(row.get(col)) for col in ADMIN_CSV_COLUMNS))
    return "\n".join(lines) + "\n"


def admin_export_v2_json(export: dict[str, Any]) -> str:
    return json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
