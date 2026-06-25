"""Backfill Money Saved compaction events from local Codex session logs.

This is intentionally local-only and bounded: it scans JSONL session files for
Codex's reliable ``event_msg``/``context_compacted`` marker, reports what it
would recover, and only writes synthetic ``compaction`` events when the operator
passes ``--apply``. Some Codex logs also contain a paired ``type=compacted`` row;
that row is not counted because it describes the same compaction and would
double-count money events.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .mcp_savings import build_mcp_savings, gateway_is_configured
from .model_detect import bind_model
from .money_events import build_event, load_summary, record_event
from .skills_savings import build_skills_savings

BACKFILL_SCHEMA_VERSION = "money-saved-codex-log-backfill-v1"
DEDUP_SCHEMA_VERSION = "money-saved-codex-log-backfill-dedupe-v1"
DEDUP_FILE = "codex-log-backfill-dedupe.json"


def _parse_since(value: str, *, now: datetime | None = None) -> datetime | None:
    value = str(value or "all").strip().lower()
    if value in {"", "all"}:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        if value.endswith("h"):
            return now - timedelta(hours=float(value[:-1]))
        if value.endswith("d"):
            return now - timedelta(days=float(value[:-1]))
    except ValueError:
        return None
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _jsonl_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    for pattern in ("*.jsonl", "*.json"):
        yield from sorted(root.rglob(pattern))


def _is_compaction_marker(row: dict[str, Any]) -> bool:
    if row.get("type") == "event_msg":
        payload = row.get("payload")
        return isinstance(payload, dict) and payload.get("type") == "context_compacted"
    return False


def _row_time(row: dict[str, Any], file_time: datetime | None = None) -> datetime | None:
    for key in ("timestamp", "created_at", "time"):
        parsed = _parse_timestamp(row.get(key))
        if parsed is not None:
            return parsed
    payload = row.get("payload")
    if isinstance(payload, dict):
        for key in ("timestamp", "created_at", "time"):
            parsed = _parse_timestamp(payload.get(key))
            if parsed is not None:
                return parsed
    return file_time


def _marker_key(path: Path, line_no: int, timestamp: str) -> str:
    raw = f"{path.as_posix()}:{line_no}:{timestamp}".encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def _load_dedupe(directory: Path) -> dict[str, Any]:
    path = directory / DEDUP_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": DEDUP_SCHEMA_VERSION, "keys": {}}
    if not isinstance(data, dict) or data.get("schema_version") != DEDUP_SCHEMA_VERSION:
        return {"schema_version": DEDUP_SCHEMA_VERSION, "keys": {}}
    if not isinstance(data.get("keys"), dict):
        data["keys"] = {}
    return data


def _save_dedupe(directory: Path, data: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / DEDUP_FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _total_events(summary: dict[str, Any]) -> int:
    return sum(int(bucket.get("event_count", 0)) for bucket in (summary.get("buckets") or {}).values())


def _iter_markers(sessions_root: Path, *, since_at: datetime | None) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for path in _jsonl_files(sessions_root):
        try:
            file_time = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or not _is_compaction_marker(row):
                continue
            when = _row_time(row, file_time)
            if since_at is not None and when is not None and when < since_at:
                continue
            iso = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
            key = _marker_key(path, idx, iso)
            markers.append({
                "key": key,
                "file": str(path),
                "line": idx,
                "generated_at": iso,
                "marker_type": str(row.get("type") or ""),
            })
    return markers


def backfill_codex_logs(
    *,
    sessions_root: Path,
    event_directory: Path,
    library_root: Path,
    since: str = "all",
    apply: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    since_at = _parse_since(since)
    markers = _iter_markers(sessions_root, since_at=since_at)
    dedupe = _load_dedupe(event_directory)
    known = dedupe["keys"]
    new_markers = [marker for marker in markers if marker["key"] not in known]

    report: dict[str, Any] = {
        "schema_version": BACKFILL_SCHEMA_VERSION,
        "ok": True,
        "mode": "apply" if apply else "dry_run",
        "sessions_root": str(sessions_root),
        "money_saved_dir": str(event_directory),
        "since": since,
        "markers_found": len(markers),
        "already_recorded": len(markers) - len(new_markers),
        "eligible_new_markers": len(new_markers),
        "recorded": 0,
        "skipped_pre_genesis": 0,
        "event_types": {"compaction": len(new_markers)},
        "dedupe_file": str(event_directory / DEDUP_FILE),
    }
    if not apply or not new_markers:
        return report

    binding = bind_model(model, agent="codex")
    if not binding.available or binding.price is None:
        report.update({"ok": False, "error": "model_binding_missing", "agent": binding.agent})
        return report
    price = binding.price
    skills = build_skills_savings(provider=price.provider, model_api_id=None, root=library_root)
    mcp = {"baseline_tokens": 0, "actual_gateway_tokens": 0}
    if gateway_is_configured():
        mcp_report = build_mcp_savings(provider=price.provider)
        mcp = {
            "baseline_tokens": int(mcp_report["baseline_tokens"]),
            "actual_gateway_tokens": int(mcp_report["actual_gateway_tokens"]),
        }

    recorded = 0
    skipped_pre_genesis = 0
    for marker in new_markers:
        before = _total_events(load_summary(event_directory))
        event = build_event(
            agent="codex",
            event_type="compaction",
            provider=price.provider,
            model=price.model,
            model_source=binding.source,
            currency=price.currency,
            price_source_date=price.source_date,
            token_counter_method=skills["token_counter"]["method"],
            skills={
                "visible_skill_count": skills["baseline_skill_count"],
                "baseline_tokens": skills["baseline_tokens"],
                "actual_router_tokens": skills["actual_router_tokens"],
            },
            mcp=mcp,
            event_id=f"codex-log-{marker['key'][:24]}",
            generated_at=marker["generated_at"],
        )
        summary = record_event(event, event_directory)
        after = _total_events(summary)
        if after > before:
            recorded += 1
            known[marker["key"]] = {
                "event_id": event["event_id"],
                "generated_at": marker["generated_at"],
                "source_sha256": marker["key"],
            }
        else:
            skipped_pre_genesis += 1
    dedupe["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save_dedupe(event_directory, dedupe)
    report["recorded"] = recorded
    report["skipped_pre_genesis"] = skipped_pre_genesis
    report["event_types"] = {"compaction": recorded}
    return report
