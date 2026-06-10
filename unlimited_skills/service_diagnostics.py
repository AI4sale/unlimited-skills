from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__
from .registration import (
    DEFAULT_SERVICE_URL,
    RegistrationState,
    build_registration_payload,
    is_secure_or_local_url,
    load_registration,
    proof_headers,
    redact_sensitive_text,
    unlimited_skills_home,
    with_install_identity,
)
from .signatures import key_record_allows, normalize_registry_origin, trusted_manifest_key_records

SERVICE_CONFIG_NAME = "service.json"
REQUIRED_KEY_SCOPES = (
    "hub-allowlist",
    "catalog-updates",
    "enhancement-manifest",
    "team-sync-manifest",
    "release-channels",
)
FORBIDDEN_DIAGNOSTIC_FIELDS = (
    "skill_bodies",
    "skill_names",
    "prompts",
    "search_queries",
    "local_paths",
    "repo_paths",
    "env_values",
    "tokens",
    "private_keys",
)


class ServiceDiagnosticError(RuntimeError):
    """Raised when service onboarding diagnostics cannot be completed safely."""


def service_config_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / SERVICE_CONFIG_NAME


def _now_service_payload() -> dict[str, Any]:
    return {"schema_version": 1, "client": {"name": "unlimited-skills", "version": __version__}}


def normalize_service_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        raise ServiceDiagnosticError("Service URL must include scheme and host, for example https://unlimited.ai4.sale.")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "")).rstrip("/")


def _is_localhost_http(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "http" and (host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost"))


def validate_service_url(url: str, *, allow_insecure_localhost: bool = False) -> str:
    normalized = normalize_service_url(url)
    parsed = urllib.parse.urlsplit(normalized)
    if parsed.scheme == "https":
        return normalized
    if _is_localhost_http(normalized):
        if allow_insecure_localhost:
            return normalized
        raise ServiceDiagnosticError("Plain HTTP localhost service URLs require --allow-insecure-localhost.")
    raise ServiceDiagnosticError("Service URL must use HTTPS. Plain HTTP is allowed only for explicit localhost diagnostics.")


def load_service_config(home: Path | None = None) -> dict[str, Any]:
    path = service_config_path(home)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServiceDiagnosticError("Cannot read local service configuration.") from exc
    if not isinstance(payload, dict):
        raise ServiceDiagnosticError("Local service configuration must be a JSON object.")
    return payload


def configured_service_url(state: RegistrationState | None = None, *, home: Path | None = None) -> str:
    config = load_service_config(home)
    configured = str(config.get("service_url") or "")
    if configured:
        return normalize_service_url(configured)
    state = state or load_registration(home)
    return normalize_service_url(state.server_url or DEFAULT_SERVICE_URL)


def configure_service(url: str, *, allow_insecure_localhost: bool = False, home: Path | None = None) -> dict[str, Any]:
    normalized = validate_service_url(url, allow_insecure_localhost=allow_insecure_localhost)
    from .policy_enforcement import enforce_registry_url

    enforce_registry_url(normalized, action="service configure", home=home)
    path = service_config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "service_url": normalized,
        "configured_by": "unlimited-skills service configure",
    }
    from .registration import write_private_json

    write_private_json(path, payload)
    return {
        **_now_service_payload(),
        "configured": True,
        "service_url": normalized,
        "stored": True,
        "stored_path": "private service configuration",
        "insecure_localhost": _is_localhost_http(normalized),
    }


def _public_registration_status(state: RegistrationState) -> dict[str, Any]:
    return {
        "registered": state.registered,
        "install_id": state.install_id or "",
        "plan": state.plan or "community-core",
        "telemetry": state.telemetry,
        "hosted_credential": "present" if state.license_token else "missing",
        "device_key": "present" if state.device_private_key else "missing",
        "device_public_identity": "present" if state.device_public_key else "missing",
        "key_thumbprint": state.key_thumbprint,
        "proof_required": state.proof_required,
        "features_enabled": list(state.features_enabled),
    }


def local_status(*, refresh: bool = False, timeout: float = 10.0, home: Path | None = None) -> dict[str, Any]:
    state = load_registration(home)
    service_url = configured_service_url(state, home=home)
    payload: dict[str, Any] = {
        **_now_service_payload(),
        "service_url": service_url,
        "service_config": "present" if service_config_path(home).is_file() else "missing",
        "registration": _public_registration_status(state),
        "trust": local_trust_status(service_url),
        "network": {"performed": False, "endpoints_contacted": []},
    }
    if refresh:
        payload["network"] = {"performed": True, **doctor(service_url=service_url, timeout=timeout, home=home)}
    return payload


def service_health_snapshot(*, refresh: bool = False, timeout: float = 10.0, home: Path | None = None) -> dict[str, Any]:
    """Build the shared setup/support service diagnostic snapshot.

    The default is local-only. Callers must pass refresh=True to contact the
    configured service health and public-key endpoints.
    """
    status = local_status(refresh=refresh, timeout=timeout, home=home)
    registration = status.get("registration") if isinstance(status.get("registration"), dict) else {}
    trust = status.get("trust") if isinstance(status.get("trust"), dict) else {}
    network = status.get("network") if isinstance(status.get("network"), dict) else {"performed": False, "endpoints_contacted": []}
    registered = bool(registration.get("registered"))
    credential_present = registration.get("hosted_credential") == "present"
    device_identity_present = registration.get("device_key") == "present" and registration.get("device_public_identity") == "present"
    compatible_key_count = int(trust.get("compatible_key_count") or 0)
    service_configured = status.get("service_config") == "present"
    checks = {
        "service_configured": service_configured,
        "registered": registered,
        "hosted_credential_present": credential_present,
        "device_identity_present": device_identity_present,
        "trusted_manifest_keys_compatible": compatible_key_count > 0,
        "network_refresh_performed": bool(network.get("performed")),
    }
    next_commands: list[str] = []
    if not service_configured:
        next_commands.append("unlimited-skills service configure https://unlimited.ai4.sale")
    if not registered:
        next_commands.extend(
            [
                "unlimited-skills service test-registration --dry-run --agent codex",
                "unlimited-skills register --agent codex",
            ]
        )
    if compatible_key_count <= 0:
        next_commands.extend(["unlimited-skills trust status", "unlimited-skills service verify-trust"])
    if not device_identity_present:
        next_commands.append("unlimited-skills service test-proof")
    if not refresh:
        next_commands.append("unlimited-skills service doctor")
    ready = all(
        checks[key]
        for key in (
            "service_configured",
            "registered",
            "hosted_credential_present",
            "device_identity_present",
            "trusted_manifest_keys_compatible",
        )
    )
    return {
        **_now_service_payload(),
        "snapshot_version": 2,
        "status": "ok" if ready else "needs_action",
        "service_url": status.get("service_url", ""),
        "registration": {
            "registered": registered,
            "plan": registration.get("plan", "community-core"),
            "hosted_credential": registration.get("hosted_credential", "missing"),
            "device_identity": "present" if device_identity_present else "missing",
            "features_enabled": list(registration.get("features_enabled", [])),
        },
        "trust": {
            "compatible_key_count": compatible_key_count,
            "compatible_key_ids": list(trust.get("compatible_key_ids", [])),
            "required_scopes": list(trust.get("required_scopes", REQUIRED_KEY_SCOPES)),
            "registry_origin": trust.get("registry_origin", ""),
        },
        "network": {
            "performed": bool(network.get("performed")),
            "endpoints_contacted": list(network.get("endpoints_contacted", [])),
        },
        "checks": checks,
        "next_commands": list(dict.fromkeys(next_commands)),
        "privacy": {
            "uploads_local_data": False,
            "uploads_skill_bodies": False,
            "uploads_skill_names": False,
            "uploads_prompts": False,
            "uploads_local_paths": False,
            "tokens_redacted": True,
            "private_keys_redacted": True,
        },
    }


def local_trust_status(service_url: str) -> dict[str, Any]:
    records = trusted_manifest_key_records()
    compatible = [
        {
            "key_id": str(record.get("key_id") or ""),
            "source": str(record.get("source") or ""),
            "scopes": [str(item) for item in record.get("scopes", [])],
        }
        for record in records
        if any(key_record_allows(record, scope=scope, registry_url=service_url) for scope in REQUIRED_KEY_SCOPES)
    ]
    return {
        "trusted_key_count": len(records),
        "compatible_key_count": len(compatible),
        "compatible_key_ids": [item["key_id"] for item in compatible if item["key_id"]],
        "required_scopes": list(REQUIRED_KEY_SCOPES),
        "registry_origin": normalize_registry_origin(service_url),
    }


def _get_json(url: str, *, timeout: float = 10.0, optional: bool = False, summarize: bool = True) -> dict[str, Any]:
    if not is_secure_or_local_url(url):
        raise ServiceDiagnosticError("Service diagnostics require HTTPS, except explicit localhost diagnostics.")
    request = urllib.request.Request(url, headers={"User-Agent": f"unlimited-skills/{__version__}"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        if optional and exc.code == 404:
            return {"ok": False, "available": False, "status": 404, "error": "not_available"}
        return {"ok": False, "available": False, "status": exc.code, "error": redact_sensitive_text(body)}
    except urllib.error.URLError as exc:
        return {"ok": False, "available": False, "status": 0, "error": redact_sensitive_text(exc.reason)}
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "available": True, "status": status, "error": "invalid_json"}
    if not isinstance(payload, dict):
        return {"ok": False, "available": True, "status": status, "error": "non_object_json"}
    return {
        "ok": 200 <= status < 300,
        "available": True,
        "status": status,
        "payload": _summarize_payload(payload) if summarize else payload,
    }


def _summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("schema_version", "status", "ok", "ready", "distribution_mode", "full_catalog_distribution_allowed"):
        if key in payload:
            summary[key] = payload[key]
    if "keys" in payload and isinstance(payload["keys"], list):
        summary["key_count"] = len(payload["keys"])
        summary["key_ids"] = [str(item.get("key_id") or "") for item in payload["keys"] if isinstance(item, dict) and item.get("key_id")]
    return summary


def fetch_public_keys(service_url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    endpoint = f"{service_url.rstrip('/')}/v1/public-keys"
    result = _get_json(endpoint, timeout=timeout, summarize=False)
    if not result.get("ok"):
        raise ServiceDiagnosticError(f"Cannot fetch service public keys: {result.get('error') or result.get('status')}")
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    return payload


def verify_trust(*, service_url: str | None = None, timeout: float = 10.0, home: Path | None = None) -> dict[str, Any]:
    state = load_registration(home)
    resolved_url = validate_service_url(service_url or configured_service_url(state, home=home), allow_insecure_localhost=True)
    endpoint = f"{resolved_url}/v1/public-keys"
    remote = fetch_public_keys(resolved_url, timeout=timeout)
    return _trust_report(resolved_url, remote, [endpoint])


def _trust_report(resolved_url: str, remote: dict[str, Any], endpoints_contacted: list[str]) -> dict[str, Any]:
    remote_keys = [item for item in remote.get("keys", []) if isinstance(item, dict)]
    local_records = trusted_manifest_key_records(include_public=True)
    local_by_id = {str(item.get("key_id") or ""): item for item in local_records}
    matches: list[dict[str, Any]] = []
    for key in remote_keys:
        key_id = str(key.get("key_id") or "")
        local = local_by_id.get(key_id)
        if not local:
            matches.append({"key_id": key_id, "trusted": False, "reason": "missing_local_trust"})
            continue
        scopes = [scope for scope in REQUIRED_KEY_SCOPES if key_record_allows(local, scope=scope, registry_url=resolved_url)]
        matches.append({"key_id": key_id, "trusted": bool(scopes), "compatible_scopes": scopes})
    trusted = [item for item in matches if item.get("trusted")]
    return {
        **_now_service_payload(),
        "service_url": resolved_url,
        "endpoints_contacted": endpoints_contacted,
        "remote_key_count": len(remote_keys),
        "local_trust_key_count": len(local_records),
        "required_scopes": list(REQUIRED_KEY_SCOPES),
        "trusted_remote_key_ids": [str(item["key_id"]) for item in trusted],
        "matches": matches,
        "signed_manifest_compatibility": {
            "compatible": bool(trusted),
            "registry_origin": normalize_registry_origin(resolved_url),
        },
    }


def doctor(*, service_url: str | None = None, timeout: float = 10.0, home: Path | None = None) -> dict[str, Any]:
    state = load_registration(home)
    resolved_url = validate_service_url(service_url or configured_service_url(state, home=home), allow_insecure_localhost=True)
    endpoints = [f"{resolved_url}/health", f"{resolved_url}/ready", f"{resolved_url}/v1/public-keys"]
    health = _get_json(endpoints[0], timeout=timeout)
    ready = _get_json(endpoints[1], timeout=timeout, optional=True)
    public_keys_raw = _get_json(endpoints[2], timeout=timeout, summarize=False)
    public_keys_public = dict(public_keys_raw)
    if isinstance(public_keys_public.get("payload"), dict):
        public_keys_public["payload"] = _summarize_payload(public_keys_public["payload"])
    checks = {
        "service_url": {"ok": True, "value": resolved_url, "https": urllib.parse.urlsplit(resolved_url).scheme == "https", "localhost": _is_localhost_http(resolved_url)},
        "health": health,
        "ready": ready,
        "public_keys": public_keys_public,
        "local_trust_store": local_trust_status(resolved_url),
        "registration_state": _public_registration_status(state),
        "device_proof_generation": test_proof(home=home, service_url=resolved_url),
    }
    trust = (
        _trust_report(resolved_url, public_keys_raw.get("payload", {}) if isinstance(public_keys_raw.get("payload"), dict) else {}, [endpoints[2]])
        if checks["public_keys"].get("ok")
        else {"signed_manifest_compatibility": {"compatible": False}}
    )
    checks["signed_manifest_compatibility"] = trust["signed_manifest_compatibility"]
    ok = bool(checks["health"].get("ok") and checks["public_keys"].get("ok") and checks["signed_manifest_compatibility"].get("compatible"))
    return {
        **_now_service_payload(),
        "service_url": resolved_url,
        "ok": ok,
        "privacy": {
            "uploads_local_data": False,
            "forbidden_fields": list(FORBIDDEN_DIAGNOSTIC_FIELDS),
            "methods_used": ["GET"],
        },
        "endpoints_contacted": endpoints,
        "checks": checks,
    }


def registration_dry_run(*, service_url: str | None = None, agent: str = "", telemetry: str = "off", home: Path | None = None) -> dict[str, Any]:
    resolved_url = validate_service_url(service_url or configured_service_url(home=home), allow_insecure_localhost=True)
    state = with_install_identity(load_registration(home), resolved_url)
    payload = build_registration_payload(state, agent=agent, skill_count=0, telemetry=telemetry)
    redacted_payload = dict(payload)
    redacted_payload["public_key"] = "present"
    return {
        **_now_service_payload(),
        "service_url": state.server_url,
        "endpoint": f"{state.server_url.rstrip('/')}/v1/installations/register",
        "would_send": False,
        "dry_run": True,
        "payload": redacted_payload,
        "privacy": {
            "sends_skill_bodies": False,
            "sends_skill_names": False,
            "sends_prompts": False,
            "sends_local_paths": False,
            "sends_tokens": False,
            "sends_device_secrets": False,
        },
    }


def test_proof(*, home: Path | None = None, service_url: str | None = None) -> dict[str, Any]:
    state = load_registration(home)
    resolved_url = validate_service_url(service_url or configured_service_url(state, home=home), allow_insecure_localhost=True)
    body = b'{"diagnostic":true}'
    headers = proof_headers(state, "POST", f"{resolved_url.rstrip('/')}/v1/diagnostic-proof", body)
    return {
        **_now_service_payload(),
        "generated": bool(headers.get("X-ULS-Proof")),
        "install_id": state.install_id,
        "key_thumbprint": state.key_thumbprint,
        "request": {"method": "POST", "path": "/v1/diagnostic-proof", "body_sha256_only": True},
        "headers": {"X-ULS-Proof": "present" if headers.get("X-ULS-Proof") else "missing"},
        "proof_value": "[redacted]" if headers.get("X-ULS-Proof") else "",
    }


def assert_service_diagnostics_do_not_contain_forbidden_fields(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    forbidden_values = ["skilL.md".lower(), "device_private_key", "license_token", "authorization", "bearer "]
    for value in forbidden_values:
        if value in serialized:
            raise ServiceDiagnosticError(f"Service diagnostic output contains forbidden field/value: {value}")
