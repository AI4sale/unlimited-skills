from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .registration import base64_urlsafe_decode, base64_urlsafe_encode


SIGNATURE_FIELDS = {"manifest_signature", "signature_envelope"}
PUBLIC_KEYS_ENV = "UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"
REQUIRE_SIGNATURES_ENV = "UNLIMITED_SKILLS_REQUIRE_SIGNED_MANIFESTS"


class ManifestSignatureError(RuntimeError):
    """Raised when a hosted manifest signature is missing, untrusted, or invalid."""


def canonical_manifest_bytes(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key not in SIGNATURE_FIELDS}
    return json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def manifest_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_manifest_bytes(payload)).hexdigest()


def trusted_manifest_public_keys(value: str | None = None) -> dict[str, bytes]:
    raw = value if value is not None else os.environ.get(PUBLIC_KEYS_ENV, "")
    keys: dict[str, bytes] = {}
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
            keys[key_id] = base64_urlsafe_decode(public_key.strip())
        except Exception as exc:
            raise ManifestSignatureError(f"Trusted manifest public key is invalid: {key_id}") from exc
    return keys


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
) -> dict[str, Any]:
    envelope = signature_envelope(payload)
    if not envelope:
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

    actual_sha = manifest_sha256(payload)
    if expected_sha and expected_sha.lower() != actual_sha.lower():
        raise ManifestSignatureError(f"{purpose} signed_payload_sha256 mismatch: expected {expected_sha}, got {actual_sha}")

    keys = public_keys if public_keys is not None else trusted_manifest_public_keys()
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
    }


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
