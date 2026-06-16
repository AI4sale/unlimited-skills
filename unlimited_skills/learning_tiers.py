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
