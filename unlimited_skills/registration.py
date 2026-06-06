from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__

DEFAULT_SERVICE_URL = os.environ.get("UNLIMITED_SKILLS_SERVICE_URL", "https://unlimited.ai4.sale")
REGISTRATION_NAME = "registration.json"


class RegistrationError(RuntimeError):
    """Raised when registration state or the registration service is unavailable."""


def unlimited_skills_home() -> Path:
    return Path(os.environ.get("UNLIMITED_SKILLS_HOME", Path.home() / ".unlimited-skills")).expanduser()


def registration_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / REGISTRATION_NAME


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_install_id() -> str:
    return "uls_inst_" + secrets.token_urlsafe(24)


def email_hash(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RegistrationState:
    schema_version: int = 1
    install_id: str = ""
    server_url: str = DEFAULT_SERVICE_URL
    plan: str = ""
    license_token: str = ""
    telemetry: str = "off"
    registered_email_hash: str = ""
    registered_at: str = ""
    last_checked_at: str = ""
    features_enabled: tuple[str, ...] = ()

    @property
    def registered(self) -> bool:
        return bool(self.install_id and self.license_token)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "install_id": self.install_id,
            "server_url": self.server_url,
            "plan": self.plan,
            "license_token": self.license_token,
            "telemetry": self.telemetry,
            "registered_email_hash": self.registered_email_hash,
            "registered_at": self.registered_at,
            "last_checked_at": self.last_checked_at,
            "features_enabled": list(self.features_enabled),
        }


def state_from_json(data: dict[str, Any] | None) -> RegistrationState:
    data = data or {}
    features = data.get("features_enabled") or ()
    if not isinstance(features, (list, tuple)):
        features = ()
    return RegistrationState(
        schema_version=int(data.get("schema_version") or 1),
        install_id=str(data.get("install_id") or ""),
        server_url=str(data.get("server_url") or DEFAULT_SERVICE_URL),
        plan=str(data.get("plan") or ""),
        license_token=str(data.get("license_token") or ""),
        telemetry=str(data.get("telemetry") or "off"),
        registered_email_hash=str(data.get("registered_email_hash") or ""),
        registered_at=str(data.get("registered_at") or ""),
        last_checked_at=str(data.get("last_checked_at") or ""),
        features_enabled=tuple(str(item) for item in features),
    )


def load_registration(home: Path | None = None) -> RegistrationState:
    path = registration_path(home)
    if not path.exists():
        return RegistrationState()
    try:
        return state_from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistrationError(f"Cannot read registration file: {path}") from exc


def save_registration(state: RegistrationState, home: Path | None = None) -> Path:
    path = registration_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def with_install_id(state: RegistrationState, server_url: str = "") -> RegistrationState:
    return RegistrationState(
        schema_version=state.schema_version,
        install_id=state.install_id or new_install_id(),
        server_url=(server_url or state.server_url or DEFAULT_SERVICE_URL).rstrip("/"),
        plan=state.plan,
        license_token=state.license_token,
        telemetry=state.telemetry,
        registered_email_hash=state.registered_email_hash,
        registered_at=state.registered_at,
        last_checked_at=state.last_checked_at,
        features_enabled=state.features_enabled,
    )


def count_bucket(count: int) -> str:
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


def build_registration_payload(
    state: RegistrationState,
    registration_key: str,
    *,
    agent: str = "",
    skill_count: int = 0,
    telemetry: str = "off",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "install_id": state.install_id,
        "registration_key": registration_key,
        "client": {
            "name": "unlimited-skills",
            "version": __version__,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "os": platform.system().lower(),
        },
        "agent": agent,
        "skill_count_bucket": count_bucket(skill_count),
        "telemetry": telemetry == "on",
    }


def post_json(url: str, payload: dict[str, Any], *, token: str = "", timeout: float = 30.0) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "User-Agent": f"unlimited-skills/{__version__}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RegistrationError(f"Registration service returned HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise RegistrationError(f"Registration service is unreachable: {exc.reason}") from exc
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise RegistrationError("Registration service returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise RegistrationError("Registration service returned a non-object JSON payload.")
    return data


def register_installation(
    state: RegistrationState,
    registration_key: str,
    *,
    server_url: str = "",
    agent: str = "",
    skill_count: int = 0,
    email: str = "",
    telemetry: str = "off",
    timeout: float = 30.0,
) -> RegistrationState:
    state = with_install_id(state, server_url)
    payload = build_registration_payload(state, registration_key, agent=agent, skill_count=skill_count, telemetry=telemetry)
    response = post_json(f"{state.server_url}/v1/installations/register", payload, timeout=timeout)
    token = str(response.get("license_token") or response.get("token") or "")
    if not token:
        raise RegistrationError("Registration service did not return a license token.")
    features = response.get("features_enabled") or ["hosted_catalog", "collection_updates"]
    if not isinstance(features, (list, tuple)):
        features = ["hosted_catalog", "collection_updates"]
    return RegistrationState(
        install_id=state.install_id,
        server_url=state.server_url,
        plan=str(response.get("plan") or "registered-community"),
        license_token=token,
        telemetry="on" if telemetry == "on" else "off",
        registered_email_hash=email_hash(email),
        registered_at=str(response.get("registered_at") or now_iso()),
        last_checked_at=now_iso(),
        features_enabled=tuple(str(item) for item in features),
    )


def redacted_status(state: RegistrationState) -> dict[str, Any]:
    return {
        "registered": state.registered,
        "install_id": state.install_id,
        "server_url": state.server_url,
        "plan": state.plan or "community-core",
        "telemetry": state.telemetry,
        "features_enabled": list(state.features_enabled),
        "registered_at": state.registered_at,
        "last_checked_at": state.last_checked_at,
        "license_token": "present" if state.license_token else "",
    }


def set_telemetry(state: RegistrationState, mode: str) -> RegistrationState:
    if mode not in {"on", "off"}:
        raise RegistrationError("Telemetry mode must be 'on' or 'off'.")
    return RegistrationState(
        schema_version=state.schema_version,
        install_id=state.install_id,
        server_url=state.server_url,
        plan=state.plan,
        license_token=state.license_token,
        telemetry=mode,
        registered_email_hash=state.registered_email_hash,
        registered_at=state.registered_at,
        last_checked_at=state.last_checked_at,
        features_enabled=state.features_enabled,
    )
