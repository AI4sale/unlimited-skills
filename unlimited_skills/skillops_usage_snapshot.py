from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Any

from . import __version__
from .catalog_browser import redacted_catalog_browser_summary
from .catalog_quality import redacted_catalog_quality_summary
from .enterprise_policy import redacted_enterprise_policy_summary
from .maintainer_queue_status import redacted_maintainer_queue_summary
from .plan_status import redacted_plan_summary
from .private_pack_diagnostics import private_pack_local_summary
from .recommendation_policy import DECISION_TABLE, FORBIDDEN_TEXT_PATTERNS, PRIVATE_DATA_KEYS
from .registration import RegistrationError, RegistrationState, load_registration, unlimited_skills_home
from .skill_improvements import redacted_skill_improvement_summary
from .updates import current_collection_state, load_release_channel


SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_TYPE = "skillops-usage-snapshot"
ALLOWED_SENSITIVE_FLAG_KEYS = {
    "customer_data_included",
    "environment_values_included",
    "local_paths_included",
    "private_keys_included",
    "private_pack_names_included",
    "private_skill_names_included",
    "prompts_included",
    "proofs_included",
    "repo_paths_included",
    "search_queries_included",
    "skill_bodies_included",
    "skill_names_included",
    "task_text_included",
    "tokens_included",
}
FORBIDDEN_TEXT_MARKERS = (
    "authorization: bearer",
    "license_token",
    "device_private_key",
    "private key",
    "skill.md",
    "x-uls-proof",
    "x-uls-hub-token",
)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def os_bucket() -> str:
    system = platform.system().strip().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    if system == "linux":
        return "linux"
    return "other"


def _count_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    if count <= 10:
        return "1-10"
    if count <= 50:
        return "11-50"
    if count <= 250:
        return "51-250"
    if count <= 1000:
        return "251-1000"
    return "1000+"


def _manifest_sources(root: Path) -> dict[str, str]:
    path = root / ".unlimited-skills-collections.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    collections = payload.get("collections") if isinstance(payload, dict) else {}
    if not isinstance(collections, dict):
        return {}
    sources: dict[str, str] = {}
    for name, row in collections.items():
        if isinstance(row, dict):
            sources[str(name)] = str(row.get("source") or "").lower()
    return sources


def _source_bucket(root: Path, skill_file: Path, sources: dict[str, str]) -> str:
    try:
        rel = skill_file.relative_to(root)
    except ValueError:
        return "local"
    parts = rel.parts
    if not parts:
        return "local"
    if parts[0] == "local":
        return "local"
    if parts[0] == "registry" and len(parts) > 1:
        collection = parts[1]
        source = sources.get(collection, "")
        combined = f"{collection} {source}".lower()
        if "private" in combined or "team-pack" in combined:
            return "private"
        if "community" in combined:
            return "community"
        return "official"
    return "local"


def _skill_inventory(root: Path) -> dict[str, Any]:
    sources = _manifest_sources(root)
    counts = {"official": 0, "community": 0, "private": 0, "local": 0}
    collection_names: set[str] = set()
    physical_count = 0
    if root.is_dir():
        for skill_file in root.rglob("SKILL.md"):
            try:
                rel_parts = skill_file.relative_to(root).parts
            except ValueError:
                continue
            if ".rollbacks" in rel_parts or "duplicates" in rel_parts:
                continue
            physical_count += 1
            bucket = _source_bucket(root, skill_file, sources)
            counts[bucket] += 1
            if rel_parts and rel_parts[0] == "registry" and len(rel_parts) > 1:
                collection_names.add(rel_parts[1])
            elif rel_parts and rel_parts[0] == "local":
                collection_names.add("local")
            elif rel_parts:
                collection_names.add(rel_parts[0])
    index_path = root / ".unlimited-skills-index.json"
    index_record_count = 0
    index_readable = False
    if index_path.is_file():
        try:
            records = json.loads(index_path.read_text(encoding="utf-8-sig"))
            if isinstance(records, list):
                index_record_count = len(records)
                index_readable = True
        except (OSError, json.JSONDecodeError):
            index_readable = False
    state = current_collection_state(root)
    return {
        "root_present": root.is_dir(),
        "physical_skill_files": physical_count,
        "physical_skill_file_bucket": _count_bucket(physical_count),
        "collection_count": len(collection_names or set(state)),
        "official_pack_skill_count": counts["official"],
        "community_pack_skill_count": counts["community"],
        "private_pack_skill_count": counts["private"],
        "local_skill_count": counts["local"],
        "installed_pack_counts": {
            "official": len([name for name, row in state.items() if "private" not in row.get("source", "").lower() and "community" not in row.get("source", "").lower() and name != "local"]),
            "community": len([row for row in state.values() if "community" in row.get("source", "").lower()]),
            "private": len([row for row in state.values() if "private" in row.get("source", "").lower() or "team-pack" in row.get("source", "").lower()]),
            "local": 1 if "local" in state or counts["local"] else 0,
        },
        "index_present": index_path.is_file(),
        "index_readable": index_readable,
        "index_record_count": index_record_count,
        "vector_sidecar_present": (root / ".unlimited-skills-vector.json").is_file(),
        "chroma_present": (root / ".chroma-skills").is_dir(),
        "collection_names_included": False,
        "skill_names_included": False,
        "skill_bodies_included": False,
        "local_paths_included": False,
    }


def _registration_state(home: Path) -> RegistrationState:
    try:
        return load_registration(home)
    except RegistrationError:
        return RegistrationState()


def _plan_summary(state: RegistrationState, home: Path) -> dict[str, Any]:
    try:
        raw = redacted_plan_summary(state=state, home=home)
    except Exception:
        return {
            "schema_version": 1,
            "registered": bool(state.registered),
            "source": "local-error",
            "plan": state.plan or ("registered-community" if state.registered else "community-core"),
            "status": "unknown",
            "features_enabled": [],
            "limits": {},
            "policy": {},
            "last_heartbeat_at": "",
            "offline_grace_status": "unknown",
            "denial_reason": "",
            "privacy": _privacy_flags(),
        }
    return {
        "schema_version": 1,
        "registered": bool(raw.get("registered")),
        "source": str(raw.get("source") or "local"),
        "plan": str(raw.get("plan") or "community-core"),
        "status": str(raw.get("status") or "unknown"),
        "features_enabled": sorted(str(item) for item in (raw.get("features_enabled") or []) if str(item).strip()),
        "limits": raw.get("limits") if isinstance(raw.get("limits"), dict) else {},
        "last_heartbeat_at": str(raw.get("last_heartbeat_at") or ""),
        "offline_grace_status": str(raw.get("offline_grace_status") or "unknown"),
        "denial_reason": str(raw.get("denial_reason") or ""),
        "privacy": _privacy_flags(),
    }


def _recommendation_outcome_counts() -> dict[str, Any]:
    counts: dict[str, int] = {}
    refusal_counts: dict[str, int] = {}
    for decision in DECISION_TABLE:
        counts[decision.outcome] = counts.get(decision.outcome, 0) + 1
        if decision.refusal_code:
            refusal_counts[decision.refusal_code] = refusal_counts.get(decision.refusal_code, 0) + 1
    return {
        "fixture_decision_count": len(DECISION_TABLE),
        "outcome_counts": counts,
        "refusal_code_counts": refusal_counts,
        "preview_only": True,
        "automatic_install": False,
        "automatic_update": False,
        "automatic_remove": False,
        "item_ids_included": False,
        "item_names_included": False,
    }


def _release_channel(home: Path) -> dict[str, Any]:
    try:
        state = load_release_channel(home)
    except Exception:
        return {"schema_version": 1, "channel": "stable", "pinned": False, "status": "unknown"}
    return {"schema_version": 1, "channel": state.channel, "pinned": state.pinned, "status": "ok" if state.channel else "unknown"}


def _privacy_flags() -> dict[str, bool]:
    return {
        "prompts_included": False,
        "task_text_included": False,
        "skill_bodies_included": False,
        "skill_names_included": False,
        "search_queries_included": False,
        "private_pack_names_included": False,
        "private_skill_names_included": False,
        "local_paths_included": False,
        "repo_paths_included": False,
        "customer_data_included": False,
        "environment_values_included": False,
        "tokens_included": False,
        "proofs_included": False,
        "private_keys_included": False,
    }


def build_usage_snapshot(root: Path, *, dry_run: bool = False, created_at: str | None = None) -> dict[str, Any]:
    root = root.expanduser()
    home = unlimited_skills_home()
    state = _registration_state(home)
    plan = _plan_summary(state, home)
    policy = redacted_enterprise_policy_summary(home=home)
    catalog_quality = redacted_catalog_quality_summary()
    improvements = redacted_skill_improvement_summary()
    maintainer_queue = redacted_maintainer_queue_summary()
    private_packs = private_pack_local_summary(root, include_pack_ids=False)
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_type": SNAPSHOT_TYPE,
        "created_at": created_at or now_iso(),
        "dry_run": dry_run,
        "local_only": True,
        "network_calls": False,
        "hosted_calls": False,
        "upload_available": False,
        "client": {"name": "unlimited-skills", "version": __version__},
        "system": {"os_bucket": os_bucket()},
        "library": _skill_inventory(root),
        "release_channel": _release_channel(home),
        "registration": {
            "registered": bool(state.registered),
            "plan": state.plan or ("registered-community" if state.registered else "community-core"),
            "telemetry": state.telemetry or "off",
            "install_id_included": False,
            "license_token_included": False,
            "proofs_included": False,
            "private_keys_included": False,
        },
        "plan": plan,
        "policy": policy,
        "recommendations": _recommendation_outcome_counts(),
        "catalog_browser": redacted_catalog_browser_summary(),
        "catalog_quality": catalog_quality,
        "skill_improvements": improvements,
        "maintainer_queue": maintainer_queue,
        "private_packs": {
            "installed_count": int(private_packs.get("installed_count") or 0),
            "revoked_count": int(private_packs.get("revoked_count") or 0),
            "stale_count": int(private_packs.get("stale_count") or 0),
            "missing_target_count": int(private_packs.get("missing_target_count") or 0),
            "access_denied_count": int(private_packs.get("access_denied_count") or 0),
            "pack_names_included": False,
            "pack_refs_included": False,
            "skill_names_included": False,
            "skill_bodies_included": False,
            "archive_urls_included": False,
            "local_paths_included": False,
        },
        "governance": {
            "summary_available": bool(policy.get("governance_summary_available")),
            "policy_mode": str(policy.get("mode") or "disabled"),
            "policy_body_included": False,
        },
        "update_recommendations": {
            "update_recommendation_count": int(improvements.get("improvement_status", {}).get("update_recommendation_count") or 0),
            "remove_recommendation_count": int(improvements.get("improvement_status", {}).get("remove_recommendation_count") or 0),
            "preview_only": True,
            "automatic_install": False,
            "automatic_update": False,
            "automatic_remove": False,
        },
        "support_bundle": {
            "may_include_usage_snapshot_counts": True,
            "counts_only": True,
            "details_included_by_default": False,
        },
        "privacy": _privacy_flags(),
    }
    assert_usage_snapshot_safe(payload)
    return payload


def support_bundle_usage_summary(root: Path) -> dict[str, Any]:
    snapshot = build_usage_snapshot(root, dry_run=True)
    summary = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "available": True,
        "counts_only": True,
        "library": {
            "physical_skill_files": snapshot["library"]["physical_skill_files"],
            "official_pack_skill_count": snapshot["library"]["official_pack_skill_count"],
            "community_pack_skill_count": snapshot["library"]["community_pack_skill_count"],
            "private_pack_skill_count": snapshot["library"]["private_pack_skill_count"],
            "local_skill_count": snapshot["library"]["local_skill_count"],
            "index_record_count": snapshot["library"]["index_record_count"],
        },
        "recommendations": {
            "fixture_decision_count": snapshot["recommendations"]["fixture_decision_count"],
            "outcome_counts": snapshot["recommendations"]["outcome_counts"],
        },
        "quality": snapshot["catalog_quality"]["quality_status"],
        "updates": snapshot["update_recommendations"],
        "maintainer_queue": snapshot["maintainer_queue"]["queue_status"],
        "privacy": _privacy_flags(),
    }
    assert_usage_snapshot_safe(summary)
    return summary


def assert_usage_snapshot_safe(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in PRIVATE_DATA_KEYS and lowered not in ALLOWED_SENSITIVE_FLAG_KEYS:
                raise RuntimeError(f"Usage snapshot contains forbidden field: {key_text}")
            if lowered in ALLOWED_SENSITIVE_FLAG_KEYS and item is not False:
                raise RuntimeError(f"Usage snapshot privacy flag must be false: {key_text}")
            assert_usage_snapshot_safe(item, path=f"{path}.{key_text}")
        return
    if isinstance(value, list):
        for idx, item in enumerate(value):
            assert_usage_snapshot_safe(item, path=f"{path}[{idx}]")
        return
    if isinstance(value, str):
        lowered = value.lower()
        for marker in FORBIDDEN_TEXT_MARKERS:
            if marker in lowered:
                raise RuntimeError(f"Usage snapshot contains forbidden marker at {path}: {marker}")
        for pattern in FORBIDDEN_TEXT_PATTERNS:
            if pattern.search(value):
                raise RuntimeError(f"Usage snapshot contains forbidden sensitive text at {path}.")


def format_usage_snapshot_text(snapshot: dict[str, Any]) -> str:
    library = snapshot["library"]
    plan = snapshot["plan"]
    updates = snapshot["update_recommendations"]
    queue = snapshot["maintainer_queue"]["queue_status"]
    lines = [
        "SkillOps usage snapshot",
        "Local-only: yes",
        "Hosted calls: no",
        "Upload: no",
        "Dry run: " + ("yes" if snapshot.get("dry_run") else "no"),
        f"Client: {snapshot['client']['version']}",
        f"OS bucket: {snapshot['system']['os_bucket']}",
        f"Release channel: {snapshot['release_channel']['channel']}",
        f"Plan: {plan.get('plan') or 'community-core'}",
        f"Policy mode: {snapshot['policy'].get('mode') or 'disabled'}",
        f"Physical skill files: {library['physical_skill_files']}",
        (
            "Skill counts: "
            f"official={library['official_pack_skill_count']}, "
            f"community={library['community_pack_skill_count']}, "
            f"private={library['private_pack_skill_count']}, "
            f"local={library['local_skill_count']}"
        ),
        f"Recommendation fixture decisions: {snapshot['recommendations']['fixture_decision_count']}",
        (
            "Update recommendations: "
            f"update={updates['update_recommendation_count']}, "
            f"remove={updates['remove_recommendation_count']}"
        ),
        f"Maintainer queue items: {queue.get('total_count', 0)}",
        "Privacy: counts only; no prompts, task text, skill bodies, search queries, private names, paths, tokens, proofs, or private keys.",
    ]
    return "\n".join(lines)


def usage_snapshot_explain() -> str:
    return "\n".join(
        [
            "SkillOps usage snapshot is a local-only diagnostic summary for future recommendation context.",
            "It reads local metadata and cached redacted summaries only.",
            "It does not call hosted services, upload data, forward queries, install, update, remove, rewrite, reindex, or publish skills.",
            "The snapshot includes counts and coarse states such as client version, OS bucket, library counts, release channel, plan flags, policy mode, recommendation outcome counts, quality warning counts, maintainer queue counts, and update recommendation counts.",
            "The snapshot excludes prompts, task text, skill bodies, search queries, local paths, repo paths, customer data, environment values, tokens, proofs, private keys, private pack names, and private skill names by default.",
            "Support bundles may include usage snapshot counts only.",
        ]
    )
