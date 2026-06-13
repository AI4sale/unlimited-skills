"""Privacy-safe local ROI receipt generation.

The receipt is local-only and aggregate-only. It summarizes value signals from
the user's own machine without uploading data and without copying raw prompts,
queries, tasks, tool I/O, skill bodies, MCP schemas, configs, env, tokens,
paths, user identifiers, or tracking identifiers into output.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from . import __version__
from .feedback import FORBIDDEN_TEXT_RE, assert_feedback_report_safe
from .mcp.savings import LAB_FULL_DUMP_BYTES, LAB_GATEWAY_BYTES
from .search_core import EVENT_LOG, INDEX_NAME, IGNORED_SKILL_PATH_PARTS

RECEIPT_SCHEMA_VERSION = 1
RECEIPT_TYPE = "local_roi_receipt"
REQUIRED_NOTICE = (
    "This receipt is a local estimate from your own machine. It is not telemetry, "
    "not a benchmark guarantee, and not a paid ROI promise."
)

FORBIDDEN_EVENT_FIELDS = {
    "args",
    "argument",
    "arguments",
    "authorization",
    "command",
    "cookie",
    "device_private_key",
    "env",
    "environment",
    "input",
    "inputSchema",
    "license_token",
    "notes",
    "output",
    "path",
    "private_key",
    "prompt",
    "proof",
    "query",
    "raw",
    "result",
    "schema",
    "secret",
    "skill_body",
    "stderr",
    "stdout",
    "task",
    "token",
    "tool_input",
    "tool_output",
}

_SINCE_RE = re.compile(r"^(?P<count>\d+)(?P<unit>[hdw])$")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_since(value: str | None, *, now: float | None = None) -> tuple[str, float | None]:
    raw = (value or "").strip().lower()
    if not raw or raw == "all":
        return "all", None
    match = _SINCE_RE.match(raw)
    if not match:
        raise ValueError("--since must be all, <hours>h, <days>d, or <weeks>w")
    count = int(match.group("count"))
    unit = match.group("unit")
    seconds = count * {"h": 3600, "d": 86400, "w": 604800}[unit]
    return raw, (now if now is not None else time.time()) - seconds


def _read_jsonl(path: Path, *, limit: int = 2000) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _row_ts(row: dict[str, Any]) -> float | None:
    try:
        return float(row.get("ts"))
    except (TypeError, ValueError):
        return None


def _is_unsafe_legacy_row(row: dict[str, Any]) -> bool:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    for key in payload:
        if str(key).lower() in FORBIDDEN_EVENT_FIELDS:
            return True
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return any(pattern.search(serialized) for pattern in FORBIDDEN_TEXT_RE)


def _event_rows(root: Path, *, since_cutoff: float | None) -> tuple[list[dict[str, Any]], int]:
    rows = _read_jsonl(root / ".learning" / EVENT_LOG)
    safe_rows: list[dict[str, Any]] = []
    unsafe_count = 0
    for row in rows:
        ts = _row_ts(row)
        if since_cutoff is not None and (ts is None or ts < since_cutoff):
            continue
        if _is_unsafe_legacy_row(row):
            unsafe_count += 1
            continue
        safe_rows.append(row)
    return safe_rows, unsafe_count


def _library_skill_count(root: Path) -> dict[str, Any]:
    skill_files: list[Path] = []
    if root.exists():
        for skill_file in root.rglob("SKILL.md"):
            try:
                rel_parts = skill_file.relative_to(root).parts
            except ValueError:
                continue
            if any(part in IGNORED_SKILL_PATH_PARTS for part in rel_parts):
                continue
            skill_files.append(skill_file)
    collections = Counter(_collection_from_parts(skill_file.relative_to(root).parts) for skill_file in skill_files)
    return {
        "skill_count": len(skill_files),
        "collection_count": len(collections),
        "index_present": (root / INDEX_NAME).is_file(),
        "skill_names_included": False,
        "skill_bodies_included": False,
        "local_paths_included": False,
    }


def _collection_from_parts(parts: tuple[str, ...]) -> str:
    if len(parts) > 3 and parts[0] == "registry":
        return "registry/" + parts[1]
    if len(parts) > 1:
        return parts[0]
    return "local"


def _quickstart_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    quickstarts = [row for row in rows if row.get("type") == "quickstart"]
    if not quickstarts:
        return {"status": "unknown", "latest_run_present": False}
    payload = quickstarts[-1].get("payload") if isinstance(quickstarts[-1].get("payload"), dict) else {}
    steps = payload.get("steps") if isinstance(payload.get("steps"), dict) else {}
    return {
        "status": "completed" if steps else "seen",
        "latest_run_present": True,
        "step_count": len(steps),
        "had_search_result": bool(payload.get("first_search_hit_count")),
        "had_mcp_savings": bool(payload.get("mcp_savings_present") or payload.get("savings")),
        "raw_output_included": False,
    }


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 3)


def _routing_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    suggest_count = sum(1 for row in rows if row.get("type") == "suggest")
    view_count = sum(1 for row in rows if row.get("type") in {"view", "daemon_view"})
    use_count = sum(1 for row in rows if row.get("type") in {"skill_used", "daemon_skill_used"})
    return {
        "suggest_count": suggest_count,
        "view_count": view_count,
        "use_count": use_count,
        "suggest_to_view_rate": _rate(view_count, suggest_count),
        "suggest_to_use_rate": _rate(use_count, suggest_count),
        "raw_queries_included": False,
        "raw_tasks_included": False,
        "skill_bodies_included": False,
        "local_paths_included": False,
    }


def _safe_learning_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    score_buckets: Counter[str] = Counter()
    margin_buckets: Counter[str] = Counter()
    tier_counts: Counter[str] = Counter()
    injected = 0
    carded = 0
    sessions: dict[str, list[tuple[float, str]]] = {}
    for row in rows:
        event_type = str(row.get("type") or "")
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        ts = _row_ts(row) or 0.0
        if event_type == "suggest":
            if payload.get("score_bucket") is not None:
                score_buckets[str(payload.get("score_bucket"))] += 1
            if payload.get("margin_bucket") is not None:
                margin_buckets[str(payload.get("margin_bucket"))] += 1
            tier = payload.get("delivery_tier")
            if tier is not None:
                carded += 1
                tier_counts[str(tier)] += 1
            if payload.get("injected"):
                injected += 1
        sid = payload.get("session_correlation_id")
        if sid:
            sessions.setdefault(str(sid), []).append((ts, event_type))

    suggest_sessions = view_after = use_after = 0
    for events in sessions.values():
        events.sort(key=lambda item: item[0])
        suggests = [item for item in events if item[1] == "suggest"]
        if not suggests:
            continue
        suggest_sessions += 1
        first_ts = suggests[0][0]
        if any(ts >= first_ts and event_type in {"view", "daemon_view"} for ts, event_type in events):
            view_after += 1
        if any(ts >= first_ts and event_type in {"skill_used", "daemon_skill_used"} for ts, event_type in events):
            use_after += 1
    return {
        "available": True,
        "aggregate_only": True,
        "suggest_sessions": suggest_sessions,
        "post_suggest_view_rate": _rate(view_after, suggest_sessions),
        "post_suggest_use_rate": _rate(use_after, suggest_sessions),
        "injection_rate": _rate(injected, carded),
        "tier_counts": dict(sorted(tier_counts.items())),
        "score_bucket_counts": dict(sorted(score_buckets.items())),
        "margin_bucket_counts": dict(sorted(margin_buckets.items())),
        "raw_queries_included": False,
        "raw_tasks_included": False,
        "session_ids_included": False,
    }


def _latest_mcp_savings(rows: list[dict[str, Any]]) -> dict[str, Any]:
    savings = [row for row in rows if row.get("type") == "mcp_savings"]
    if not savings:
        return {
            "source": "benchmark_fallback",
            "status": "no_local_mcp_savings_snapshot",
            "measured_servers": 0,
            "skipped_servers": 0,
            "total_bytes": 0,
            "total_est_tokens": 0,
            "gateway_bytes": LAB_GATEWAY_BYTES,
            "gateway_est_tokens": LAB_GATEWAY_BYTES // 4,
            "savings_bytes": 0,
            "savings_pct": round((LAB_FULL_DUMP_BYTES - LAB_GATEWAY_BYTES) / LAB_FULL_DUMP_BYTES * 100.0, 1),
            "server_names_included": False,
            "schema_contents_included": False,
            "commands_included": False,
            "env_included": False,
        }
    payload = savings[-1].get("payload") if isinstance(savings[-1].get("payload"), dict) else {}
    servers = payload.get("servers") if isinstance(payload.get("servers"), list) else []
    return {
        "source": "local_mcp_savings",
        "status": "available",
        "measured_servers": sum(1 for row in servers if isinstance(row, dict) and row.get("status") == "ok"),
        "skipped_servers": sum(1 for row in servers if isinstance(row, dict) and row.get("status") != "ok"),
        "total_bytes": int(payload.get("total_bytes") or 0),
        "total_est_tokens": int(payload.get("total_est_tokens") or 0),
        "gateway_bytes": int(payload.get("gateway_bytes") or 0),
        "gateway_est_tokens": int(payload.get("gateway_bytes") or 0) // 4,
        "savings_bytes": int(payload.get("savings_bytes") or 0),
        "savings_pct": float(payload.get("savings_pct") or 0.0),
        "server_names_included": False,
        "schema_contents_included": False,
        "commands_included": False,
        "env_included": False,
    }


def build_roi_receipt(
    root: Path,
    *,
    since: str | None = None,
    generated_at: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    root = root.expanduser()
    window_requested, cutoff = parse_since(since, now=now)
    rows, unsafe_legacy_count = _event_rows(root, since_cutoff=cutoff)
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "report_type": RECEIPT_TYPE,
        "generated_at": generated_at or now_iso(),
        "window": {
            "requested": window_requested,
            "effective": window_requested,
            "unsafe_legacy_rows_skipped": unsafe_legacy_count,
            "legacy_status": "unavailable_legacy_logs" if unsafe_legacy_count else "safe_aggregates",
        },
        "unlimited_skills_version": __version__,
        "library": _library_skill_count(root),
        "quickstart_status": _quickstart_status(rows),
        "mcp_savings_summary": _latest_mcp_savings(rows),
        "skill_routing": _routing_summary(rows),
        "learning_summary_events": _safe_learning_metrics(rows),
        "feedback_prepare_status": {
            "available": True,
            "safe_invocation": "unlimited-skills feedback prepare",
            "paste_safe": True,
            "raw_feedback_included": False,
        },
        "privacy_notice": REQUIRED_NOTICE,
        "privacy": {
            "local_only": True,
            "telemetry": False,
            "upload": False,
            "analytics": False,
            "tracking_pixel": False,
            "prompts_included": False,
            "raw_queries_included": False,
            "raw_tasks_included": False,
            "tool_inputs_included": False,
            "tool_outputs_included": False,
            "skill_bodies_included": False,
            "mcp_schemas_included": False,
            "raw_logs_included": False,
            "raw_configs_included": False,
            "env_names_included": False,
            "env_values_included": False,
            "tokens_included": False,
            "local_paths_included": False,
            "user_identifiers_included": False,
            "tracking_identifiers_included": False,
        },
    }
    assert_roi_receipt_safe(receipt)
    return receipt


def assert_roi_receipt_safe(value: Any, *, path: str = "$") -> None:
    assert_feedback_report_safe(value, path=path)
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_EVENT_FIELDS:
                raise RuntimeError(f"ROI receipt contains forbidden field at {path}: {key}")
            if lowered.endswith("_included") and item is not False and lowered not in {"server_names_included"}:
                raise RuntimeError(f"ROI receipt privacy flag must be false at {path}.{key}")
            assert_roi_receipt_safe(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_roi_receipt_safe(item, path=f"{path}[{index}]")


def roi_receipt_json(receipt: dict[str, Any]) -> str:
    assert_roi_receipt_safe(receipt)
    return json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def format_roi_receipt_markdown(receipt: dict[str, Any]) -> str:
    assert_roi_receipt_safe(receipt)
    library = receipt["library"]
    quickstart = receipt["quickstart_status"]
    mcp = receipt["mcp_savings_summary"]
    routing = receipt["skill_routing"]
    learning = receipt["learning_summary_events"]
    lines = [
        "# Unlimited Skills local ROI receipt",
        "",
        f"Generated: {receipt['generated_at']}",
        f"Window: {receipt['window']['requested']}",
        "",
        f"- Version: {receipt['unlimited_skills_version']}",
        f"- Library: {library['skill_count']} indexed skills",
        f"- Quickstart: {quickstart['status']}",
        f"- MCP context savings: {mcp['status']} ({mcp['source']}), savings {mcp['savings_pct']}%",
        f"- Skill routing: {routing['suggest_count']} suggests, {routing['view_count']} views, {routing['use_count']} uses",
        f"- Suggest to view: {routing['suggest_to_view_rate']}",
        f"- Suggest to use: {routing['suggest_to_use_rate']}",
        f"- Learning summary: {learning['suggest_sessions']} attributed suggest sessions",
        f"- Feedback report: {'available' if receipt['feedback_prepare_status']['available'] else 'unavailable'}",
    ]
    if receipt["window"]["legacy_status"] == "unavailable_legacy_logs":
        lines.append(f"- Legacy logs: unavailable_legacy_logs ({receipt['window']['unsafe_legacy_rows_skipped']} unsafe rows skipped)")
    lines.extend(
        [
            "",
            REQUIRED_NOTICE,
            "",
            "Local-only: yes. Upload: no. Telemetry: no.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_receipt(path: Path, text: str) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
