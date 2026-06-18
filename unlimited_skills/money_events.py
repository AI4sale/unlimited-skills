"""Event + cache accounting with COMPACT storage (O064-R2-04).

Standing context re-enters the model's input/cache on more than one occasion —
``session_start``, ``compaction``, ``context_rebuild``, ``agent_restart`` and a
manual reindex-reload — and every one of those re-loads the (collapsed) skill +
MCP descriptors. Each is a Money Saved *event*.

Owner directive (2026-06-17): "хранить компактно, не бесконечный лог." So we do
NOT keep an unbounded append-only events log. Storage is two bounded parts:

(a) ``summary.json`` (schema ``money-saved-summary-v1``) — a rolling aggregate
    bucketed by the money-BASIS tuple ``(agent, provider, model, model_source,
    currency, price_class, price_source_date, token_counter_method,
    money_model_version)``.
    Its size is O(distinct agent × model × price_class), still tiny compared to
    session count. The basis key is intentional: it IS the Team/Business "sum
    only when the basis matches" rule.

(b) ``recent-events.jsonl`` — only the newest ~200 ``money-saved-event-v1`` lines,
    truncated on every write. For ``events inspect`` / debugging only.

``record_event`` increments the matching basis bucket and appends to the capped
tail. Bounded forever.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .registration import unlimited_skills_home

EVENT_SCHEMA_VERSION = "money-saved-event-v1"
SUMMARY_SCHEMA_VERSION = "money-saved-summary-v1"
MONEY_MODEL_VERSION = "money-saved-v2"
RECENT_EVENTS_CAP = 200

# Standing context re-enters the cache on each of these.
EVENT_TYPES = (
    "session_start",
    "compaction",
    "context_rebuild",
    "agent_restart",
    "manual_reindex_reload",
)

# Cache price classes (mirror Anthropic input price classes).
PRICE_CLASS_BASE = "base_input"
PRICE_CLASS_CACHE_WRITE_5M = "cache_write_5m"
PRICE_CLASS_CACHE_WRITE_1H = "cache_write_1h"
PRICE_CLASS_CACHE_HIT_REFRESH = "cache_hit_refresh"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def default_price_class(event_type: str) -> str:
    """Default cache class for an event (runtime may override).

    First session has no warm cache → ``base_input``. Every other event re-writes
    the standing context to the cache → ``cache_write_5m`` (every compaction
    reloads the descriptors = a cache-write event).
    """
    return PRICE_CLASS_BASE if event_type == "session_start" else PRICE_CLASS_CACHE_WRITE_5M


def money_saved_dir(home: Path | None = None) -> Path:
    base = (home / ".unlimited-skills") if home is not None else unlimited_skills_home()
    return base / "money_saved"


def summary_path(directory: Path) -> Path:
    return directory / "summary.json"


def recent_events_path(directory: Path) -> Path:
    return directory / "recent-events.jsonl"


def _skills_saved(skills: dict[str, Any]) -> int:
    return max(0, int(skills.get("baseline_tokens", 0)) - int(skills.get("actual_router_tokens", 0)))


def _mcp_saved(mcp: dict[str, Any]) -> int:
    return max(0, int(mcp.get("baseline_tokens", 0)) - int(mcp.get("actual_gateway_tokens", 0)))


def build_event(
    *,
    agent: str,
    event_type: str,
    provider: str,
    model: str,
    model_source: str,
    currency: str,
    price_source_date: str,
    token_counter_method: str,
    skills: dict[str, Any],
    mcp: dict[str, Any],
    price_class: str | None = None,
    money_model_version: str = MONEY_MODEL_VERSION,
    event_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build one ``money-saved-event-v1`` record."""
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": event_id or uuid.uuid4().hex,
        "generated_at": generated_at or now_iso(),
        "agent": agent,
        "event_type": event_type,
        "money_model_version": money_model_version,
        "model": {"provider": provider, "model": model, "source": model_source},
        "cache": {
            "price_class": price_class or default_price_class(event_type),
            "source": "default_for_event_type" if price_class is None else "explicit",
        },
        "pricing": {"currency": currency, "price_source_date": price_source_date},
        "token_counter": {"method": token_counter_method},
        "skills": {
            "visible_skill_count": int(skills.get("visible_skill_count", skills.get("baseline_skill_count", 0))),
            "baseline_tokens": int(skills.get("baseline_tokens", 0)),
            "actual_router_tokens": int(skills.get("actual_router_tokens", 0)),
        },
        "mcp": {
            "baseline_tokens": int(mcp.get("baseline_tokens", 0)),
            "actual_gateway_tokens": int(mcp.get("actual_gateway_tokens", 0)),
        },
    }


def event_basis(event: dict[str, Any]) -> dict[str, Any]:
    """The 8-field money-basis of an event (the bucket identity)."""
    model = event.get("model") or {}
    cache = event.get("cache") or {}
    pricing = event.get("pricing") or {}
    counter = event.get("token_counter") or {}
    return {
        "agent": str(event.get("agent", "")),
        "provider": str(model.get("provider", "")),
        "model": str(model.get("model", "")),
        "model_source": str(model.get("source", "")),
        "currency": str(pricing.get("currency", "")),
        "price_class": str(cache.get("price_class", "")),
        "price_source_date": str(pricing.get("price_source_date", "")),
        "token_counter_method": str(counter.get("method", "")),
        "money_model_version": str(event.get("money_model_version", MONEY_MODEL_VERSION)),
    }


_BASIS_ORDER = (
    "agent", "provider", "model", "model_source", "currency",
    "price_class", "price_source_date", "token_counter_method", "money_model_version",
)


def basis_key(basis: dict[str, Any]) -> str:
    return "|".join(str(basis.get(field, "")) for field in _BASIS_ORDER)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def empty_summary() -> dict[str, Any]:
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "money_model_version": MONEY_MODEL_VERSION,
        "buckets": {},
    }


def load_summary(directory: Path | None = None, *, home: Path | None = None) -> dict[str, Any]:
    directory = directory or money_saved_dir(home)
    data = _read_json(summary_path(directory))
    if not data or data.get("schema_version") != SUMMARY_SCHEMA_VERSION:
        return empty_summary()
    if not isinstance(data.get("buckets"), dict):
        data["buckets"] = {}
    return data


def save_summary(summary: dict[str, Any], directory: Path | None = None, *, home: Path | None = None) -> None:
    directory = directory or money_saved_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    path = summary_path(directory)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_recent(event: dict[str, Any], directory: Path | None = None, *, cap: int = RECENT_EVENTS_CAP, home: Path | None = None) -> None:
    directory = directory or money_saved_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    path = recent_events_path(directory)
    lines: list[str] = []
    if path.is_file():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    lines.append(json.dumps(event, ensure_ascii=False, sort_keys=True))
    if len(lines) > cap:
        lines = lines[-cap:]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def record_event(event: dict[str, Any], directory: Path | None = None, *, home: Path | None = None) -> dict[str, Any]:
    """Fold ``event`` into the rolling summary bucket and append to the capped tail."""
    directory = directory or money_saved_dir(home)
    summary = load_summary(directory)
    basis = event_basis(event)
    key = basis_key(basis)
    bucket = summary["buckets"].get(key)
    skills_saved = _skills_saved(event.get("skills") or {})
    mcp_saved = _mcp_saved(event.get("mcp") or {})
    event_type = str(event.get("event_type", ""))
    generated_at = str(event.get("generated_at", "")) or now_iso()

    # NO BACKDATING (owner 2026-06-17): savings are only ever counted from the
    # moment the counter first observed an event. The first record sets the
    # genesis; anything dated earlier is refused — we have no evidence it
    # happened under our skill, so we never claim savings for a pre-counter past.
    genesis = summary.get("counter_genesis_at")
    if genesis is None:
        summary["counter_genesis_at"] = generated_at
    elif generated_at < genesis:
        return summary

    if bucket is None:
        bucket = {
            "basis": basis,
            "event_count": 0,
            "event_types": {},
            "skills_total_tokens_saved": 0,
            "mcp_total_tokens_saved": 0,
            "total_tokens_saved": 0,
            "first_event_at": generated_at,
            "last_event_at": generated_at,
        }
        summary["buckets"][key] = bucket

    bucket["event_count"] += 1
    bucket["event_types"][event_type] = bucket["event_types"].get(event_type, 0) + 1
    bucket["skills_total_tokens_saved"] += skills_saved
    bucket["mcp_total_tokens_saved"] += mcp_saved
    bucket["total_tokens_saved"] += skills_saved + mcp_saved
    bucket["last_event_at"] = generated_at
    if generated_at < bucket["first_event_at"]:
        bucket["first_event_at"] = generated_at

    save_summary(summary, directory)
    append_recent(event, directory)
    return summary


def read_recent(directory: Path | None = None, *, tail: int = RECENT_EVENTS_CAP, home: Path | None = None) -> list[dict[str, Any]]:
    directory = directory or money_saved_dir(home)
    path = recent_events_path(directory)
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-tail:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def events_inspect(directory: Path | None = None, *, tail: int = 50, home: Path | None = None) -> dict[str, Any]:
    """The ``money-saved events inspect`` payload: aggregate + capped tail."""
    directory = directory or money_saved_dir(home)
    summary = load_summary(directory)
    buckets = list(summary.get("buckets", {}).values())
    return {
        "schema_version": "money-saved-events-inspect-v1",
        "storage": "compact_summary_plus_capped_tail",
        "dir": str(directory),
        "recent_events_cap": RECENT_EVENTS_CAP,
        "bucket_count": len(buckets),
        "total_event_count": sum(int(b.get("event_count", 0)) for b in buckets),
        "buckets": buckets,
        "recent_events": read_recent(directory, tail=tail),
    }
