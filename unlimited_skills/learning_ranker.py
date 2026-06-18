from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .search_core import (
    EVENT_LOG,
    LEARNING_BOOST_WEIGHT,
    LEARNING_DEMOTION_WEIGHT,
    LEARNING_MAX_ADJUSTMENT,
    expanded_query,
    skill_identity,
    task_summary_hash,
    token_summary_hash,
    tokens,
)

FEEDBACK_LOG = "feedback.jsonl"
SIMILARITY_THRESHOLD = 0.25
SIMILAR_QUERY_WEIGHT = 0.5
MANUAL_USE_WEIGHT = 6.0
QUERY_EVENT_TYPES = {"search", "suggest", "daemon_search"}
USE_EVENT_TYPES = {"skill_used", "daemon_skill_used"}


@dataclass(frozen=True)
class LearningSignal:
    skill: str
    event_type: str
    query_hash: str
    query_token_hashes: frozenset[str]
    adjustment: float


@dataclass(frozen=True)
class QueryFingerprint:
    query_hash: str
    query_token_hashes: frozenset[str]


def _read_jsonl(path: Path, *, limit: int = 1000) -> list[dict[str, Any]]:
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


def _token_hashes_from_row(row: dict[str, Any]) -> frozenset[str]:
    value = row.get("query_token_hashes")
    if not isinstance(value, list):
        return frozenset()
    clean = []
    for item in value[:40]:
        text = str(item or "").strip().lower()
        if text:
            clean.append(text)
    return frozenset(clean)


def _signal(
    *,
    skill: str,
    event_type: str,
    query_hash: str,
    query_token_hashes: frozenset[str],
    adjustment: float,
) -> LearningSignal | None:
    clean_skill = skill_identity(skill)
    if not clean_skill or not query_hash or not query_token_hashes or not adjustment:
        return None
    return LearningSignal(
        skill=clean_skill,
        event_type=event_type,
        query_hash=str(query_hash),
        query_token_hashes=query_token_hashes,
        adjustment=float(adjustment),
    )


def _feedback_signals(root: Path) -> list[LearningSignal]:
    rows = _read_jsonl(root / ".learning" / FEEDBACK_LOG)
    signals: list[LearningSignal] = []
    for row in rows:
        verdict = str(row.get("verdict") or row.get("outcome") or "").strip().lower()
        if verdict == "accepted":
            weight = LEARNING_BOOST_WEIGHT
        elif verdict in {"rejected", "wrong"}:
            weight = -LEARNING_DEMOTION_WEIGHT
        else:
            continue
        signal = _signal(
            skill=str(row.get("name") or row.get("skill_name") or ""),
            event_type=f"feedback_{verdict}",
            query_hash=str(row.get("query_summary_hash") or ""),
            query_token_hashes=_token_hashes_from_row(row),
            adjustment=weight,
        )
        if signal:
            signals.append(signal)
    return signals


def _event_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else {}


def _query_fingerprint(payload: dict[str, Any]) -> QueryFingerprint | None:
    query_hash = str(payload.get("query_summary_hash") or payload.get("task_summary_hash") or "")
    token_hashes = _token_hashes_from_row(payload)
    if not query_hash or not token_hashes:
        return None
    return QueryFingerprint(query_hash=query_hash, query_token_hashes=token_hashes)


def _manual_use_signals(root: Path) -> list[LearningSignal]:
    rows = _read_jsonl(root / ".learning" / EVENT_LOG)
    signals: list[LearningSignal] = []
    latest_query_by_session: dict[str, QueryFingerprint] = {}
    latest_query_global: QueryFingerprint | None = None
    for row in rows:
        event_type = str(row.get("type") or "")
        payload = _event_payload(row)
        if event_type in QUERY_EVENT_TYPES:
            fingerprint = _query_fingerprint(payload)
            if fingerprint:
                latest_query_global = fingerprint
                session = str(payload.get("session_correlation_id") or "")
                if session:
                    latest_query_by_session[session] = fingerprint
            continue
        if event_type not in USE_EVENT_TYPES:
            continue
        fingerprint = _query_fingerprint(payload)
        if fingerprint is None:
            session = str(payload.get("session_correlation_id") or "")
            fingerprint = latest_query_by_session.get(session) if session else None
            if fingerprint is None:
                fingerprint = latest_query_global
        if fingerprint is None:
            continue
        signal = _signal(
            skill=str(payload.get("name") or payload.get("skill_name") or ""),
            event_type=event_type,
            query_hash=fingerprint.query_hash,
            query_token_hashes=fingerprint.query_token_hashes,
            adjustment=MANUAL_USE_WEIGHT,
        )
        if signal:
            signals.append(signal)
    return signals


def read_learning_signals(root: Path) -> list[LearningSignal]:
    return _feedback_signals(root) + _manual_use_signals(root)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def query_tokens(query: str) -> frozenset[str]:
    return frozenset(token_summary_hash(token) for token in sorted(tokens(expanded_query(query))))


def learning_adjustments_for_query(root: Path, query: str) -> dict[str, float]:
    q_hash = task_summary_hash(query)
    q_tokens = query_tokens(query)
    adjustments: dict[str, float] = {}
    for signal in read_learning_signals(root):
        if signal.query_hash == q_hash:
            factor = 1.0
        else:
            similarity = _jaccard(q_tokens, signal.query_token_hashes)
            if similarity < SIMILARITY_THRESHOLD:
                continue
            factor = SIMILAR_QUERY_WEIGHT
        adjustments[signal.skill] = adjustments.get(signal.skill, 0.0) + signal.adjustment * factor
    return {
        key: max(-LEARNING_MAX_ADJUSTMENT, min(LEARNING_MAX_ADJUSTMENT, value))
        for key, value in adjustments.items()
        if value
    }


def learning_diagnostics(root: Path) -> dict[str, Any]:
    signals = read_learning_signals(root)
    accepted = [s for s in signals if s.event_type == "feedback_accepted"]
    rejected = [s for s in signals if s.event_type in {"feedback_rejected", "feedback_wrong"}]
    manual = [s for s in signals if s.event_type in USE_EVENT_TYPES]
    return {
        "learning_events_count": len(signals),
        "last_learning_event_type": signals[-1].event_type if signals else "",
        "accepted_events_count": len(accepted),
        "rejected_wrong_events_count": len(rejected),
        "manual_use_events_count": len(manual),
        "learning_boost_active": any(s.adjustment > 0 for s in signals),
        "learning_demotion_active": any(s.adjustment < 0 for s in signals),
        "last_query_fingerprint_present": bool(signals and signals[-1].query_hash),
        "privacy_ok": all(bool(s.query_hash) and bool(s.query_token_hashes) for s in signals),
    }
