from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VALID_FIXTURE = ROOT / "fixtures" / "learning-loop" / "feedback-signals-valid.jsonl"
INVALID_FIXTURE = ROOT / "fixtures" / "learning-loop" / "feedback-signals-invalid.jsonl"
SCHEMA = ROOT / "schemas" / "learning-feedback-signal.schema.json"

OUTCOMES = {"suggested", "viewed", "used", "accepted", "rejected", "missed", "wrong"}
SOURCES = {"event", "feedback"}
EVENT_OUTCOMES = {"suggested", "viewed", "used"}
FEEDBACK_OUTCOMES = {"accepted", "rejected", "missed", "wrong"}
HASH_RE = re.compile(r"^[a-f0-9]{12}$")
SKILL_LABEL_RE = re.compile(r"^skill-[a-f0-9]{12}$")
FORBIDDEN_FIELDS = {
    "prompt",
    "raw_prompt",
    "query",
    "raw_query",
    "notes",
    "raw_notes",
    "path",
    "debug_path",
    "local_path",
    "token",
    "key",
    "secret",
    "skill_body",
}
FORBIDDEN_TEXT_RE = [
    re.compile(r"[A-Za-z]:\\[^\s\"']+", re.IGNORECASE),
    re.compile(r"/(?:Users|home|private|tmp|var|etc)/[^\s\"']+", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|glpat|xoxb|uls)_[A-Za-z0-9_\-]{8,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(private customer|customer incident|raw customer|operator secret|prompt secret)\b", re.IGNORECASE),
]
PRIVACY_FLAGS = {
    "prompts_included",
    "raw_queries_included",
    "raw_notes_included",
    "local_paths_included",
    "tokens_included",
    "keys_included",
    "skill_bodies_included",
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _validate_signal(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "schema_version",
        "source",
        "outcome",
        "skill_label",
        "task_summary_hash",
        "query_summary_hash",
        "session_correlation_id",
        "signal_count",
        "local_only",
        "privacy",
    }
    extras = set(row) - allowed
    if extras:
        errors.append(f"unexpected fields: {sorted(extras)}")
    if row.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    source = row.get("source")
    outcome = row.get("outcome")
    if source not in SOURCES:
        errors.append("source must be event or feedback")
    if outcome not in OUTCOMES:
        errors.append("outcome is not one of the seven local Learning Loop outcomes")
    if source == "event" and outcome not in EVENT_OUTCOMES:
        errors.append("event source must use suggested/viewed/used outcome")
    if source == "feedback" and outcome not in FEEDBACK_OUTCOMES:
        errors.append("feedback source must use accepted/rejected/missed/wrong outcome")
    if not SKILL_LABEL_RE.fullmatch(str(row.get("skill_label") or "")):
        errors.append("skill_label must be a redacted skill-<12 hex> label")
    for key in ("task_summary_hash", "query_summary_hash", "session_correlation_id"):
        if key in row and not HASH_RE.fullmatch(str(row.get(key) or "")):
            errors.append(f"{key} must be 12 hex chars")
    if row.get("local_only") is not True:
        errors.append("local_only must be true")
    privacy = row.get("privacy")
    if not isinstance(privacy, dict):
        errors.append("privacy must be an object")
    else:
        missing = PRIVACY_FLAGS - set(privacy)
        extras = set(privacy) - PRIVACY_FLAGS
        if missing:
            errors.append(f"privacy missing: {sorted(missing)}")
        if extras:
            errors.append(f"privacy has unexpected fields: {sorted(extras)}")
        for key in PRIVACY_FLAGS:
            if privacy.get(key) is not False:
                errors.append(f"privacy.{key} must be false")
    if FORBIDDEN_FIELDS & set(row):
        errors.append(f"forbidden raw fields present: {sorted(FORBIDDEN_FIELDS & set(row))}")
    text = json.dumps(row, ensure_ascii=False, sort_keys=True)
    for pattern in FORBIDDEN_TEXT_RE:
        if pattern.search(text):
            errors.append("privacy-unsafe text present")
            break
    return errors


def main() -> int:
    json.loads(SCHEMA.read_text(encoding="utf-8"))
    valid_rows = _load_jsonl(VALID_FIXTURE)
    invalid_rows = _load_jsonl(INVALID_FIXTURE)

    valid_errors = [(idx, _validate_signal(row)) for idx, row in enumerate(valid_rows, start=1)]
    valid_errors = [(idx, errors) for idx, errors in valid_errors if errors]
    invalid_passes = [idx for idx, row in enumerate(invalid_rows, start=1) if not _validate_signal(row)]

    payload = {
        "schema_version": 1,
        "report_type": "learning_feedback_signal_contract",
        "valid_fixture": str(VALID_FIXTURE.relative_to(ROOT)).replace("\\", "/"),
        "invalid_fixture": str(INVALID_FIXTURE.relative_to(ROOT)).replace("\\", "/"),
        "valid_rows": len(valid_rows),
        "invalid_rows": len(invalid_rows),
        "valid_errors": valid_errors,
        "invalid_rows_that_passed": invalid_passes,
        "ok": not valid_errors and not invalid_passes,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
