from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .search_core import EVENT_LOG, ROUTER_METRICS, read_router_metrics

FEEDBACK_LOG = "feedback.jsonl"
SUPPORTED_FEEDBACK_OUTCOMES = {"accepted", "rejected", "neutral", "missed", "wrong"}
ACTIONABLE_OUTCOMES = {"rejected", "missed", "wrong"}

FORBIDDEN_TEXT_RE = [
    re.compile(r"[A-Za-z]:\\[^\s\"']+", re.IGNORECASE),
    re.compile(r"/(?:Users|home|private|tmp|var|etc)/[^\s\"']+", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|glpat|xoxb|uls)_[A-Za-z0-9_\-]{8,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bAuthorization:\s*Bearer\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class LearningCandidate:
    candidate_id: str
    candidate_type: str
    title: str
    source: str
    skill_label: str
    signal_count: int
    confidence: str
    recommended_action: str
    dry_run_summary: str
    privacy: dict[str, bool]

    def to_json(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "title": self.title,
            "source": self.source,
            "skill_label": self.skill_label,
            "signal_count": self.signal_count,
            "confidence": self.confidence,
            "recommended_action": self.recommended_action,
            "dry_run_summary": self.dry_run_summary,
            "privacy": self.privacy,
        }


def read_jsonl(path: Path, *, limit: int = 1000) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines[-limit:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def feedback_rows(root: Path) -> list[dict[str, Any]]:
    return read_jsonl(root / ".learning" / FEEDBACK_LOG)


def event_rows(root: Path) -> list[dict[str, Any]]:
    return read_jsonl(root / ".learning" / EVENT_LOG)


def _outcome(row: dict[str, Any]) -> str:
    return str(row.get("outcome") or row.get("verdict") or "").strip().lower()


def _raw_skill_name(row: dict[str, Any]) -> str:
    name = str(row.get("name") or row.get("skill_name") or "").strip()
    return name if name else "unknown"


def _safe_skill_label(name: str) -> str:
    digest = hashlib.sha256(str(name or "unknown").encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"skill-{digest}"


def _safe_candidate_id(value: str) -> str:
    candidate_id = str(value or "").strip()
    if re.fullmatch(r"llc_[a-f0-9]{12}", candidate_id):
        return candidate_id
    return "invalid"


def _candidate_id(candidate_type: str, skill_name: str) -> str:
    raw = json.dumps(
        {"type": candidate_type, "skill": skill_name},
        ensure_ascii=False,
        sort_keys=True,
    )
    return "llc_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _privacy_flags() -> dict[str, bool]:
    return {
        "local_only": True,
        "dry_run_only": True,
        "prompts_included": False,
        "raw_queries_included": False,
        "raw_notes_included": False,
        "skill_bodies_included": False,
        "local_paths_included": False,
        "tokens_included": False,
        "keys_included": False,
    }


def _candidate_for(outcome: str, skill_name: str, signal_count: int) -> LearningCandidate:
    if outcome == "missed":
        candidate_type = "missed_skill"
        title = "Investigate missed skill invocation"
        action = "review router coverage and skill descriptions for the missed task class"
        summary = "Would inspect aggregate missed-skill signals and propose a routing or skill-description change."
    elif outcome == "wrong":
        candidate_type = "wrong_skill"
        title = "Investigate wrong skill suggestion"
        action = "review ranking terms and competing skill descriptions for this skill"
        summary = "Would inspect aggregate wrong-skill signals and propose a ranking or wording correction."
    else:
        candidate_type = "rejected_suggestion"
        title = "Investigate rejected skill suggestion"
        action = "review why the suggested skill was rejected before changing routing or skill text"
        summary = "Would inspect aggregate rejected-suggestion signals and propose a non-mutating fix plan."
    return LearningCandidate(
        candidate_id=_candidate_id(candidate_type, skill_name),
        candidate_type=candidate_type,
        title=title,
        source="local_feedback",
        skill_label=_safe_skill_label(skill_name),
        signal_count=signal_count,
        confidence="low" if signal_count == 1 else "medium",
        recommended_action=action,
        dry_run_summary=summary,
        privacy=_privacy_flags(),
    )


def build_improvement_candidates(root: Path) -> list[LearningCandidate]:
    grouped: dict[tuple[str, str], int] = {}
    for row in feedback_rows(root):
        outcome = _outcome(row)
        if outcome not in ACTIONABLE_OUTCOMES:
            continue
        key = (outcome, _raw_skill_name(row))
        grouped[key] = grouped.get(key, 0) + 1
    candidates = [_candidate_for(outcome, skill_name, count) for (outcome, skill_name), count in sorted(grouped.items())]
    return sorted(candidates, key=lambda item: (item.candidate_type, item.skill_label))


def learning_doctor(root: Path) -> dict[str, Any]:
    root = Path(root)
    learning_dir = root / ".learning"
    feedback = feedback_rows(root)
    events = event_rows(root)
    router_metrics = read_router_metrics(root)
    outcomes: dict[str, int] = {}
    for row in feedback:
        outcome = _outcome(row) or "unknown"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    candidates = build_improvement_candidates(root)
    return {
        "schema_version": 1,
        "status": "ok",
        "root_present": root.exists(),
        "learning_dir_present": learning_dir.is_dir(),
        "feedback_log_present": (learning_dir / FEEDBACK_LOG).is_file(),
        "event_log_present": (learning_dir / EVENT_LOG).is_file(),
        "router_metrics_present": (learning_dir / ROUTER_METRICS).is_file(),
        "feedback_count": len(feedback),
        "event_count": len(events),
        "feedback_outcomes": dict(sorted(outcomes.items())),
        "router_total_invocations": int(router_metrics.get("total_invocations") or 0),
        "candidate_count": len(candidates),
        "candidate_ids": [candidate.candidate_id for candidate in candidates],
        "privacy": _privacy_flags(),
        "message": "No learning feedback found yet." if not feedback and not events else "Learning state inspected.",
    }


def dry_run_candidate(root: Path, candidate_id: str) -> dict[str, Any]:
    candidates = build_improvement_candidates(root)
    match = next((candidate for candidate in candidates if candidate.candidate_id == candidate_id), None)
    if match is None:
        return {
            "schema_version": 1,
            "status": "not_found",
            "candidate_id": _safe_candidate_id(candidate_id),
            "written": False,
            "mutated_files": [],
            "message": "Candidate not found. Run `unlimited-skills improvement-candidates` to list current candidates.",
        }
    return {
        "schema_version": 1,
        "status": "dry_run",
        "candidate": match.to_json(),
        "written": False,
        "mutated_files": [],
        "message": "Dry run only: no skill files were modified.",
        "preview": {
            "would_review": [match.source],
            "would_change": [],
            "recommended_action": match.recommended_action,
            "summary": match.dry_run_summary,
        },
    }


def assert_privacy_safe(payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for pattern in FORBIDDEN_TEXT_RE:
        if pattern.search(text):
            raise ValueError("Learning Loop payload contains privacy-unsafe text")
