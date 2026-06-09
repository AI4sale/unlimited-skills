from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Any

from . import __version__
from .hub_allowlist import cached_allowlist_summary, hub_dir
from .registration import RegistrationState, post_json, redact_sensitive_text, unlimited_skills_home, write_private_json


ENTITLEMENTS_NAME = "entitlements.json"
DEFAULT_OFFLINE_GRACE_SECONDS = 7 * 24 * 60 * 60
FORBIDDEN_HEARTBEAT_KEYS = {
    "query",
    "queries",
    "prompt",
    "prompts",
    "skill",
    "skills",
    "skill_name",
    "skill_names",
    "body",
    "bodies",
    "path",
    "paths",
    "repo_path",
    "local_path",
    "customer",
    "customer_name",
    "env",
    "env_vars",
    "token",
    "tokens",
    "secret",
    "secrets",
    "private_key",
    "device_private_key",
    "license_token",
}
ALLOWED_FEATURE_FLAGS = {
    "local_skill_hub",
    "max_hub_clients",
    "hub_distribution_mode",
    "signed_manifests_required",
    "team_sync_enabled",
}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def epoch_to_iso(value: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def entitlements_path(home: Path | None = None) -> Path:
    return hub_dir(home) / ENTITLEMENTS_NAME


def count_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    if count <= 10:
        return "1-10"
    if count <= 50:
        return "11-50"
    if count <= 100:
        return "51-100"
    if count <= 250:
        return "101-250"
    if count <= 1000:
        return "251-1000"
    return "1000+"


def os_bucket() -> str:
    value = platform.system().lower()
    if value.startswith("win"):
        return "windows"
    if value.startswith("darwin"):
        return "macos"
    if value.startswith("linux"):
        return "linux"
    return "other"


def normalize_feature_flags(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    flags: dict[str, Any] = {}
    for key, item in value.items():
        key = str(key)
        if key not in ALLOWED_FEATURE_FLAGS:
            continue
        if key == "max_hub_clients":
            try:
                flags[key] = max(0, int(item))
            except (TypeError, ValueError):
                continue
        elif key == "hub_distribution_mode":
            flags[key] = str(item or "allowlist_only")
        else:
            flags[key] = bool(item)
    return flags


def has_forbidden_heartbeat_fields(value: Any) -> list[str]:
    found: list[str] = []

    def walk(item: Any, path: str = "") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                key_text = str(key)
                normalized = key_text.lower().replace("-", "_")
                child_path = f"{path}.{key_text}" if path else key_text
                if normalized in FORBIDDEN_HEARTBEAT_KEYS:
                    found.append(child_path)
                walk(child, child_path)
        elif isinstance(item, list):
            for idx, child in enumerate(item):
                walk(child, f"{path}[{idx}]")

    walk(value)
    return sorted(set(found))


def load_entitlements(home: Path | None = None) -> dict[str, Any]:
    path = entitlements_path(home)
    if not path.is_file():
        return {
            "schema_version": 1,
            "source": "unregistered",
            "plan": "community-core",
            "features_enabled": [],
            "limits": {"max_hub_clients": 100},
            "policy": {
                "hub_distribution_mode": "allowlist_only",
                "signed_manifests_required": True,
                "hosted_query_forwarding_allowed": False,
            },
            "last_heartbeat_at": "",
            "offline_grace_until": "",
            "offline_grace_status": "unregistered",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", 1)
    payload.setdefault("source", "cached")
    payload.setdefault("limits", {"max_hub_clients": 100})
    payload.setdefault("policy", {"hub_distribution_mode": "allowlist_only", "signed_manifests_required": True, "hosted_query_forwarding_allowed": False})
    return payload


def save_entitlements(payload: dict[str, Any], home: Path | None = None) -> Path:
    return write_private_json(entitlements_path(home), payload)


def offline_grace_status(payload: dict[str, Any], *, now: float | None = None) -> str:
    now = now if now is not None else time.time()
    value = str(payload.get("offline_grace_until") or "")
    if not value:
        return "none"
    try:
        parsed = time.strptime(value.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
        expires = time.mktime(parsed)
    except ValueError:
        return "invalid"
    return "active" if expires >= now else "expired"


def entitlement_summary(state: RegistrationState | None = None, home: Path | None = None) -> dict[str, Any]:
    payload = load_entitlements(home)
    if state is not None and not state.registered:
        payload["source"] = "unregistered"
    status = offline_grace_status(payload)
    return {
        "source": str(payload.get("source") or "cached"),
        "plan": str(payload.get("plan") or (state.plan if state else "") or "community-core"),
        "features_enabled": [str(item) for item in payload.get("features_enabled", []) if isinstance(item, str)],
        "limits": payload.get("limits") if isinstance(payload.get("limits"), dict) else {"max_hub_clients": 100},
        "policy": payload.get("policy") if isinstance(payload.get("policy"), dict) else {},
        "last_heartbeat_at": str(payload.get("last_heartbeat_at") or ""),
        "offline_grace_until": str(payload.get("offline_grace_until") or ""),
        "offline_grace_status": status,
    }


def build_heartbeat_payload(
    state: RegistrationState,
    *,
    active_client_count: int = 0,
    status_summary: dict[str, Any] | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    from .hub import HUB_FEATURE_FLAGS, load_hub_config

    hub_config = load_hub_config(home)
    allowlist = cached_allowlist_summary(home)
    entitlement = entitlement_summary(state, home)
    flags = dict(HUB_FEATURE_FLAGS)
    flags.update(normalize_feature_flags(entitlement.get("policy", {})))
    flags["max_hub_clients"] = int((entitlement.get("limits") or {}).get("max_hub_clients") or hub_config.get("active_client_limit") or flags["max_hub_clients"])
    payload = {
        "schema_version": 1,
        "install_id": state.install_id,
        "hub_id": str(hub_config.get("hub_id") or ""),
        "client": {"name": "unlimited-skills", "version": __version__},
        "plan": state.plan or entitlement.get("plan") or "registered-community",
        "hub": {
            "active_client_count": int(active_client_count),
            "active_client_count_bucket": count_bucket(int(active_client_count)),
            "active_client_limit": int(flags["max_hub_clients"]),
            "distribution_mode": str(hub_config.get("distribution_mode") or flags["hub_distribution_mode"]),
            "allowlist_sha256": str(allowlist.get("sha256") or ""),
            "allowlist_present": bool(allowlist.get("present")),
            "hosted_query_forwarding": False,
        },
        "feature_flags": {
            "local_skill_hub": bool(flags.get("local_skill_hub", True)),
            "max_hub_clients": int(flags["max_hub_clients"]),
            "hub_distribution_mode": str(flags.get("hub_distribution_mode") or "allowlist_only"),
            "signed_manifests_required": bool(flags.get("signed_manifests_required", True)),
            "team_sync_enabled": bool(flags.get("team_sync_enabled", False)),
        },
        "platform": {"os_bucket": os_bucket()},
        "status_summary": status_summary or {"errors_bucket": "0", "warnings_bucket": "0"},
    }
    forbidden = has_forbidden_heartbeat_fields(payload)
    if forbidden:
        raise RuntimeError("Heartbeat payload contains forbidden privacy fields: " + ", ".join(forbidden))
    return payload


def validate_entitlement_response(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("schema_version") != 1:
        raise RuntimeError("Entitlement service returned unsupported schema_version.")
    limits = response.get("limits") if isinstance(response.get("limits"), dict) else {}
    policy = response.get("policy") if isinstance(response.get("policy"), dict) else {}
    max_clients = int(limits.get("max_hub_clients") or 100)
    if max_clients < 0:
        raise RuntimeError("Entitlement max_hub_clients must be non-negative.")
    distribution_mode = str(policy.get("hub_distribution_mode") or "allowlist_only")
    if distribution_mode != "allowlist_only":
        raise RuntimeError("Entitlement service must keep hub_distribution_mode=allowlist_only.")
    if policy.get("hosted_query_forwarding_allowed") is not False:
        raise RuntimeError("Entitlement service must keep hosted_query_forwarding_allowed=false.")
    features = response.get("features_enabled") or []
    if not isinstance(features, list):
        features = []
    grace = response.get("grace") if isinstance(response.get("grace"), dict) else {}
    offline_until = str(grace.get("offline_grace_until") or epoch_to_iso(time.time() + DEFAULT_OFFLINE_GRACE_SECONDS))
    return {
        "schema_version": 1,
        "source": "refreshed",
        "plan": str(response.get("plan") or "registered-community"),
        "features_enabled": [str(item) for item in features if isinstance(item, str)],
        "limits": {"max_hub_clients": max_clients},
        "policy": {
            "hub_distribution_mode": distribution_mode,
            "signed_manifests_required": bool(policy.get("signed_manifests_required", True)),
            "hosted_query_forwarding_allowed": False,
            "team_sync_enabled": bool(policy.get("team_sync_enabled", "team_sync_enabled" in features)),
        },
        "last_heartbeat_at": now_iso(),
        "offline_grace_until": offline_until,
        "offline_grace_status": "active",
        "raw_response_redacted": redact_sensitive_text({key: value for key, value in response.items() if key not in {"token", "license_token", "private_key"}}),
    }


def apply_entitlements(cache: dict[str, Any], home: Path | None = None) -> Path:
    from .hub import load_hub_config, save_hub_config

    config = load_hub_config(home)
    limits = cache.get("limits") if isinstance(cache.get("limits"), dict) else {}
    policy = cache.get("policy") if isinstance(cache.get("policy"), dict) else {}
    config["active_client_limit"] = int(limits.get("max_hub_clients") or 100)
    config["distribution_mode"] = str(policy.get("hub_distribution_mode") or "allowlist_only")
    config["entitlement_source"] = cache.get("source", "cached")
    config["last_heartbeat_at"] = cache.get("last_heartbeat_at", "")
    save_hub_config(config, home)
    return save_entitlements(cache, home)


def refresh_entitlements(
    state: RegistrationState,
    *,
    endpoint: str = "heartbeat",
    active_client_count: int = 0,
    timeout: float = 30.0,
    home: Path | None = None,
) -> dict[str, Any]:
    if not state.registered:
        raise RuntimeError("Registration is required for Local Skill Hub heartbeat and entitlement refresh.")
    if endpoint not in {"heartbeat", "entitlements"}:
        raise RuntimeError("endpoint must be heartbeat or entitlements.")
    payload = build_heartbeat_payload(state, active_client_count=active_client_count, home=home)
    path = "/v1/hub/heartbeat" if endpoint == "heartbeat" else "/v1/hub/entitlements"
    response = post_json(f"{state.server_url.rstrip('/')}{path}", payload, token=state.license_token, proof_state=state, timeout=timeout, retry_safe=True)
    cache = validate_entitlement_response(response)
    apply_entitlements(cache, home)
    return {"request": payload, "response": cache, "endpoint": path}
