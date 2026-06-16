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


# --- Team tier (O062-TIER-TEAM-IMPL): local rollup of Registered exports --------

ROUTER_HEALTH_TEAM_ROLLUP_SCHEMA_VERSION = "router-health-team-rollup-v1"


class IncompatibleExportError(ValueError):
    """Raised when a team-rollup input is not a compatible Registered export."""


def _content_hash(data: dict[str, Any]) -> str:
    import hashlib

    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_registered_export(path: Path) -> dict[str, Any]:
    """Load + validate one Registered router-health export (local file only)."""
    path = Path(path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncompatibleExportError(f"{path.name}: cannot read JSON ({exc.__class__.__name__}).") from exc
    if not isinstance(data, dict):
        raise IncompatibleExportError(f"{path.name}: export is not a JSON object.")
    if data.get("schema_version") != ROUTER_HEALTH_EXPORT_SCHEMA_VERSION:
        raise IncompatibleExportError(
            f"{path.name}: incompatible schema_version "
            f"{data.get('schema_version')!r} (expected {ROUTER_HEALTH_EXPORT_SCHEMA_VERSION!r})."
        )
    try:
        assert_router_health_safe(data)  # unsafe export is rejected before aggregation
    except RuntimeError as exc:
        raise IncompatibleExportError(f"{path.name}: unsafe export rejected ({exc}).") from exc
    return data


def build_router_health_team_rollup(
    inputs: list[Path],
    *,
    aliases: list[str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Team-tier local rollup over multiple Registered exports (O062-TIER-TEAM-IMPL).

    Inputs are local files gathered out of band; there is NO network fetch. Member
    aliases are local labels (operator-supplied or the input file stem) — never OS
    usernames or emails. Duplicate inputs are detected and counted once; an input
    with an incompatible schema or unsafe content is rejected. Fail-closed.
    """
    members: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for index, raw in enumerate(inputs):
        path = Path(raw).expanduser()
        data = load_registered_export(path)
        alias = aliases[index] if aliases and index < len(aliases) and aliases[index] else path.stem
        digest = _content_hash(data)
        if digest in seen:
            duplicates.append({"alias": alias, "duplicate_of_alias": seen[digest]})
            continue
        seen[digest] = alias
        router = data.get("router", {}) if isinstance(data.get("router"), dict) else {}
        readiness = data.get("readiness", {}) if isinstance(data.get("readiness"), dict) else {}
        members.append({
            "alias": alias,
            "total_invocations": int(router.get("total_invocations", 0) or 0),
            "router_invoked": bool(router.get("router_invoked", False)),
            "non_english_fallback_readiness": readiness.get("non_english_fallback_readiness"),
            "vector_index_present": bool(readiness.get("vector_index_present", False)),
        })

    readiness_summary: dict[str, int] = {}
    for member in members:
        key = member["non_english_fallback_readiness"] or "unknown"
        readiness_summary[key] = readiness_summary.get(key, 0) + 1

    rollup: dict[str, Any] = {
        "schema_version": ROUTER_HEALTH_TEAM_ROLLUP_SCHEMA_VERSION,
        "report_type": "router_health_team_rollup",
        "tier": "team",
        "export_profile": "team_local_rollup",
        "generated_at": generated_at or now_iso(),
        "source": "registered_router_health_exports",
        "unlimited_skills_version": __version__,
        "member_count": len(members),
        "team_total_invocations": sum(m["total_invocations"] for m in members),
        "members": members,
        "non_english_readiness_summary": readiness_summary,
        "stale_or_no_router_call_members": [m["alias"] for m in members if not m["router_invoked"]],
        "duplicate_inputs": duplicates,
        "privacy": {
            **_privacy(),
            "aliases_are_local_labels": True,
            "os_usernames_or_emails_included": False,
        },
        "claim_boundary": {
            "allowed_claims": [
                "Aggregates locally-gathered Registered router-health exports into a team view.",
                "All inputs are local files; nothing is fetched over a network.",
            ],
            "forbidden_claims": [
                "hosted team dashboard",
                "live team sync",
                "telemetry-backed team analytics",
            ],
        },
        "delivery": {
            "produced_locally": True,
            "stays_local": True,
            "network_fetch": False,
            "hosted_sync": False,
            "upload": False,
            "dashboard": False,
            "note": "Inputs are gathered out of band; this rollup never fetches over a network.",
        },
    }
    assert_router_health_safe(rollup)
    return rollup


def router_health_team_rollup_json(rollup: dict[str, Any]) -> str:
    assert_router_health_safe(rollup)
    return json.dumps(rollup, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# --- Business tier (O062-TIER-BUSINESS-IMPL): admin CSV + JSON export -----------

ROUTER_HEALTH_ADMIN_EXPORT_SCHEMA_VERSION = "router-health-admin-export-v1"
_ADMIN_CSV_COLUMNS = [
    "alias",
    "team",
    "workspace",
    "agent_class",
    "total_invocations",
    "router_invoked",
    "non_english_fallback_readiness",
]
_UNLABELED = "unlabeled"


def load_team_rollup(path: Path) -> dict[str, Any]:
    """Load + validate one Team rollup (local file only)."""
    path = Path(path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IncompatibleExportError(f"{path.name}: cannot read JSON ({exc.__class__.__name__}).") from exc
    if not isinstance(data, dict):
        raise IncompatibleExportError(f"{path.name}: rollup is not a JSON object.")
    if data.get("schema_version") != ROUTER_HEALTH_TEAM_ROLLUP_SCHEMA_VERSION:
        raise IncompatibleExportError(
            f"{path.name}: incompatible schema_version "
            f"{data.get('schema_version')!r} (expected {ROUTER_HEALTH_TEAM_ROLLUP_SCHEMA_VERSION!r})."
        )
    try:
        assert_router_health_safe(data)
    except RuntimeError as exc:
        raise IncompatibleExportError(f"{path.name}: unsafe rollup rejected ({exc}).") from exc
    return data


def _label_for(labels: dict[str, Any] | None, alias: str, key: str) -> str:
    if isinstance(labels, dict):
        entry = labels.get(alias)
        if isinstance(entry, dict):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return _UNLABELED


def _group_counts(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, int]]:
    groups: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = groups.setdefault(row[key], {"members": 0, "total_invocations": 0, "stale_members": 0})
        bucket["members"] += 1
        bucket["total_invocations"] += int(row["total_invocations"])
        if not row["router_invoked"]:
            bucket["stale_members"] += 1
    return groups


def build_router_health_admin_export(
    rollup_path: Path,
    *,
    labels: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Business-tier admin export over a Team rollup (O062-TIER-BUSINESS-IMPL).

    Admin-supplied local labels (team/workspace/agent-class) group the members.
    Measured counts are kept separate from advisory status. Missing labels are
    handled safely (``unlabeled``). Fail-closed. Local file; no hosted dashboard,
    billing, provider account ids, or telemetry.
    """
    rollup = load_team_rollup(Path(rollup_path))
    members = rollup.get("members") if isinstance(rollup.get("members"), list) else []

    rows: list[dict[str, Any]] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        alias = str(member.get("alias") or _UNLABELED)
        rows.append({
            "alias": alias,
            "team": _label_for(labels, alias, "team"),
            "workspace": _label_for(labels, alias, "workspace"),
            "agent_class": _label_for(labels, alias, "agent_class"),
            # measured
            "total_invocations": int(member.get("total_invocations", 0) or 0),
            "router_invoked": bool(member.get("router_invoked", False)),
            # advisory
            "non_english_fallback_readiness": member.get("non_english_fallback_readiness"),
        })

    export: dict[str, Any] = {
        "schema_version": ROUTER_HEALTH_ADMIN_EXPORT_SCHEMA_VERSION,
        "report_type": "router_health_admin_export",
        "tier": "business",
        "export_profile": "business_local_admin",
        "generated_at": generated_at or now_iso(),
        "source": "router_health_team_rollup",
        "unlimited_skills_version": __version__,
        "csv_columns": list(_ADMIN_CSV_COLUMNS),
        "rows": rows,
        "measured": {
            "row_count": len(rows),
            "total_invocations": sum(r["total_invocations"] for r in rows),
            "explanation": "Measured counts come straight from the router metrics; they are facts, not advice.",
        },
        "advisory": {
            "stale_or_no_router_call_members": [r["alias"] for r in rows if not r["router_invoked"]],
            "explanation": "Advisory status (stale, readiness) is guidance, not a measured guarantee.",
        },
        "grouping": {
            "by_team": _group_counts(rows, "team"),
            "by_workspace": _group_counts(rows, "workspace"),
            "by_agent_class": _group_counts(rows, "agent_class"),
        },
        "privacy": {
            **_privacy(),
            "labels_are_admin_supplied_local": True,
            "provider_account_ids_included": False,
        },
        "claim_boundary": {
            "allowed_claims": [
                "Local admin CSV/JSON view of router-health readiness across labeled teams/workspaces/agent classes.",
            ],
            "forbidden_claims": [
                "hosted admin dashboard",
                "billing or entitlement",
                "telemetry-backed admin analytics",
            ],
        },
        "delivery": {
            "produced_locally": True,
            "stays_local": True,
            "upload": False,
            "hosted_dashboard": False,
            "billing_or_entitlement": False,
            "note": "Local CSV + JSON admin export; no hosted dashboard, billing, or telemetry.",
        },
    }
    assert_router_health_safe(export)
    return export


def router_health_admin_export_json(export: dict[str, Any]) -> str:
    assert_router_health_safe(export)
    return json.dumps(export, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def router_health_admin_export_csv(export: dict[str, Any]) -> str:
    """Render the admin export rows as CSV consistent with the JSON rows."""
    import csv
    import io

    assert_router_health_safe(export)
    columns = export.get("csv_columns") or _ADMIN_CSV_COLUMNS
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in export.get("rows", []):
        writer.writerow({col: row.get(col, "") for col in columns})
    return buffer.getvalue()
