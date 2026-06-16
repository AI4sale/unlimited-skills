"""Router-health tier surfaces (O062 tier debt).

Privacy-safe, local-only readiness/health views built on the router-invocation
counter (``<root>/.learning/router-metrics.json``). The underlying metrics already
store ONLY skill NAMES, numeric scores, and outcome/timing/retrieval-path codes —
never query/task text, never filesystem paths — so these surfaces are safe by
construction. Readiness is derived from locally-knowable index presence.

Registered tier (O062-TIER-REG-IMPL): a single schema-versioned local export the
user can run to prove the router is being invoked and is ready to retrieve skills,
including non-English fallback readiness. Produced locally, stays local.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import __version__
from .feedback import assert_feedback_report_safe

ROUTER_HEALTH_EXPORT_SCHEMA_VERSION = "router-health-export-v1"

ALLOWED_CLAIMS = [
    "Unlimited Skills reports, locally, whether the router is being invoked and is ready to retrieve skills.",
    "Counts and readiness are computed on your own machine; nothing is uploaded.",
]

FORBIDDEN_CLAIMS = [
    "guaranteed router accuracy",
    "hosted router analytics",
    "exact retrieval quality measured",
    "telemetry-backed router health",
]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def assert_router_health_safe(value: Any) -> None:
    """Fail-closed privacy gate (same recursive contract as feedback reports)."""
    assert_feedback_report_safe(value)


def _privacy() -> dict[str, bool]:
    return {
        "local_only": True,
        "upload": False,
        "hosted_telemetry": False,
        "raw_prompts_included": False,
        "raw_queries_included": False,
        "skill_bodies_included": False,
        "local_absolute_paths_included": False,
        "tokens_keys_secrets_included": False,
        "machine_id_included": False,
        "install_id_included": False,
        "telemetry": False,
        "analytics": False,
    }


def _readiness(root: Path) -> dict[str, Any]:
    from .doctor import _library_summary

    lib = _library_summary(root)
    vector_ready = bool(lib.get("vector_index_present"))
    lexical_ready = bool(lib.get("index_present"))
    if vector_ready:
        non_english = "multilingual_vector_ready"
    elif lexical_ready:
        non_english = "lexical_fallback_only"
    else:
        non_english = "unavailable_no_index"
    return {
        "lexical_index_present": lexical_ready,
        "vector_index_present": vector_ready,
        "non_english_fallback_readiness": non_english,
        "vector_daemon_readiness": {
            "vector_index_present": vector_ready,
            "daemon_locally_knowable": False,
            "daemon_status": "unknown_not_locally_determinable",
        },
    }


def _last_call_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    last = metrics.get("last_call") if isinstance(metrics.get("last_call"), dict) else {}
    # `path` in the metrics is a retrieval-path label (lexical/vector/hybrid),
    # NOT a filesystem path; `top_skill` is a skill NAME only. Both are safe.
    return {
        "present": bool(last),
        "iso": last.get("iso"),
        "retrieval_path": last.get("path"),
        "reason_code": last.get("reason_code"),
        "injected": bool(last.get("injected", False)),
        "elapsed_ms": last.get("elapsed_ms"),
        "delivery_tier": last.get("delivery_tier"),
        "top_skill": last.get("top_skill"),
        "top_score": last.get("top_score"),
    }


def _safe_by_day(by_day: Any) -> dict[str, int]:
    if not isinstance(by_day, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in by_day.items():
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        out[str(key)] = int(value)
    return out


def build_router_health_export(root: Path, *, generated_at: str | None = None) -> dict[str, Any]:
    """Registered-tier local router-health export (O062-TIER-REG-IMPL).

    Fail-closed: the whole export is run through ``assert_router_health_safe``
    before it is returned/serialized.
    """
    from .search_core import read_router_metrics

    root = Path(root).expanduser()
    metrics = read_router_metrics(root)
    total = int(metrics.get("total_invocations", 0) or 0)
    last_call = metrics.get("last_call") if isinstance(metrics.get("last_call"), dict) else {}

    export: dict[str, Any] = {
        "schema_version": ROUTER_HEALTH_EXPORT_SCHEMA_VERSION,
        "report_type": "router_health_export",
        "tier": "registered",
        "export_profile": "registered_local",
        "generated_at": generated_at or now_iso(),
        "source": "router_metrics",
        "unlimited_skills_version": __version__,
        "router": {
            "total_invocations": total,
            "router_invoked": total > 0,
            "first_call_iso": metrics.get("first_call_iso"),
            "updated_iso": metrics.get("updated_iso"),
        },
        "retrieval_path_aggregates": {
            "by_day_invocation_counts": _safe_by_day(metrics.get("by_day")),
            "last_call_retrieval_path": last_call.get("path"),
            "note": (
                "Per-day invocation counts are aggregated; a historical per-path "
                "breakdown is not stored, so only the last call's retrieval path is known."
            ),
        },
        "last_call_summary": _last_call_summary(metrics),
        "readiness": _readiness(root),
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
    assert_router_health_safe(export)
    return export


def router_health_export_json(export: dict[str, Any]) -> str:
    assert_router_health_safe(export)
    return json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
