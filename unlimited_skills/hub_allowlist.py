from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .registration import redact_sensitive_text, unlimited_skills_home, write_private_json


ALLOWLIST_NAME = "allowlist.v1.json"
ALLOWLIST_META_NAME = "allowlist.meta.json"
HUB_DIR_NAME = "hub"
HUB_CLIENTS_NAME = "clients.json"
HUB_LOG_DIR_NAME = "logs"
ALLOWED_HUB_READY_CATEGORIES = {"HUB_READY_PURE_TEXT", "HUB_READY_WITH_ASSETS"}
EXCLUDED_GROUPS = ("blocked", "local_only", "needs_human_review")
SECRET_KEY_RE = re.compile(r"(?i)(token|secret|password|private[_-]?key|api[_-]?key|credential)")
PRIVATE_BODY_RE = re.compile(r"(?i)(^---\s*$|BEGIN [A-Z ]*PRIVATE KEY|PRIVATE_BODY_SENTINEL|LOCAL_USER_PATH_SENTINEL)", re.MULTILINE)


class HubAllowlistError(RuntimeError):
    """Raised when a Local Skill Hub allowlist violates the allowlist-only policy."""


def hub_dir(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / HUB_DIR_NAME


def cached_allowlist_path(home: Path | None = None) -> Path:
    return hub_dir(home) / ALLOWLIST_NAME


def cached_allowlist_meta_path(home: Path | None = None) -> Path:
    return hub_dir(home) / ALLOWLIST_META_NAME


def hub_clients_path(home: Path | None = None) -> Path:
    return hub_dir(home) / HUB_CLIENTS_NAME


def hub_logs_dir(home: Path | None = None) -> Path:
    return hub_dir(home) / HUB_LOG_DIR_NAME


def ensure_hub_layout(home: Path | None = None) -> dict[str, str]:
    root = hub_dir(home)
    root.mkdir(parents=True, exist_ok=True)
    hub_logs_dir(home).mkdir(parents=True, exist_ok=True)
    clients = hub_clients_path(home)
    if not clients.exists():
        write_private_json(clients, {"schema_version": 1, "clients": []})
    return {
        "hub_dir": str(root),
        "allowlist": str(cached_allowlist_path(home)),
        "allowlist_meta": str(cached_allowlist_meta_path(home)),
        "clients": str(clients),
        "logs": str(hub_logs_dir(home)),
    }


def read_allowlist(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HubAllowlistError(f"Cannot read hub allowlist: {path}") from exc
    if not isinstance(data, dict):
        raise HubAllowlistError("Hub allowlist must be a JSON object.")
    return data


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def allowlist_sha256(data: dict[str, Any]) -> str:
    return sha256_text(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def validate_allowlist(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    policy = data.get("policy")
    if not isinstance(policy, dict):
        errors.append("policy must be an object")
        policy = {}
    source_audit = data.get("source_audit")
    if not isinstance(source_audit, dict):
        errors.append("source_audit must be an object")
        source_audit = {}
    verdict = str(source_audit.get("verdict") or "YES_WITH_ALLOWLIST")
    if verdict == "YES_WITH_ALLOWLIST" and policy.get("full_catalog_distribution_allowed") is not False:
        errors.append("full_catalog_distribution_allowed must be false for YES_WITH_ALLOWLIST")
    if policy.get("requires_registration") is not True:
        errors.append("requires_registration must be true")
    if int(policy.get("free_active_client_instance_limit") or 0) != 100:
        errors.append("free_active_client_instance_limit must be 100")
    if policy.get("hub_executes_skills") is not False:
        errors.append("hub_executes_skills must be false")
    if policy.get("hosted_registry_receives_search_queries_by_default") is not False:
        errors.append("hosted_registry_receives_search_queries_by_default must be false")

    excluded_names = excluded_skill_keys(data)
    allowlist = data.get("allowlist")
    if not isinstance(allowlist, list):
        errors.append("allowlist must be an array")
        allowlist = []
    for idx, item in enumerate(allowlist):
        if not isinstance(item, dict):
            errors.append(f"allowlist[{idx}] must be an object")
            continue
        name = str(item.get("name") or item.get("skill_id") or "")
        collection = str(item.get("collection") or "")
        sha256 = str(item.get("sha256") or "")
        hub_behavior = str(item.get("hub_behavior") or "")
        category = str(item.get("primary_category") or "")
        if not name:
            errors.append(f"allowlist[{idx}] missing name")
        if not collection:
            errors.append(f"allowlist[{idx}] missing collection")
        if len(sha256) != 64 or not re.fullmatch(r"[a-fA-F0-9]{64}", sha256):
            errors.append(f"allowlist[{idx}] missing valid sha256")
        if not hub_behavior:
            errors.append(f"allowlist[{idx}] missing hub_behavior")
        if category and category not in ALLOWED_HUB_READY_CATEGORIES:
            errors.append(f"allowlist[{idx}] has non-distributable category {category}")
        if skill_key(collection, name) in excluded_names:
            errors.append(f"allowlist[{idx}] includes excluded skill {collection}/{name}")
        validate_no_embedded_body(item, f"allowlist[{idx}]", errors)
        validate_no_secret_fields(item, f"allowlist[{idx}]", errors)

    for field in ("local_install_plan_candidates",):
        candidates = data.get(field, [])
        if candidates is None:
            candidates = []
        if not isinstance(candidates, list):
            errors.append(f"{field} must be an array when present")
            continue
        for idx, item in enumerate(candidates):
            if not isinstance(item, dict):
                errors.append(f"{field}[{idx}] must be an object")
                continue
            if not (item.get("name") or item.get("skill_id")) or not item.get("collection") or not item.get("sha256") or not item.get("hub_behavior"):
                errors.append(f"{field}[{idx}] must include name, collection, sha256, and hub_behavior")
            validate_no_embedded_body(item, f"{field}[{idx}]", errors)
            validate_no_secret_fields(item, f"{field}[{idx}]", errors)

    validate_no_embedded_body(data, "allowlist", errors)
    validate_no_secret_fields(data, "allowlist", errors)
    if errors:
        raise HubAllowlistError("Invalid Local Skill Hub allowlist: " + "; ".join(redact_sensitive_text(error) for error in errors))
    return data


def validate_allowlist_file(path: Path) -> dict[str, Any]:
    return validate_allowlist(read_allowlist(path))


def cache_allowlist(data: dict[str, Any], *, source: str, home: Path | None = None, notes: str = "") -> dict[str, Any]:
    ensure_hub_layout(home)
    validated = validate_allowlist(data)
    sha = allowlist_sha256(validated)
    allowlist_path = cached_allowlist_path(home)
    meta_path = cached_allowlist_meta_path(home)
    write_private_json(allowlist_path, validated)
    meta = {
        "schema_version": 1,
        "source": source,
        "sha256": sha,
        "cached_at": now_iso(),
        "distribution_mode": "allowlist_only",
        "catalog_audit_verdict": str((validated.get("source_audit") or {}).get("verdict") or "YES_WITH_ALLOWLIST"),
        "full_catalog_distribution_allowed": False,
        "requires_registration": True,
        "free_active_client_instance_limit": 100,
        "allowlist_total": len(validated.get("allowlist") or []),
        "notes": notes,
    }
    write_private_json(meta_path, meta)
    return {"allowlist_path": str(allowlist_path), "meta_path": str(meta_path), "meta": meta}


def cached_allowlist_summary(home: Path | None = None) -> dict[str, Any]:
    path = cached_allowlist_path(home)
    meta_path = cached_allowlist_meta_path(home)
    if not path.exists():
        return {"present": False, "path": str(path), "meta_path": str(meta_path)}
    data = validate_allowlist_file(path)
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                meta = raw
        except (OSError, json.JSONDecodeError):
            meta = {}
    return {
        "present": True,
        "path": str(path),
        "meta_path": str(meta_path),
        "sha256": allowlist_sha256(data),
        "distribution_mode": "allowlist_only",
        "catalog_audit_verdict": str((data.get("source_audit") or {}).get("verdict") or "YES_WITH_ALLOWLIST"),
        "full_catalog_distribution_allowed": False,
        "requires_registration": True,
        "free_active_client_instance_limit": 100,
        "allowlist_total": len(data.get("allowlist") or []),
        "local_install_plan_candidates": len(data.get("local_install_plan_candidates") or []),
        "meta": meta,
    }


def skill_key(collection: str, name: str) -> str:
    return f"{collection.strip().lower()}/{name.strip().lower()}"


def excluded_skill_keys(data: dict[str, Any]) -> set[str]:
    excluded = data.get("excluded") if isinstance(data.get("excluded"), dict) else {}
    results: set[str] = set()
    for group in EXCLUDED_GROUPS:
        rows = excluded.get(group, []) if isinstance(excluded, dict) else []
        if not isinstance(rows, list):
            continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("skill_id") or "")
            collection = str(item.get("collection") or "")
            if name and collection:
                results.add(skill_key(collection, name))
    return results


def validate_no_embedded_body(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in {"body", "skill_body", "content", "skill_md", "skill.md"}:
                errors.append(f"{path}.{key} must not embed a skill body")
            validate_no_embedded_body(child, f"{path}.{key}", errors)
        return
    if isinstance(value, list):
        for idx, child in enumerate(value):
            validate_no_embedded_body(child, f"{path}[{idx}]", errors)
        return
    if isinstance(value, str) and len(value) > 200 and PRIVATE_BODY_RE.search(value):
        errors.append(f"{path} appears to embed private skill body or key material")


def validate_no_secret_fields(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET_KEY_RE.search(str(key)) and child not in ("", None, False):
                errors.append(f"{path}.{key} must not contain secrets")
            validate_no_secret_fields(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            validate_no_secret_fields(child, f"{path}[{idx}]", errors)


def now_iso() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
