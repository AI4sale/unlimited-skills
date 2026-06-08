from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from . import __version__

DEFAULT_SERVICE_URL = os.environ.get("UNLIMITED_SKILLS_SERVICE_URL", "https://unlimited.ai4.sale")
REGISTRATION_NAME = "registration.json"
LOCAL_DEVELOPMENT_HOSTS = {"localhost", "127.0.0.1", "::1"}
SENSITIVE_TEXT_PATTERNS = (
    (re.compile(r"(?i)[\"']?authorization[\"']?\s*[:=]\s*[\"']?bearer\s+[^\s,'\"}]+[\"']?"), "[redacted]"),
    (re.compile(r"(?i)[\"']?x-uls-proof[\"']?\s*[:=]\s*[\"']?[^\s,'\"}]+[\"']?"), "[redacted]"),
    (
        re.compile(
            r"(?i)([\"']?(?:license_token|team_token|member_token|device_private_key|private_key|token)[\"']?\s*[:=]\s*[\"']?)[^\s,'\"}&]+([\"']?)"
        ),
        r"\1[redacted]\2",
    ),
)


class RegistrationError(RuntimeError):
    """Raised when registration state or the registration service is unavailable."""


def unlimited_skills_home() -> Path:
    return Path(os.environ.get("UNLIMITED_SKILLS_HOME", Path.home() / ".unlimited-skills")).expanduser()


def registration_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / REGISTRATION_NAME


def is_secure_or_local_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme == "https":
        return True
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "http" and (host in LOCAL_DEVELOPMENT_HOSTS or host.endswith(".localhost"))


def require_secure_url(url: str, *, purpose: str = "Hosted service") -> None:
    if not is_secure_or_local_url(url):
        raise RegistrationError(f"{purpose} URL must use HTTPS. Plain HTTP is allowed only for localhost development.")


def redact_sensitive_text(value: object) -> str:
    text = str(value)
    for pattern, replacement in SENSITIVE_TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def write_private_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    content = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temp = path.with_name(f".{path.name}.{secrets.token_urlsafe(8)}.tmp")
    fd: int | None = None
    try:
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            handle.write(content)
        os.replace(temp, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    finally:
        if fd is not None:
            os.close(fd)
        temp.unlink(missing_ok=True)
    return path


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_install_id() -> str:
    return "uls_inst_" + secrets.token_urlsafe(24)


def _b64_encode(raw: bytes) -> str:
    return base64_urlsafe_encode(raw)


def base64_urlsafe_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def base64_urlsafe_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def generate_device_keypair() -> tuple[str, str, str]:
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_b64 = _b64_encode(public_raw)
    return _b64_encode(private_raw), public_b64, hashlib.sha256(public_raw).hexdigest()


@dataclass(frozen=True)
class RegistrationState:
    schema_version: int = 1
    install_id: str = ""
    server_url: str = DEFAULT_SERVICE_URL
    plan: str = ""
    license_token: str = ""
    device_private_key: str = ""
    device_public_key: str = ""
    key_thumbprint: str = ""
    proof_required: bool = True
    telemetry: str = "off"
    registered_at: str = ""
    last_checked_at: str = ""
    features_enabled: tuple[str, ...] = ()

    @property
    def registered(self) -> bool:
        return bool(self.install_id and self.license_token and self.device_private_key)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "install_id": self.install_id,
            "server_url": self.server_url,
            "plan": self.plan,
            "license_token": self.license_token,
            "device_private_key": self.device_private_key,
            "device_public_key": self.device_public_key,
            "key_thumbprint": self.key_thumbprint,
            "proof_required": self.proof_required,
            "telemetry": self.telemetry,
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
        device_private_key=str(data.get("device_private_key") or ""),
        device_public_key=str(data.get("device_public_key") or ""),
        key_thumbprint=str(data.get("key_thumbprint") or ""),
        proof_required=bool(data.get("proof_required", True)),
        telemetry=str(data.get("telemetry") or "off"),
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
    return write_private_json(path, state.to_json())


def with_install_id(state: RegistrationState, server_url: str = "") -> RegistrationState:
    return RegistrationState(
        schema_version=state.schema_version,
        install_id=state.install_id or new_install_id(),
        server_url=(server_url or state.server_url or DEFAULT_SERVICE_URL).rstrip("/"),
        plan=state.plan,
        license_token=state.license_token,
        device_private_key=state.device_private_key,
        device_public_key=state.device_public_key,
        key_thumbprint=state.key_thumbprint,
        proof_required=state.proof_required,
        telemetry=state.telemetry,
        registered_at=state.registered_at,
        last_checked_at=state.last_checked_at,
        features_enabled=state.features_enabled,
    )


def with_install_identity(state: RegistrationState, server_url: str = "") -> RegistrationState:
    state = with_install_id(state, server_url)
    if state.device_private_key and state.device_public_key and state.key_thumbprint:
        return state
    private_key, public_key, thumbprint = generate_device_keypair()
    return RegistrationState(
        schema_version=state.schema_version,
        install_id=state.install_id,
        server_url=state.server_url,
        plan=state.plan,
        license_token=state.license_token,
        device_private_key=private_key,
        device_public_key=public_key,
        key_thumbprint=thumbprint,
        proof_required=True,
        telemetry=state.telemetry,
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
    *,
    agent: str = "",
    skill_count: int = 0,
    telemetry: str = "off",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "install_id": state.install_id,
        "public_key": state.device_public_key,
        "key_thumbprint": state.key_thumbprint,
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


def proof_headers(state: RegistrationState, method: str, url: str, body: bytes) -> dict[str, str]:
    if not state.device_private_key or not state.key_thumbprint:
        return {}
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(16)
    body_sha256 = hashlib.sha256(body).hexdigest()
    path = urllib.parse.urlsplit(url).path or "/"
    message = "\n".join([method.upper(), path, body_sha256, timestamp, nonce, state.install_id, state.key_thumbprint])
    private_key = Ed25519PrivateKey.from_private_bytes(base64_urlsafe_decode(state.device_private_key))
    signature = private_key.sign(message.encode("utf-8"))
    proof = {
        "install_id": state.install_id,
        "key_thumbprint": state.key_thumbprint,
        "timestamp": timestamp,
        "nonce": nonce,
        "body_sha256": body_sha256,
        "signature": base64_urlsafe_encode(signature),
    }
    return {"X-ULS-Proof": base64_urlsafe_encode(json.dumps(proof, separators=(",", ":"), sort_keys=True).encode("utf-8"))}


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    token: str = "",
    proof_state: RegistrationState | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    require_secure_url(url)
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": f"unlimited-skills/{__version__}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if token and proof_state:
        headers.update(proof_headers(proof_state, "POST", url, body))
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        message = redact_sensitive_text(exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc))
        raise RegistrationError(f"Registration service returned HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise RegistrationError(f"Registration service is unreachable: {redact_sensitive_text(exc.reason)}") from exc
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise RegistrationError("Registration service returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise RegistrationError("Registration service returned a non-object JSON payload.")
    return data


def register_installation(
    state: RegistrationState,
    *,
    server_url: str = "",
    agent: str = "",
    skill_count: int = 0,
    telemetry: str = "off",
    timeout: float = 30.0,
) -> RegistrationState:
    state = with_install_identity(state, server_url)
    payload = build_registration_payload(state, agent=agent, skill_count=skill_count, telemetry=telemetry)
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
        device_private_key=state.device_private_key,
        device_public_key=state.device_public_key,
        key_thumbprint=str(response.get("key_thumbprint") or state.key_thumbprint),
        proof_required=bool(response.get("proof_required", True)),
        telemetry="on" if telemetry == "on" else "off",
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
        "key_thumbprint": state.key_thumbprint,
        "proof_required": state.proof_required,
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
        device_private_key=state.device_private_key,
        device_public_key=state.device_public_key,
        key_thumbprint=state.key_thumbprint,
        proof_required=state.proof_required,
        telemetry=mode,
        registered_at=state.registered_at,
        last_checked_at=state.last_checked_at,
        features_enabled=state.features_enabled,
    )
