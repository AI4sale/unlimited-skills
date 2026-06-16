"""Learning Loop tier surfaces (O063 tier ladder).

Privacy-safe, local-only exports/rollups over the Learning Loop state — feedback
verdict aggregates, improvement-candidate counts, and dry-run (non-mutating)
preview status. Built on ``learning_loop.learning_doctor()`` which already stores
only counts/verdict codes and skill NAMES, never query/task text. Read-only: this
tier never mutates skills.

Registered tier (O063-TIER-REG-IMPL): a single schema-versioned local export the
user can run to prove the Learning Loop is collecting feedback and producing
improvement candidates, all locally. Produced locally, stays local.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import __version__
from .feedback import assert_feedback_report_safe

LEARNING_EXPORT_SCHEMA_VERSION = "learning-export-v1"

ALLOWED_CLAIMS = [
    "Unlimited Skills reports, locally, how much feedback the Learning Loop has and how many improvement candidates it produced.",
    "Counts are computed on your own machine; nothing is uploaded and no skill is mutated.",
]

FORBIDDEN_CLAIMS = [
    "automatic skill improvement",
    "skills mutated automatically",
    "hosted learning analytics",
    "guaranteed quality improvement",
    "telemetry-backed learning",
]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def assert_learning_safe(value: Any) -> None:
    """Fail-closed privacy gate (same recursive contract as feedback reports)."""
    assert_feedback_report_safe(value)


def _privacy() -> dict[str, bool]:
    return {
        "local_only": True,
        "upload": False,
        "hosted_telemetry": False,
        "raw_prompts_included": False,
        "raw_queries_included": False,
        "notes_included": False,
        "skill_bodies_included": False,
        "local_absolute_paths_included": False,
        "tokens_keys_secrets_included": False,
        "machine_id_included": False,
        "install_id_included": False,
        "telemetry": False,
        "analytics": False,
    }


def build_learning_export(root: Path, *, generated_at: str | None = None) -> dict[str, Any]:
    """Registered-tier local Learning Loop export (O063-TIER-REG-IMPL).

    Read-only and fail-closed: the whole export passes ``assert_learning_safe``
    before it is returned/serialized, and no skill is mutated.
    """
    from .learning_loop import learning_doctor

    root = Path(root).expanduser()
    doctor = learning_doctor(root)

    export: dict[str, Any] = {
        "schema_version": LEARNING_EXPORT_SCHEMA_VERSION,
        "report_type": "learning_export",
        "tier": "registered",
        "export_profile": "registered_local",
        "generated_at": generated_at or now_iso(),
        "source": "learning_loop",
        "unlimited_skills_version": __version__,
        "feedback": {
            "feedback_count": int(doctor.get("feedback_count", 0) or 0),
            "event_count": int(doctor.get("event_count", 0) or 0),
            # outcome aggregates: missed / wrong / accepted / rejected / ... (counts only)
            "outcome_counts": dict(doctor.get("feedback_outcomes", {}) or {}),
        },
        "candidates": {
            "candidate_count": int(doctor.get("candidate_count", 0) or 0),
            "candidate_ids": list(doctor.get("candidate_ids", []) or []),
        },
        "dry_run": {
            "mutation_supported": False,
            "dry_run_only": True,
            "note": "apply-candidate is dry-run only; this export never mutates skills.",
        },
        "readiness": {
            "learning_dir_present": bool(doctor.get("learning_dir_present", False)),
            "feedback_log_present": bool(doctor.get("feedback_log_present", False)),
            "has_feedback": int(doctor.get("feedback_count", 0) or 0) > 0,
        },
        "privacy": _privacy(),
        "claim_boundary": {
            "allowed_claims": ALLOWED_CLAIMS,
            "forbidden_claims": FORBIDDEN_CLAIMS,
        },
        "delivery": {
            "produced_locally": True,
            "stays_local": True,
            "upload": False,
            "sync": False,
            "hosted_submit": False,
            "submit_verb_present": False,
            "note": "Produced locally and stays local; no upload, sync, or hosted submit in this tier.",
        },
    }
    assert_learning_safe(export)
    return export


def learning_export_json(export: dict[str, Any]) -> str:
    assert_learning_safe(export)
    return json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# --- Team tier (O063-TIER-TEAM-IMPL): local rollup of learning exports ----------

LEARNING_TEAM_ROLLUP_SCHEMA_VERSION = "learning-team-rollup-v1"


class IncompatibleExportError(ValueError):
    """Raised when a learning team-rollup input is not a compatible export."""


def _content_hash(data: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def load_learning_export(path: Path) -> dict[str, Any]:
    """Load + validate one Registered learning export (local file only)."""
    path = Path(path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncompatibleExportError(f"{path.name}: cannot read JSON ({exc.__class__.__name__}).") from exc
    if not isinstance(data, dict):
        raise IncompatibleExportError(f"{path.name}: export is not a JSON object.")
    if data.get("schema_version") != LEARNING_EXPORT_SCHEMA_VERSION:
        raise IncompatibleExportError(
            f"{path.name}: incompatible schema_version "
            f"{data.get('schema_version')!r} (expected {LEARNING_EXPORT_SCHEMA_VERSION!r})."
        )
    try:
        assert_learning_safe(data)
    except RuntimeError as exc:
        raise IncompatibleExportError(f"{path.name}: unsafe export rejected ({exc}).") from exc
    return data


def build_learning_team_rollup(
    inputs: list[Path],
    *,
    aliases: list[str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Team-tier local rollup over multiple Registered learning exports
    (O063-TIER-TEAM-IMPL).

    Inputs are local files gathered out of band; no network fetch. Member aliases
    are local labels (operator-supplied or the input file stem), never OS
    usernames/emails. Duplicate inputs are detected; incompatible-schema and
    unsafe inputs are rejected. Aggregates feedback/candidate counts and
    missed/wrong/rejected outcome patterns. Fail-closed.
    """
    members: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    outcome_totals: dict[str, int] = {}
    for index, raw in enumerate(inputs):
        path = Path(raw).expanduser()
        data = load_learning_export(path)
        alias = aliases[index] if aliases and index < len(aliases) and aliases[index] else path.stem
        digest = _content_hash(data)
        if digest in seen:
            duplicates.append({"alias": alias, "duplicate_of_alias": seen[digest]})
            continue
        seen[digest] = alias
        feedback = data.get("feedback", {}) if isinstance(data.get("feedback"), dict) else {}
        candidates = data.get("candidates", {}) if isinstance(data.get("candidates"), dict) else {}
        outcomes = feedback.get("outcome_counts", {}) if isinstance(feedback.get("outcome_counts"), dict) else {}
        for key, value in outcomes.items():
            if isinstance(value, int) and not isinstance(value, bool):
                outcome_totals[key] = outcome_totals.get(key, 0) + value
        members.append({
            "alias": alias,
            "feedback_count": int(feedback.get("feedback_count", 0) or 0),
            "candidate_count": int(candidates.get("candidate_count", 0) or 0),
            "outcome_counts": {k: int(v) for k, v in outcomes.items() if isinstance(v, int) and not isinstance(v, bool)},
        })

    rollup: dict[str, Any] = {
        "schema_version": LEARNING_TEAM_ROLLUP_SCHEMA_VERSION,
        "report_type": "learning_team_rollup",
        "tier": "team",
        "export_profile": "team_local_rollup",
        "generated_at": generated_at or now_iso(),
        "source": "registered_learning_exports",
        "unlimited_skills_version": __version__,
        "member_count": len(members),
        "team_total_feedback": sum(m["feedback_count"] for m in members),
        "team_total_candidates": sum(m["candidate_count"] for m in members),
        "aggregate_outcome_counts": dict(sorted(outcome_totals.items())),
        "members": members,
        "no_feedback_members": [m["alias"] for m in members if m["feedback_count"] == 0],
        "duplicate_inputs": duplicates,
        "privacy": {
            **_privacy(),
            "aliases_are_local_labels": True,
            "os_usernames_or_emails_included": False,
        },
        "claim_boundary": {
            "allowed_claims": [
                "Aggregates locally-gathered Registered learning exports into a team view.",
                "All inputs are local files; nothing is fetched over a network and no skill is mutated.",
            ],
            "forbidden_claims": [
                "hosted team dashboard",
                "live team sync",
                "automatic skill improvement",
            ],
        },
        "delivery": {
            "produced_locally": True,
            "stays_local": True,
            "network_fetch": False,
            "hosted_sync": False,
            "upload": False,
            "dashboard": False,
            "mutation": False,
            "note": "Inputs are gathered out of band; this rollup never fetches over a network or mutates skills.",
        },
    }
    assert_learning_safe(rollup)
    return rollup


def learning_team_rollup_json(rollup: dict[str, Any]) -> str:
    assert_learning_safe(rollup)
    return json.dumps(rollup, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
