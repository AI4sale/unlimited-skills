from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import __version__
from .hub_allowlist import (
    HubAllowlistError,
    allowlist_sha256,
    cache_allowlist,
    cached_allowlist_path,
    cached_allowlist_summary,
    ensure_hub_layout,
    hub_dir,
    validate_allowlist,
    validate_allowlist_file,
)
from .registration import RegistrationState, is_secure_or_local_url, load_registration, post_json, redact_sensitive_text, unlimited_skills_home, write_private_json


HUB_FEATURE_FLAGS = {
    "local_skill_hub": True,
    "max_hub_clients": 100,
    "hub_distribution_mode": "allowlist_only",
}
HUB_DEFAULT_PORT = 8766
REMOTE_CONFIG_NAME = "remote.json"
HUB_CONFIG_NAME = "hub.json"
LEGACY_HUB_CONFIG_NAME = "hub.json"
HUB_REGISTRATION_REQUIRED_MESSAGE = (
    "Registration is required for Local Skill Hub. The MIT local core still works offline. "
    "Use `unlimited-skills serve` for the free local daemon, or run `unlimited-skills register`."
)
HUB_ALLOWLIST_SYNC_REQUIRED_MESSAGE = (
    "Registration is required for Local Skill Hub allowlist sync. The MIT local core still works offline."
)
HUB_ALLOWLIST_MISSING_MESSAGE = (
    "No hub allowlist is configured. Run `unlimited-skills hub init --allowlist <file>` or `unlimited-skills hub sync`."
)
LAN_REFUSAL_MESSAGE = "Refusing to bind Local Skill Hub to a non-localhost address without --allow-lan and an active hub token."
LOCALHOST_HOSTS = {"", "localhost", "127.0.0.1", "::1", "[::1]"}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def hub_config_path(home: Path | None = None) -> Path:
    return hub_dir(home) / HUB_CONFIG_NAME


def legacy_hub_config_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / LEGACY_HUB_CONFIG_NAME


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
        legacy_path = legacy_hub_config_path(home)
        if legacy_path.exists():
            path = legacy_path
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
    ensure_hub_layout(home)
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


def normalize_remote_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Remote hub URL must be an absolute http(s) URL.")
    if parsed.username or parsed.password:
        raise RuntimeError("Remote hub URL must not include embedded credentials.")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def load_remote_config(home: Path | None = None) -> dict[str, Any]:
    path = remote_config_path(home)
    if not path.exists():
        return {
            "schema_version": 1,
            "configured": False,
            "url": "",
            "token_present": False,
            "token_storage": "file",
            "token_env": "",
            "fallback_mode": "local_allowed",
            "timeout_seconds": 10,
            "created_at": "",
            "updated_at": "",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    token_storage = str(data.get("token_storage") or ("env" if data.get("token_env") else "file"))
    token_env = str(data.get("token_env") or "")
    token_present = bool(data.get("token_present") or data.get("token") or token_env)
    return {
        "schema_version": 1,
        "configured": bool(data.get("url")),
        "url": str(data.get("url") or ""),
        "token_present": token_present,
        "token_storage": token_storage,
        "token_env": token_env,
        "fallback_mode": str(data.get("fallback_mode") or "local_allowed"),
        "timeout_seconds": float(data.get("timeout_seconds") or 10),
        "created_at": str(data.get("created_at") or ""),
        "updated_at": str(data.get("updated_at") or ""),
    }


def load_remote_runtime_config(home: Path | None = None) -> dict[str, Any]:
    path = remote_config_path(home)
    if not path.exists():
        return load_remote_config(home)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    visible = load_remote_config(home)
    visible["token"] = str(data.get("token") or "")
    return visible


def save_remote_config(
    url: str,
    *,
    token: str = "",
    token_env: str = "",
    fallback_mode: str = "local_allowed",
    timeout_seconds: float = 10,
    home: Path | None = None,
) -> Path:
    if fallback_mode not in {"local_allowed", "hub_required"}:
        raise RuntimeError("fallback_mode must be local_allowed or hub_required.")
    if token and token_env:
        raise RuntimeError("Use either --token or --token-env, not both.")
    path = remote_config_path(home)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    token_storage = "env" if token_env else "file"
    payload = {
        "schema_version": 1,
        "url": normalize_remote_url(url),
        "token_present": bool(token or token_env),
        "token_storage": token_storage,
        "token_env": token_env,
        "fallback_mode": fallback_mode,
        "timeout_seconds": float(timeout_seconds or 10),
        "created_at": str(existing.get("created_at") or now_iso()),
        "updated_at": now_iso(),
    }
    if token_storage == "file":
        payload["token"] = token or str(existing.get("token") or "")
        payload["token_present"] = bool(payload["token"])
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


def ensure_hub_allowlist_sync_registered() -> RegistrationState:
    state = load_registration()
    if not state.registered:
        raise RuntimeError(HUB_ALLOWLIST_SYNC_REQUIRED_MESSAGE)
    return state


def resolve_hub_allowlist_path(value: str = "") -> Path:
    if value:
        path = Path(value).expanduser()
        if not path.is_file():
            raise RuntimeError(f"Local Skill Hub allowlist is required: {path}")
        validate_allowlist_file(path)
        return path
    path = cached_allowlist_path()
    if not path.is_file():
        raise RuntimeError(HUB_ALLOWLIST_MISSING_MESSAGE)
    validate_allowlist_file(path)
    return path


def download_allowlist_json(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    if not is_secure_or_local_url(url):
        raise RuntimeError("Hub allowlist URL must use HTTPS. Plain HTTP is allowed only for localhost development.")
    request = urllib.request.Request(url, headers={"User-Agent": f"unlimited-skills/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except OSError as exc:
        raise RuntimeError(f"Cannot download hub allowlist: {redact_sensitive_text(exc)}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Hub allowlist download returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Hub allowlist download returned a non-object JSON payload.")
    return data


def fetch_registered_allowlist(state: RegistrationState, *, current_sha: str = "", timeout: float = 30.0) -> tuple[dict[str, Any], dict[str, Any]]:
    hub_config = load_hub_config()
    payload = {
        "schema_version": 1,
        "install_id": state.install_id,
        "client": {"name": "unlimited-skills", "version": __version__},
        "current_allowlist_sha256": current_sha,
        "hub_id": str(hub_config.get("hub_id") or ""),
    }
    response = post_json(
        f"{state.server_url.rstrip('/')}/v1/hub/allowlist",
        payload,
        token=state.license_token,
        proof_state=state,
        timeout=timeout,
    )
    if response.get("schema_version") != 1:
        raise RuntimeError("Hub allowlist service returned unsupported schema_version.")
    if response.get("distribution_mode") != "allowlist_only":
        raise RuntimeError("Hub allowlist service must return distribution_mode=allowlist_only.")
    if response.get("full_catalog_distribution_allowed") is not False:
        raise RuntimeError("Hub allowlist service must keep full_catalog_distribution_allowed=false.")
    if response.get("requires_registration") is not True:
        raise RuntimeError("Hub allowlist service must keep requires_registration=true.")
    if int(response.get("free_active_client_instance_limit") or 0) != HUB_FEATURE_FLAGS["max_hub_clients"]:
        raise RuntimeError("Hub allowlist service returned an invalid free active client limit.")
    if isinstance(response.get("allowlist"), dict):
        allowlist = validate_allowlist(response["allowlist"])
    else:
        allowlist_url = str(response.get("allowlist_url") or "")
        if not allowlist_url:
            raise RuntimeError("Hub allowlist service must return allowlist or allowlist_url.")
        allowlist = validate_allowlist(download_allowlist_json(allowlist_url, timeout=timeout))
    expected_sha = str(response.get("allowlist_sha256") or "")
    actual_sha = allowlist_sha256(allowlist)
    if expected_sha and expected_sha.lower() != actual_sha.lower():
        raise RuntimeError(f"Hub allowlist SHA256 mismatch: expected {expected_sha}, got {actual_sha}")
    return allowlist, response


def emit_json(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_hub_init(args: Any) -> int:
    layout = ensure_hub_layout()
    config = load_hub_config()
    config_path = save_hub_config(config)
    state = load_registration()
    payload = hub_status_payload(state)
    payload["status"] = "initialized"
    payload["message"] = "Local Skill Hub local state initialized."
    payload["config_file"] = str(config_path)
    payload["layout"] = layout
    allowlist_arg = getattr(args, "allowlist", "") or ""
    if allowlist_arg:
        source_path = Path(allowlist_arg).expanduser()
        cached = cache_allowlist(validate_allowlist_file(source_path), source=str(source_path), notes="Cached from explicit local allowlist fixture.")
        payload["allowlist"] = cached["meta"]
        payload["allowlist"]["path"] = cached["allowlist_path"]
    else:
        payload["allowlist"] = cached_allowlist_summary()
    if getattr(args, "json", False):
        return emit_json(payload)
    print("Local Skill Hub local state initialized.")
    print(f"Config: {payload['config_file']}")
    print(f"Hub dir: {layout['hub_dir']}")
    if payload["allowlist"].get("present") or payload["allowlist"].get("path"):
        print(f"Allowlist: {payload['allowlist'].get('path') or payload['allowlist'].get('allowlist_path')}")
    return 0


def cmd_hub_status(args: Any) -> int:
    payload = hub_status_payload()
    payload["allowlist"] = cached_allowlist_summary()
    if getattr(args, "json", False):
        return emit_json(payload)
    print("Local Skill Hub: " + ("registered" if payload["registered"] else "unregistered"))
    print(f"Plan: {payload['plan']}")
    print(f"Distribution: {payload['distribution_mode']} / audit {payload['catalog_audit_verdict']}")
    print(f"Active clients: {payload['active_client_count']}/{payload['active_client_limit']}")
    print("Cached allowlist: " + ("present" if payload["allowlist"]["present"] else "missing"))
    print("Hosted query forwarding: off")
    return 0


def cmd_hub_serve(args: Any) -> int:
    ensure_hub_registered()
    allowlist = resolve_hub_allowlist_path(getattr(args, "allowlist", "") or "")
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
    allowlist = cached_allowlist_summary()
    payload["checks"] = [
        {"name": "registration", "status": "ok" if payload["registered"] else "warn"},
        {"name": "full_catalog_distribution", "status": "ok", "value": False},
        {"name": "hosted_query_forwarding", "status": "ok", "value": False},
        {"name": "cached_allowlist", "status": "ok" if allowlist["present"] else "warn", "value": allowlist["present"]},
    ]
    return emit_json(payload)


def cmd_hub_sync(args: Any) -> int:
    state = ensure_hub_allowlist_sync_registered()
    ensure_hub_layout()
    current = cached_allowlist_summary()
    current_sha = str(current.get("sha256") or "")
    allowlist, response = fetch_registered_allowlist(state, current_sha=current_sha, timeout=getattr(args, "timeout", 30.0))
    actual_sha = allowlist_sha256(allowlist)
    payload = {
        "schema_version": 1,
        "dry_run": bool(getattr(args, "dry_run", False)),
        "distribution_mode": "allowlist_only",
        "catalog_audit_verdict": str(response.get("catalog_audit_verdict") or (allowlist.get("source_audit") or {}).get("verdict") or "YES_WITH_ALLOWLIST"),
        "full_catalog_distribution_allowed": False,
        "requires_registration": True,
        "free_active_client_instance_limit": HUB_FEATURE_FLAGS["max_hub_clients"],
        "previous_allowlist_sha256": current_sha,
        "allowlist_sha256": actual_sha,
        "changed": current_sha != actual_sha,
        "notes": redact_sensitive_text(response.get("notes", "")),
    }
    if not getattr(args, "dry_run", False):
        cached = cache_allowlist(allowlist, source="registered-hub-sync", notes=str(response.get("notes") or ""))
        payload["allowlist_path"] = cached["allowlist_path"]
        payload["allowlist_meta"] = cached["meta"]
    if getattr(args, "json", False):
        return emit_json(payload)
    print("Local Skill Hub allowlist sync " + ("dry run" if payload["dry_run"] else "complete") + ".")
    print(f"Distribution: {payload['distribution_mode']}")
    print(f"Full catalog distribution allowed: {str(payload['full_catalog_distribution_allowed']).lower()}")
    print(f"SHA256: {payload['allowlist_sha256']}")
    if payload.get("allowlist_path"):
        print(f"Cached allowlist: {payload['allowlist_path']}")
    return 0


def cmd_remote_configure(args: Any) -> int:
    path = save_remote_config(
        args.url,
        token=getattr(args, "token", "") or "",
        token_env=getattr(args, "token_env", "") or "",
        fallback_mode=args.fallback_mode,
        timeout_seconds=getattr(args, "timeout", 10),
    )
    payload = load_remote_config()
    payload["config_file"] = str(path)
    if getattr(args, "token", ""):
        payload["warning"] = "Hub token stored locally in remote.json with private file permissions. Prefer --token-env for shared machines."
    return emit_json(payload)


def cmd_remote_status(args: Any) -> int:
    payload = load_remote_config()
    if payload["configured"] and payload["token_present"]:
        from .remote_client import RemoteHubClient, RemoteHubError, RemoteHubUnavailable

        try:
            status = RemoteHubClient().get_status()
            payload["reachable"] = True
            payload["hub_status"] = status
        except RemoteHubUnavailable as exc:
            payload["reachable"] = False
            payload["error"] = redact_sensitive_text(str(exc))
        except RemoteHubError as exc:
            payload["reachable"] = False
            payload["error"] = redact_sensitive_text(str(exc))
    if getattr(args, "json", False):
        return emit_json(payload)
    print("Remote hub: " + ("configured" if payload["configured"] else "not configured"))
    print(f"URL: {payload['url'] or '(none)'}")
    print("Token: " + ("present" if payload["token_present"] else "missing"))
    print(f"Token storage: {payload.get('token_storage') or 'file'}")
    print(f"Fallback: {payload['fallback_mode']}")
    if payload.get("configured") and payload.get("token_present"):
        print("Reachable: " + ("yes" if payload.get("reachable") else "no"))
        if payload.get("error"):
            print(f"Error: {payload['error']}")
    return 0


def remote_client_or_fallback(args: Any):
    from .remote_client import RemoteHubClient, RemoteHubError, RemoteHubUnavailable

    try:
        return RemoteHubClient(), None
    except RemoteHubUnavailable as exc:
        if load_remote_config().get("fallback_mode") == "local_allowed":
            return None, redact_sensitive_text(str(exc))
        raise RuntimeError("Remote hub is required by policy but unavailable.") from exc
    except RemoteHubError:
        raise


def local_search_payload(args: Any) -> dict[str, Any]:
    from .cli import DEFAULT_EMBED_MODEL, emit_hits, hybrid_search, lexical_search, vector_search

    root = Path(args.root).expanduser()
    mode = getattr(args, "mode", "hybrid") or "hybrid"
    limit = int(getattr(args, "limit", 8) or 8)
    collection = getattr(args, "collection", "") or None
    if mode == "lexical":
        hits = lexical_search(root, args.query, limit, collection, fresh=True)
    elif mode == "vector":
        hits = vector_search(root, args.query, limit, DEFAULT_EMBED_MODEL, collection)
    else:
        hits = hybrid_search(root, args.query, limit, DEFAULT_EMBED_MODEL, collection, fresh=True, require_vector=False)
    return {"schema_version": 1, "query": args.query, "results": [asdict(hit) for hit in hits], "fallback": "local_allowed"}


def local_resolve_payload(args: Any) -> dict[str, Any]:
    from .cli import DEFAULT_EMBED_MODEL, hybrid_search, read_text

    root = Path(args.root).expanduser()
    max_skills = int(getattr(args, "max_skills", 2) or 2)
    max_chars = int(getattr(args, "max_chars", 12000) or 12000)
    hits = hybrid_search(root, args.query, max_skills, DEFAULT_EMBED_MODEL, getattr(args, "collection", "") or None, fresh=True, require_vector=False)
    selected = []
    used_chars = 0
    for hit in hits:
        remaining = max(max_chars - used_chars, 0)
        body = read_text(Path(hit.path))[:remaining] if remaining > 0 else ""
        used_chars += len(body)
        selected.append(
            {
                **asdict(hit),
                "confidence": hit.score,
                "skill_kind": "local",
                "hub_behavior": "local_fallback",
                "requires_local_install": False,
                "missing_capabilities": [],
                "warnings": ["Remote hub unavailable; resolved from local fallback."],
                "body": body,
            }
        )
    return {"schema_version": 1, "query": args.query, "selected": selected, "context_budget": {"max_skills": max_skills, "max_chars": max_chars, "used_chars": used_chars}, "fallback": "local_allowed"}


def local_view_payload(args: Any) -> dict[str, Any]:
    from .cli import find_by_name, read_text

    root = Path(args.root).expanduser()
    path = find_by_name(root, args.skill_name)
    if not path:
        raise RuntimeError(f"Skill not found locally during remote fallback: {args.skill_name}")
    return {"schema_version": 1, "skill": {"name": args.skill_name, "body": read_text(path), "path": str(path), "hub_behavior": "local_fallback"}, "fallback": "local_allowed"}


def print_remote_search(payload: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        return emit_json(payload)
    results = payload.get("results", [])
    print(f"Remote results: {len(results)}")
    for item in results:
        print(f"{item.get('name')} [{item.get('collection')}] confidence={item.get('confidence', 0)}")
        if item.get("skill_kind") or item.get("hub_behavior"):
            print(f"  kind={item.get('skill_kind', '')} hub_behavior={item.get('hub_behavior', '')}")
        if item.get("requires_local_install"):
            print("  requires_local_install=true")
    return 0


def print_remote_resolve(payload: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        return emit_json(payload)
    selected = payload.get("selected", [])
    print(f"Remote selected skills: {len(selected)}")
    for item in selected:
        print(f"{item.get('name')} [{item.get('collection')}] confidence={item.get('confidence', 0)}")
        print(f"  kind={item.get('skill_kind', '')} hub_behavior={item.get('hub_behavior', '')} requires_local_install={str(bool(item.get('requires_local_install'))).lower()}")
        if item.get("missing_capabilities"):
            print("  missing_capabilities: " + ", ".join(str(value) for value in item.get("missing_capabilities", [])))
        if item.get("warnings"):
            print("  warnings: " + "; ".join(str(value) for value in item.get("warnings", [])))
        body = str(item.get("body") or "")
        if body:
            print("")
            print(body)
    return 0


def print_remote_view(payload: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        return emit_json(payload)
    skill = payload.get("skill", {})
    body = str(skill.get("body") or "")
    if body:
        print(body)
        return 0
    print(f"{skill.get('name', '')} [{skill.get('collection', '')}]")
    if skill.get("warnings"):
        print("Warnings: " + "; ".join(str(value) for value in skill.get("warnings", [])))
    return 0


def cmd_remote_search(args: Any) -> int:
    from .remote_client import RemoteHubError, RemoteHubUnavailable

    client, fallback_reason = remote_client_or_fallback(args)
    if client is None:
        if not getattr(args, "json", False):
            print("Remote hub unavailable; using local fallback.")
        payload = local_search_payload(args)
        if fallback_reason:
            payload["remote_error"] = fallback_reason
        return print_remote_search(payload, as_json=getattr(args, "json", False))
    try:
        payload = client.search(args.query, limit=args.limit, mode=args.mode, collection=getattr(args, "collection", "") or "")
    except RemoteHubUnavailable as exc:
        if client.config.fallback_mode != "local_allowed":
            raise RuntimeError("Remote hub is required by policy but unavailable.") from exc
        if not getattr(args, "json", False):
            print("Remote hub unavailable; using local fallback.")
        payload = local_search_payload(args)
        payload["remote_error"] = redact_sensitive_text(str(exc))
    except RemoteHubError as exc:
        raise RuntimeError(str(exc)) from exc
    return print_remote_search(payload, as_json=getattr(args, "json", False))


def cmd_remote_resolve(args: Any) -> int:
    from .remote_client import RemoteHubError, RemoteHubUnavailable, collect_client_capabilities

    client, fallback_reason = remote_client_or_fallback(args)
    if client is None:
        if not getattr(args, "json", False):
            print("Remote hub unavailable; using local fallback.")
        payload = local_resolve_payload(args)
        if fallback_reason:
            payload["remote_error"] = fallback_reason
        return print_remote_resolve(payload, as_json=getattr(args, "json", False))
    try:
        capabilities = collect_client_capabilities(getattr(args, "agent", "") or "unknown", getattr(args, "capabilities_json", "") or None)
        budget = {"max_skills": int(args.max_skills), "max_chars": int(args.max_chars)}
        payload = client.resolve(args.query, context_budget=budget, client_capabilities=capabilities)
    except RemoteHubUnavailable as exc:
        if client.config.fallback_mode != "local_allowed":
            raise RuntimeError("Remote hub is required by policy but unavailable.") from exc
        if not getattr(args, "json", False):
            print("Remote hub unavailable; using local fallback.")
        payload = local_resolve_payload(args)
        payload["remote_error"] = redact_sensitive_text(str(exc))
    except RemoteHubError as exc:
        raise RuntimeError(str(exc)) from exc
    return print_remote_resolve(payload, as_json=getattr(args, "json", False))


def cmd_remote_view(args: Any) -> int:
    from .remote_client import RemoteHubError, RemoteHubUnavailable

    client, fallback_reason = remote_client_or_fallback(args)
    if client is None:
        if not getattr(args, "json", False):
            print("Remote hub unavailable; using local fallback.")
        payload = local_view_payload(args)
        if fallback_reason:
            payload["remote_error"] = fallback_reason
        return print_remote_view(payload, as_json=getattr(args, "json", False))
    try:
        payload = client.view(args.skill_name)
    except RemoteHubUnavailable as exc:
        if client.config.fallback_mode != "local_allowed":
            raise RuntimeError("Remote hub is required by policy but unavailable.") from exc
        if not getattr(args, "json", False):
            print("Remote hub unavailable; using local fallback.")
        payload = local_view_payload(args)
        payload["remote_error"] = redact_sensitive_text(str(exc))
    except RemoteHubError as exc:
        raise RuntimeError(str(exc)) from exc
    return print_remote_view(payload, as_json=getattr(args, "json", False))


def redacted_runtime_error(exc: RuntimeError) -> str:
    return redact_sensitive_text(str(exc))
