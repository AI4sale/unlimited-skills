from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import __version__
from .registration import RegistrationError, RegistrationState, load_registration, post_json, redact_sensitive_text, unlimited_skills_home, write_private_json
from .team import TeamState, load_team_state, redacted_team_status


ORG_STATUS_NAME = "org-status.json"


class OrgStatusError(RuntimeError):
    """Raised when organization status cannot be loaded or refreshed."""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def org_status_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / ORG_STATUS_NAME


def load_cached_org_status(home: Path | None = None) -> dict[str, Any]:
    path = org_status_path(home)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrgStatusError(f"Cannot read organization status cache: {path}") from exc
    if not isinstance(payload, dict):
        raise OrgStatusError(f"Organization status cache must be a JSON object: {path}")
    return sanitize_org_status(payload)


def save_org_status(payload: dict[str, Any], home: Path | None = None) -> Path:
    return write_private_json(org_status_path(home), sanitize_org_status(payload))


def local_org_status(
    registration: RegistrationState | None = None,
    team: TeamState | None = None,
    *,
    cached: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registration = registration or load_registration()
    team = team or load_team_state()
    cached = cached if cached is not None else load_cached_org_status()
    organization = cached.get("organization") if isinstance(cached.get("organization"), dict) else {}
    entitlements = cached.get("entitlements") if isinstance(cached.get("entitlements"), dict) else {}
    payload = {
        "schema_version": 1,
        "source": "cache" if cached else "local",
        "registered": registration.registered,
        "refreshed": False,
        "last_refreshed_at": str(cached.get("last_refreshed_at") or ""),
        "server_url": registration.server_url,
        "plan": registration.plan or str(cached.get("plan") or "community-core"),
        "organization": {
            "org_id": str(organization.get("org_id") or organization.get("id") or ""),
            "name": str(organization.get("name") or ""),
            "role": str(organization.get("role") or "none"),
            "status": str(organization.get("status") or "unknown"),
        },
        "team": redacted_team_status(team, registration),
        "entitlements": {
            "private_packs": _entitlement_state(entitlements.get("private_packs")),
            "community_catalog": _entitlement_state(entitlements.get("community_catalog")),
            "team_sync": _entitlement_state(entitlements.get("team_sync")),
        },
        "recommendations": _recommendations(registration, bool(cached)),
        "privacy": _privacy_flags(),
    }
    return sanitize_org_status(payload)


def refresh_org_status(registration: RegistrationState | None = None, team: TeamState | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
    registration = registration or load_registration()
    if not registration.registered:
        raise OrgStatusError("Registration is required for hosted organization status. Run: unlimited-skills register")
    team = team or load_team_state()
    client = OrgStatusClient(registration, timeout=timeout)
    payload = client.status(team)
    payload["refreshed"] = True
    payload["source"] = "hosted"
    payload["last_refreshed_at"] = str(payload.get("last_refreshed_at") or now_iso())
    payload.setdefault("registered", True)
    payload.setdefault("server_url", registration.server_url)
    payload.setdefault("plan", registration.plan or "registered-community")
    payload.setdefault("team", redacted_team_status(team, registration))
    payload.setdefault("privacy", _privacy_flags())
    save_org_status(payload)
    return sanitize_org_status(payload)


class OrgStatusClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0) -> None:
        if not state.registered:
            raise OrgStatusError("Registration is required for hosted organization status. Run: unlimited-skills register")
        self.state = state
        self.timeout = timeout

    def status(self, team: TeamState) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": {"name": "unlimited-skills", "version": __version__},
            "team_id": team.team_id,
        }
        try:
            response = post_json(
                f"{self.state.server_url.rstrip('/')}/v1/org/status",
                payload,
                token=self.state.license_token,
                proof_state=self.state,
                timeout=self.timeout,
                retry_safe=True,
            )
        except RegistrationError as exc:
            raise OrgStatusError(redact_sensitive_text(exc)) from exc
        if not isinstance(response, dict):
            raise OrgStatusError("Organization status service returned an invalid payload.")
        return response


def sanitize_org_status(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = _sanitize(payload)
    if not isinstance(sanitized, dict):
        return {}
    sanitized.setdefault("schema_version", 1)
    sanitized.setdefault("privacy", _privacy_flags())
    serialized = json.dumps(sanitized, ensure_ascii=False).lower()
    forbidden = ["authorization", "bearer ", "license_token", "device_private_key", "x-uls-proof", '"archive_url":', '"download_url":', "skill.md"]
    if any(marker in serialized for marker in forbidden):
        raise OrgStatusError("Organization status payload contains sensitive fields.")
    return sanitized


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if any(marker in key_lower for marker in ("token", "proof", "private_key", "archive_url", "download_url")):
                continue
            cleaned[key_text] = _sanitize(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def _entitlement_state(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("status") or value.get("state") or value.get("allowed")
    if isinstance(value, bool):
        return "allowed" if value else "denied"
    text = str(value or "unknown").lower()
    if text in {"allowed", "denied", "disabled", "unknown", "not_available"}:
        return text
    return "unknown"


def _recommendations(registration: RegistrationState, has_cache: bool) -> list[str]:
    recommendations: list[str] = []
    if not registration.registered:
        recommendations.append("Run: unlimited-skills register")
    if registration.registered and not has_cache:
        recommendations.append("Run: unlimited-skills org status --refresh")
    return recommendations


def _privacy_flags() -> dict[str, bool]:
    return {
        "tokens_included": False,
        "proofs_included": False,
        "private_keys_included": False,
        "private_skill_names_included": False,
        "private_pack_names_included": False,
        "archive_urls_included": False,
        "local_paths_included": False,
    }
