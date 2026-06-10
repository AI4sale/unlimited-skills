from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .registration import base64_urlsafe_decode, base64_urlsafe_encode, unlimited_skills_home, write_private_json


SIGNATURE_FIELDS = {"manifest_signature", "signature_envelope"}
PUBLIC_KEYS_ENV = "UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"
PUBLIC_KEYS_FILE_ENV = "UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS_FILE"
REQUIRE_SIGNATURES_ENV = "UNLIMITED_SKILLS_REQUIRE_SIGNED_MANIFESTS"
REVOKED_KEYS_ENV = "UNLIMITED_SKILLS_REVOKED_MANIFEST_KEY_IDS"
LOCAL_TRUST_FILE = "manifest-public-keys.v1.json"
BUNDLED_TRUSTED_MANIFEST_KEYS = [
    {
        "key_id": "registry-alpha-2026-06",
        "algorithm": "ed25519",
        "public_key": "HkSfNF1lZbdWlXsBrCa7bok-2N64WzvOsujYv2QvlFA",
        "status": "active",
        "source": "bundled",
        "scopes": [
            "hub-allowlist",
            "catalog-updates",
            "catalog-browser-response",
            "catalog-browser-item",
            "catalog-browser-preview",
            "catalog-browser-filters",
            "catalog-quality-status",
            "catalog-eval-status",
            "skill-improvement-status",
            "skill-known-issues",
            "update-recommendations",
            "update-preview",
            "deprecation-status",
            "enhancement-manifest",
            "team-sync-manifest",
            "release-channels",
            "enterprise-policy",
        ],
        "registry_origins": ["https://unlimited.ai4.sale"],
    }
]


class ManifestSignatureError(RuntimeError):
    """Raised when a hosted manifest signature is missing, untrusted, or invalid."""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def trust_store_path(home: Path | None = None) -> Path:
    return (home or unlimited_skills_home()) / "trust" / LOCAL_TRUST_FILE


def normalize_registry_origin(value: str) -> str:
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value.rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def canonical_manifest_bytes(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key not in SIGNATURE_FIELDS}
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def manifest_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_manifest_bytes(payload)).hexdigest()


def _env_key_records(value: str | None = None) -> list[dict[str, Any]]:
    raw = value if value is not None else os.environ.get(PUBLIC_KEYS_ENV, "")
    records: list[dict[str, Any]] = []
    for idx, item in enumerate(part.strip() for part in raw.replace(";", ",").split(",")):
        if not item:
            continue
        if ":" in item:
            key_id, public_key = item.split(":", 1)
            key_id = key_id.strip()
        else:
            public_key = item
            key_id = f"env-{idx + 1}"
        if not key_id:
            raise ManifestSignatureError("Trusted manifest public key entry is missing key_id.")
        try:
            base64_urlsafe_decode(public_key.strip())
        except Exception as exc:
            raise ManifestSignatureError(f"Trusted manifest public key is invalid: {key_id}") from exc
        records.append(
            {
                "key_id": key_id,
                "algorithm": "ed25519",
                "public_key": public_key.strip(),
                "status": "active",
                "source": "env",
                "scopes": ["*"],
                "registry_origins": ["*"],
            }
        )
    return records


def _manifest_key_records(path: Path, *, source: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestSignatureError(f"Trusted manifest public key file is invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise ManifestSignatureError(f"Trusted manifest public key file must contain a JSON object: {path}")
    records = payload.get("keys", [])
    if not isinstance(records, list):
        raise ManifestSignatureError(f"Trusted manifest public key file keys must be a list: {path}")
    normalized: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        public_key = str(item.get("public_key") or "")
        key_id = str(item.get("key_id") or "")
        if not key_id or not public_key:
            continue
        try:
            decoded = base64_urlsafe_decode(public_key)
        except Exception as exc:
            raise ManifestSignatureError(f"Trusted manifest public key is invalid: {key_id}") from exc
        if len(decoded) != 32:
            raise ManifestSignatureError(f"Trusted manifest public key has invalid length: {key_id}")
        normalized.append(
            {
                "key_id": key_id,
                "algorithm": str(item.get("algorithm") or "ed25519").lower(),
                "public_key": public_key,
                "status": str(item.get("status") or "active").lower(),
                "source": source,
                "scopes": [str(scope) for scope in item.get("scopes", ["*"]) if str(scope)],
                "registry_origins": [normalize_registry_origin(str(origin)) for origin in item.get("registry_origins", ["*"]) if str(origin)],
            }
        )
    return normalized


def _revoked_key_ids() -> set[str]:
    values = {item.strip() for item in os.environ.get(REVOKED_KEYS_ENV, "").replace(";", ",").split(",") if item.strip()}
    path = trust_store_path()
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestSignatureError(f"Local trust manifest is invalid: {path}") from exc
        for item in payload.get("keys", []) if isinstance(payload, dict) else []:
            if isinstance(item, dict) and str(item.get("status") or "").lower() == "revoked":
                key_id = str(item.get("key_id") or "")
                if key_id:
                    values.add(key_id)
    return values


def trusted_manifest_key_records(*, include_public: bool = False) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = [dict(item) for item in BUNDLED_TRUSTED_MANIFEST_KEYS]
    records.extend(_manifest_key_records(trust_store_path(), source="local"))
    env_file = os.environ.get(PUBLIC_KEYS_FILE_ENV, "")
    if env_file:
        records.extend(_manifest_key_records(Path(env_file).expanduser(), source="env-file"))
    records.extend(_env_key_records())
    revoked = _revoked_key_ids()
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        key_id = str(record.get("key_id") or "")
        if not key_id:
            continue
        normalized = dict(record)
        normalized["status"] = "revoked" if key_id in revoked else str(normalized.get("status") or "active").lower()
        by_id[key_id] = normalized
    output = []
    for key_id in sorted(by_id):
        record = dict(by_id[key_id])
        if not include_public:
            record.pop("public_key", None)
        output.append(record)
    return output


def trusted_manifest_public_keys(value: str | None = None) -> dict[str, bytes]:
    if value is not None:
        records = _env_key_records(value)
    else:
        records = trusted_manifest_key_records(include_public=True)
    keys: dict[str, bytes] = {}
    for record in records:
        if record.get("status") == "revoked":
            continue
        if record.get("algorithm") != "ed25519":
            continue
        keys[str(record["key_id"])] = base64_urlsafe_decode(str(record["public_key"]))
    return keys


def key_record_allows(record: dict[str, Any], *, scope: str = "", registry_url: str = "") -> bool:
    if record.get("status") == "revoked":
        return False
    if record.get("algorithm") != "ed25519":
        return False
    scopes = set(str(item) for item in record.get("scopes", ["*"]))
    if scope and "*" not in scopes and scope not in scopes:
        return False
    origins = set(str(item) for item in record.get("registry_origins", ["*"]))
    origin = normalize_registry_origin(registry_url)
    if origin and "*" not in origins and origin not in origins:
        return False
    return True


def signature_required(default: bool = False) -> bool:
    value = os.environ.get(REQUIRE_SIGNATURES_ENV, "")
    if not value:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def signature_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("manifest_signature") or payload.get("signature_envelope") or {}
    return raw if isinstance(raw, dict) else {}


def verify_manifest_signature(
    payload: dict[str, Any],
    *,
    purpose: str,
    required: bool = False,
    public_keys: dict[str, bytes] | None = None,
    scope: str = "",
    registry_url: str = "",
) -> dict[str, Any]:
    envelope = signature_envelope(payload)
    if not envelope:
        from .policy_enforcement import enforce_manifest_signature_present

        enforce_manifest_signature_present(False, purpose=purpose)
        if signature_required(required):
            raise ManifestSignatureError(f"{purpose} must include manifest_signature.")
        return {"verified": False, "required": False, "reason": "signature_missing"}

    algorithm = str(envelope.get("algorithm") or "").lower()
    key_id = str(envelope.get("key_id") or "")
    signature = str(envelope.get("signature") or "")
    expected_sha = str(envelope.get("signed_payload_sha256") or "")
    if algorithm != "ed25519":
        raise ManifestSignatureError(f"{purpose} manifest_signature must use algorithm=ed25519.")
    if not key_id or not signature:
        raise ManifestSignatureError(f"{purpose} manifest_signature must include key_id and signature.")
    from .policy_enforcement import enforce_manifest_key

    enforce_manifest_key(key_id, scope=scope, registry_url=registry_url, purpose=purpose)

    actual_sha = manifest_sha256(payload)
    if expected_sha and expected_sha.lower() != actual_sha.lower():
        raise ManifestSignatureError(f"{purpose} signed_payload_sha256 mismatch: expected {expected_sha}, got {actual_sha}")

    if public_keys is not None:
        keys = public_keys
        key_record: dict[str, Any] | None = None
    else:
        records = trusted_manifest_key_records(include_public=True)
        key_record = next((record for record in records if record.get("key_id") == key_id), None)
        if key_record is not None and not key_record_allows(key_record, scope=scope, registry_url=registry_url):
            status = str(key_record.get("status") or "")
            if status == "revoked":
                raise ManifestSignatureError(f"{purpose} manifest signature key is revoked: {key_id}")
            raise ManifestSignatureError(f"{purpose} manifest signature key is not allowed for this scope or registry: {key_id}")
        keys = {
            str(record["key_id"]): base64_urlsafe_decode(str(record["public_key"]))
            for record in records
            if key_record_allows(record, scope=scope, registry_url=registry_url)
        }
    public_key = keys.get(key_id)
    if public_key is None:
        raise ManifestSignatureError(f"{purpose} manifest signature key is not trusted: {key_id}")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(base64_urlsafe_decode(signature), canonical_manifest_bytes(payload))
    except (InvalidSignature, ValueError) as exc:
        raise ManifestSignatureError(f"{purpose} manifest signature verification failed.") from exc
    return {
        "verified": True,
        "required": signature_required(required),
        "algorithm": "ed25519",
        "key_id": key_id,
        "signed_payload_sha256": actual_sha,
        "scope": scope,
        "registry_origin": normalize_registry_origin(registry_url),
    }


def read_local_trust_manifest(home: Path | None = None) -> dict[str, Any]:
    path = trust_store_path(home)
    if not path.is_file():
        return {"schema_version": 1, "generated_at": now_iso(), "keys": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestSignatureError(f"Local trust manifest is invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise ManifestSignatureError(f"Local trust manifest must be a JSON object: {path}")
    payload.setdefault("schema_version", 1)
    payload.setdefault("keys", [])
    return payload


def write_local_trust_manifest(payload: dict[str, Any], home: Path | None = None) -> Path:
    payload = dict(payload)
    payload["schema_version"] = 1
    payload["updated_at"] = now_iso()
    return write_private_json(trust_store_path(home), payload)


def import_local_trust_manifest(source: Path, *, replace: bool = False, home: Path | None = None) -> dict[str, Any]:
    records = _manifest_key_records(source, source="local")
    current = {"schema_version": 1, "keys": []} if replace else read_local_trust_manifest(home)
    existing = {str(item.get("key_id") or ""): item for item in current.get("keys", []) if isinstance(item, dict)}
    for record in records:
        item = dict(record)
        item.pop("source", None)
        existing[str(item["key_id"])] = item
    payload = {"schema_version": 1, "keys": [existing[key] for key in sorted(existing) if key]}
    path = write_local_trust_manifest(payload, home)
    return {"schema_version": 1, "imported_count": len(records), "key_ids": [record["key_id"] for record in records], "path": str(path)}


def revoke_local_trust_key(key_id: str, *, reason: str = "", home: Path | None = None) -> dict[str, Any]:
    if not key_id:
        raise ManifestSignatureError("key_id is required.")
    payload = read_local_trust_manifest(home)
    keys = payload.get("keys", [])
    if not isinstance(keys, list):
        keys = []
    found = False
    for item in keys:
        if isinstance(item, dict) and item.get("key_id") == key_id:
            item["status"] = "revoked"
            if reason:
                item["revocation_reason"] = reason
            found = True
    if not found:
        keys.append({"key_id": key_id, "algorithm": "ed25519", "public_key": "", "status": "revoked", "scopes": [], "registry_origins": [], "revocation_reason": reason})
    payload["keys"] = keys
    path = write_local_trust_manifest(payload, home)
    return {"schema_version": 1, "key_id": key_id, "status": "revoked", "path": str(path)}


def sign_manifest_for_tests(payload: dict[str, Any], private_key: Any, *, key_id: str = "test") -> dict[str, Any]:
    signed = dict(payload)
    signed.pop("manifest_signature", None)
    signed.pop("signature_envelope", None)
    body = canonical_manifest_bytes(signed)
    signed["manifest_signature"] = {
        "schema_version": 1,
        "algorithm": "ed25519",
        "key_id": key_id,
        "signed_payload_sha256": hashlib.sha256(body).hexdigest(),
        "signature": base64_urlsafe_encode(private_key.sign(body)),
    }
    return signed
