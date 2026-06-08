from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any

from .registration import RegistrationState, load_registration, redact_sensitive_text, unlimited_skills_home, write_private_json


HUB_FEATURE_FLAGS = {
    "local_skill_hub": True,
    "max_hub_clients": 100,
    "hub_distribution_mode": "allowlist_only",
}
HUB_DEFAULT_PORT = 8766
REMOTE_CONFIG_NAME = "remote.json"
HUB_CONFIG_NAME = "hub.json"
HUB_REGISTRATION_REQUIRED_MESSAGE = (
    "Registration is required for Local Skill Hub. The MIT local core still works offline. "
    "Use `unlimited-skills serve` for the free local daemon, or run `unlimited-skills register`."
)
REMOTE_ALPHA_NOT_IMPLEMENTED = "Remote hub runtime is not implemented in this alpha. Configure/status are available now."
LAN_REFUSAL_MESSAGE = "Refusing to bind Local Skill Hub to a non-localhost address without --allow-lan and an active hub token."
LOCALHOST_HOSTS = {"", "localhost", "127.0.0.1", "::1", "[::1]"}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def hub_config_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / HUB_CONFIG_NAME


def new_hub_id() -> str:
    return "uls_hub_" + secrets.token_urlsafe(18)


def new_hub_token_id() -> str:
    return "hub_tok_" + secrets.token_urlsafe(12)


def new_hub_token() -> str:
    return "uls_hub_" + secrets.token_urlsafe(32)


def hash_hub_token(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def default_hub_config() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "hub_id": new_hub_id(),
        "created_at": now_iso(),
        "tokens": [],
        "active_client_limit": HUB_FEATURE_FLAGS["max_hub_clients"],
        "distribution_mode": HUB_FEATURE_FLAGS["hub_distribution_mode"],
    }


def load_hub_config(home: Path | None = None) -> dict[str, Any]:
    path = hub_config_path(home)
    if not path.exists():
        return default_hub_config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read Local Skill Hub config: {path}") from exc
    if not isinstance(data, dict):
        return default_hub_config()
    tokens = data.get("tokens")
    if not isinstance(tokens, list):
        tokens = []
    return {
        "schema_version": int(data.get("schema_version") or 1),
        "hub_id": str(data.get("hub_id") or new_hub_id()),
        "created_at": str(data.get("created_at") or now_iso()),
        "tokens": [token for token in tokens if isinstance(token, dict)],
        "active_client_limit": int(data.get("active_client_limit") or HUB_FEATURE_FLAGS["max_hub_clients"]),
        "distribution_mode": str(data.get("distribution_mode") or HUB_FEATURE_FLAGS["hub_distribution_mode"]),
    }


def save_hub_config(config: dict[str, Any], home: Path | None = None) -> Path:
    return write_private_json(hub_config_path(home), config)


def active_hub_tokens(config: dict[str, Any] | None = None, home: Path | None = None) -> list[dict[str, Any]]:
    config = config or load_hub_config(home)
    return [token for token in config.get("tokens", []) if not bool(token.get("revoked"))]


def active_hub_token_count(home: Path | None = None) -> int:
    return len(active_hub_tokens(home=home))


def create_hub_token(label: str = "default", home: Path | None = None) -> dict[str, Any]:
    config = load_hub_config(home)
    raw_token = new_hub_token()
    record = {
        "token_id": new_hub_token_id(),
        "token_hash": hash_hub_token(raw_token),
        "label": label or "default",
        "created_at": now_iso(),
        "last_used_at": None,
        "revoked": False,
    }
    config.setdefault("tokens", []).append(record)
    save_hub_config(config, home)
    return {"raw_token": raw_token, "record": dict(record), "config_path": str(hub_config_path(home))}


def list_hub_tokens(home: Path | None = None) -> list[dict[str, Any]]:
    config = load_hub_config(home)
    rows = []
    for token in config.get("tokens", []):
        rows.append(
            {
                "token_id": str(token.get("token_id") or ""),
                "label": str(token.get("label") or ""),
                "created_at": token.get("created_at"),
                "last_used_at": token.get("last_used_at"),
                "revoked": bool(token.get("revoked")),
            }
        )
    return rows


def revoke_hub_token(token_id: str, home: Path | None = None) -> dict[str, Any]:
    config = load_hub_config(home)
    found: dict[str, Any] | None = None
    for token in config.get("tokens", []):
        if str(token.get("token_id") or "") == token_id:
            token["revoked"] = True
            found = token
            break
    if found is None:
        raise RuntimeError(f"Hub token not found: {token_id}")
    save_hub_config(config, home)
    return {
        "token_id": str(found.get("token_id") or ""),
        "label": str(found.get("label") or ""),
        "created_at": found.get("created_at"),
        "last_used_at": found.get("last_used_at"),
        "revoked": True,
    }


def verify_hub_token(raw_token: str, home: Path | None = None, *, update_last_used: bool = True) -> tuple[bool, str, dict[str, Any] | None]:
    if not raw_token:
        return False, "hub_token_required", None
    config = load_hub_config(home)
    wanted_hash = hash_hub_token(raw_token)
    for token in config.get("tokens", []):
        stored_hash = str(token.get("token_hash") or "")
        if not hmac.compare_digest(stored_hash, wanted_hash):
            continue
        if bool(token.get("revoked")):
            return False, "hub_token_revoked", token
        if update_last_used:
            token["last_used_at"] = now_iso()
            save_hub_config(config, home)
        return True, "ok", token
    return False, "invalid_hub_token", None


def is_localhost_bind(host: str) -> bool:
    value = (host or "").strip().lower()
    return value in LOCALHOST_HOSTS


def ensure_lan_bind_allowed(host: str, *, allow_lan: bool, home: Path | None = None) -> None:
    if is_localhost_bind(host):
        return
    if not allow_lan or active_hub_token_count(home) <= 0:
        raise RuntimeError(LAN_REFUSAL_MESSAGE)


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
    hub_config = load_hub_config()
    return {
        "schema_version": 1,
        "hub_id": hub_config.get("hub_id") or (state.install_id.replace("uls_inst_", "uls_hub_", 1) if state.install_id else ""),
        "registered": state.registered,
        "plan": state.plan or "community-core",
        "active_client_count": 0,
        "active_client_limit": HUB_FEATURE_FLAGS["max_hub_clients"],
        "active_hub_tokens": active_hub_token_count(),
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
    allowlist = Path(args.allowlist).expanduser() if getattr(args, "allowlist", "") else unlimited_skills_home() / "hub" / "hub-allowlist.v1.json"
    if not allowlist.is_file():
        raise RuntimeError(f"Local Skill Hub allowlist is required: {allowlist}")
    ensure_lan_bind_allowed(str(args.host), allow_lan=bool(getattr(args, "allow_lan", False)))
    try:
        import uvicorn  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install server dependencies with: pip install 'unlimited-skills[server]'") from exc
    import os

    os.environ["UNLIMITED_SKILLS_ROOT"] = str(Path(args.root).expanduser())
    os.environ["UNLIMITED_SKILLS_HUB_ALLOWLIST"] = str(allowlist)
    uvicorn.run("unlimited_skills.hub_server:create_app", host=args.host, port=args.port, log_level=args.log_level, factory=True)
    return 0


def cmd_hub_clients(args: Any) -> int:
    ensure_hub_registered()
    return emit_json({"schema_version": 1, "clients": [], "count": 0, "active_client_limit": HUB_FEATURE_FLAGS["max_hub_clients"]})


def cmd_hub_token_create(args: Any) -> int:
    ensure_hub_registered()
    result = create_hub_token(getattr(args, "label", "") or "default")
    record = result["record"]
    payload = {
        "schema_version": 1,
        "token_id": record["token_id"],
        "label": record["label"],
        "created_at": record["created_at"],
        "token": result["raw_token"],
        "message": "Store this token now. It will not be shown again.",
    }
    if getattr(args, "json", False):
        return emit_json(payload)
    print("Created Local Skill Hub client token.")
    print(f"Token ID: {payload['token_id']}")
    print(f"Label: {payload['label']}")
    print("Raw token (shown once):")
    print(payload["token"])
    return 0


def cmd_hub_token_list(args: Any) -> int:
    ensure_hub_registered()
    tokens = list_hub_tokens()
    payload = {"schema_version": 1, "tokens": tokens, "count": len(tokens), "active_count": len([token for token in tokens if not token["revoked"]])}
    if getattr(args, "json", False):
        return emit_json(payload)
    if not tokens:
        print("No Local Skill Hub client tokens.")
        return 0
    for token in tokens:
        print(
            f"{token['token_id']} label={token['label']} revoked={str(token['revoked']).lower()} "
            f"created_at={token['created_at']} last_used_at={token['last_used_at'] or '<never>'}"
        )
    return 0


def cmd_hub_token_revoke(args: Any) -> int:
    ensure_hub_registered()
    token = revoke_hub_token(args.token_id)
    payload = {"schema_version": 1, "token": token}
    if getattr(args, "json", False):
        return emit_json(payload)
    print(f"Revoked Local Skill Hub client token: {token['token_id']}")
    return 0


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


def redacted_runtime_error(exc: RuntimeError) -> str:
    return redact_sensitive_text(str(exc))
