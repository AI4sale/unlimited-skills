from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .registration import RegistrationState, load_registration, unlimited_skills_home, write_private_json


HUB_FEATURE_FLAGS = {
    "local_skill_hub": True,
    "max_hub_clients": 100,
    "hub_distribution_mode": "allowlist_only",
}
HUB_DEFAULT_PORT = 8766
REMOTE_CONFIG_NAME = "remote.json"
HUB_REGISTRATION_REQUIRED_MESSAGE = (
    "Registration is required for Local Skill Hub. The MIT local core still works offline. "
    "Use `unlimited-skills serve` for the free local daemon, or run `unlimited-skills register`."
)
HUB_ALPHA_NOT_IMPLEMENTED = "Local Skill Hub runtime is planned/MVP not implemented yet in this alpha."
REMOTE_ALPHA_NOT_IMPLEMENTED = "Remote hub runtime is not implemented in this alpha. Configure/status are available now."


def remote_config_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / REMOTE_CONFIG_NAME


def load_remote_config(home: Path | None = None) -> dict[str, Any]:
    path = remote_config_path(home)
    if not path.exists():
        return {
            "schema_version": 1,
            "configured": False,
            "url": "",
            "token_present": False,
            "fallback_mode": "local_allowed",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return {
        "schema_version": 1,
        "configured": bool(data.get("url")),
        "url": str(data.get("url") or ""),
        "token_present": bool(data.get("token_present")),
        "fallback_mode": str(data.get("fallback_mode") or "local_allowed"),
    }


def save_remote_config(url: str, *, token: str = "", fallback_mode: str = "local_allowed", home: Path | None = None) -> Path:
    if fallback_mode not in {"local_allowed", "hub_required"}:
        raise RuntimeError("fallback_mode must be local_allowed or hub_required.")
    payload = {
        "schema_version": 1,
        "url": url.rstrip("/"),
        "token_present": bool(token),
        "fallback_mode": fallback_mode,
    }
    return write_private_json(remote_config_path(home), payload)


def hub_status_payload(state: RegistrationState | None = None) -> dict[str, Any]:
    state = state or load_registration()
    return {
        "schema_version": 1,
        "hub_id": state.install_id.replace("uls_inst_", "uls_hub_", 1) if state.install_id else "",
        "registered": state.registered,
        "plan": state.plan or "community-core",
        "active_client_count": 0,
        "active_client_limit": HUB_FEATURE_FLAGS["max_hub_clients"],
        "full_catalog_distribution_allowed": False,
        "distribution_mode": HUB_FEATURE_FLAGS["hub_distribution_mode"],
        "catalog_audit_verdict": "YES_WITH_ALLOWLIST",
        "skills_total": 0,
        "allowlisted_skills": 0,
        "vector_index_present": False,
        "hosted_query_forwarding": False,
        "feature_flags": dict(HUB_FEATURE_FLAGS),
        "registration": {
            "token_present": bool(state.license_token),
            "proof_key_present": bool(state.device_private_key),
            "key_thumbprint": state.key_thumbprint,
        },
    }


def ensure_hub_registered() -> RegistrationState:
    state = load_registration()
    if not state.registered:
        raise RuntimeError(HUB_REGISTRATION_REQUIRED_MESSAGE)
    return state


def emit_json(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_hub_init(args: Any) -> int:
    state = load_registration()
    payload = hub_status_payload(state)
    payload["status"] = "initialized" if state.registered else "registration_required"
    payload["message"] = (
        "Local Skill Hub contract initialized."
        if state.registered
        else "Registration is required before serving Local Skill Hub."
    )
    return emit_json(payload)


def cmd_hub_status(args: Any) -> int:
    payload = hub_status_payload()
    if getattr(args, "json", False):
        return emit_json(payload)
    print("Local Skill Hub: " + ("registered" if payload["registered"] else "unregistered"))
    print(f"Plan: {payload['plan']}")
    print(f"Distribution: {payload['distribution_mode']} / audit {payload['catalog_audit_verdict']}")
    print(f"Active clients: {payload['active_client_count']}/{payload['active_client_limit']}")
    print("Hosted query forwarding: off")
    return 0


def cmd_hub_serve(args: Any) -> int:
    ensure_hub_registered()
    raise RuntimeError(HUB_ALPHA_NOT_IMPLEMENTED)


def cmd_hub_clients(args: Any) -> int:
    ensure_hub_registered()
    return emit_json({"schema_version": 1, "clients": [], "count": 0, "active_client_limit": HUB_FEATURE_FLAGS["max_hub_clients"]})


def cmd_hub_token_create(args: Any) -> int:
    ensure_hub_registered()
    raise RuntimeError("Local Skill Hub client token creation is planned/MVP not implemented yet in this alpha.")


def cmd_hub_doctor(args: Any) -> int:
    payload = hub_status_payload()
    payload["checks"] = [
        {"name": "registration", "status": "ok" if payload["registered"] else "warn"},
        {"name": "full_catalog_distribution", "status": "ok", "value": False},
        {"name": "hosted_query_forwarding", "status": "ok", "value": False},
    ]
    return emit_json(payload)


def cmd_remote_configure(args: Any) -> int:
    path = save_remote_config(args.url, token=args.token, fallback_mode=args.fallback_mode)
    payload = load_remote_config()
    payload["config_file"] = str(path)
    return emit_json(payload)


def cmd_remote_status(args: Any) -> int:
    payload = load_remote_config()
    if getattr(args, "json", False):
        return emit_json(payload)
    print("Remote hub: " + ("configured" if payload["configured"] else "not configured"))
    print(f"URL: {payload['url'] or '(none)'}")
    print("Token: " + ("present" if payload["token_present"] else "missing"))
    print(f"Fallback: {payload['fallback_mode']}")
    return 0


def cmd_remote_planned(args: Any) -> int:
    raise RuntimeError(REMOTE_ALPHA_NOT_IMPLEMENTED)
