"""Reference validator for the public Fleet Wire Contract v1.

The JSON schema bundle is the cross-language authority.  This module is the
Python reference implementation used by the local reconciler and golden
fixtures.  It intentionally owns no tenant policy and no private registry
state.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


FLEET_CONTRACT_ID = "unlimited-skills.fleet-wire"
FLEET_CONTRACT_VERSION = 1
FLEET_CONTRACT_BUNDLE_REVISION = 2
DESIRED_STATE_SIGNING_ROLE = "fleet-desired-state-signing"
MAX_MESSAGE_BYTES = 256 * 1024
MAX_ID_CHARS = 160
MAX_ITEMS = 256
ALLOWED_ACTIONS = {"activate", "rollback"}
CLIENT_EVENT_TYPES = {
    "DESIRED_SEEN",
    "MANIFEST_VERIFIED",
    "ARTIFACT_VERIFIED",
    "ARTIFACT_DOWNLOADED",
    "INSTALL_COMMITTED",
    "ACTIVATION_PENDING",
    "RUNTIME_ATTESTED",
    "FAILED_RETRYABLE",
    "FAILED_TERMINAL",
    "REJECTED",
    "DRIFT_DETECTED",
}
SERVER_EVENT_TYPES = {"TARGETED", "VERIFIED_ACTIVE"}
CLIENT_REASON_CODES = {
    "none",
    "activation_pending",
    "adapter_unavailable",
    "artifact_hash_mismatch",
    "desired_state_expired",
    "desired_state_signature_invalid",
    "drift_detected",
    "install_failed",
    "manifest_invalid",
    "manifest_signature_invalid",
    "offline",
    "runtime_attestation_invalid",
    "stale_control_epoch",
    "unsupported_action",
}
SERVER_REASON_CODES = CLIENT_REASON_CODES | {
    "activation_nonce_mismatch",
    "agent_binding_mismatch",
    "invalid_event_sequence",
    "rollout_attempt_mismatch",
    "runtime_generation_mismatch",
    "server_authority_event_forbidden",
    "tenant_mismatch",
    "unsupported_contract_version",
}
ALLOWED_REASON_CODES = SERVER_REASON_CODES

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SIGNATURE_RE = re.compile(r"^[A-Za-z0-9_-]{86}$")
_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
_MANIFEST_REF_PREFIXES = ("https://", "registry:", "urn:")


class FleetContractError(ValueError):
    """Raised when a Fleet Wire Contract message fails closed."""


def _contract_roots() -> tuple[Path, ...]:
    package_root = Path(__file__).resolve().parents[1]
    checkout_root = Path(__file__).resolve().parents[2]
    return (
        checkout_root / "contracts" / "fleet" / "v1",
        package_root / "contracts" / "fleet" / "v1",
    )


def contract_root() -> Path:
    for candidate in _contract_roots():
        if (candidate / "contract-manifest.json").is_file():
            return candidate
    raise FleetContractError("fleet_contract_bundle_missing")


def load_contract_document(relative_path: str) -> dict[str, Any]:
    normalized = str(relative_path or "").replace("\\", "/").strip("/")
    if not normalized or ".." in normalized.split("/"):
        raise FleetContractError("invalid_contract_path")
    path = contract_root() / normalized
    if not path.is_file():
        raise FleetContractError("contract_document_missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FleetContractError("contract_document_invalid") from exc
    if not isinstance(value, dict):
        raise FleetContractError("contract_document_object_required")
    return value


def validate_contract_bundle(root: Path | None = None) -> dict[str, Any]:
    bundle_root = root or contract_root()
    manifest_path = bundle_root / "contract-manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FleetContractError("contract_manifest_invalid") from exc
    if not isinstance(manifest, dict):
        raise FleetContractError("contract_manifest_object_required")
    if manifest.get("contract_id") != FLEET_CONTRACT_ID:
        raise FleetContractError("contract_id_mismatch")
    if manifest.get("major_version") != FLEET_CONTRACT_VERSION:
        raise FleetContractError("contract_major_version_mismatch")
    if (
        manifest.get("bundle_revision")
        != FLEET_CONTRACT_BUNDLE_REVISION
    ):
        raise FleetContractError("contract_bundle_revision_mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise FleetContractError("contract_manifest_files_required")
    verified: list[str] = []
    for relative_path, expected in sorted(files.items()):
        if not isinstance(relative_path, str) or not isinstance(expected, str):
            raise FleetContractError("contract_manifest_file_entry_invalid")
        normalized = relative_path.replace("\\", "/").strip("/")
        if not normalized or ".." in normalized.split("/"):
            raise FleetContractError("invalid_contract_path")
        try:
            payload = (bundle_root / normalized).read_bytes()
        except OSError as exc:
            raise FleetContractError(f"contract_file_missing:{normalized}") from exc
        actual = "sha256:" + hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise FleetContractError(f"contract_file_hash_mismatch:{normalized}")
        verified.append(normalized)
    return {
        "contract_id": FLEET_CONTRACT_ID,
        "major_version": FLEET_CONTRACT_VERSION,
        "bundle_revision": FLEET_CONTRACT_BUNDLE_REVISION,
        "manifest_sha256": "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        "verified_files": verified,
    }


def parse_json_strict(raw: bytes | str) -> dict[str, Any]:
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    if not data or len(data) > MAX_MESSAGE_BYTES:
        raise FleetContractError("invalid_message_size")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise FleetContractError("duplicate_json_property")
            value[key] = item
        return value

    def reject_constant(_: str) -> None:
        raise FleetContractError("invalid_json_constant")

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except FleetContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FleetContractError("invalid_json") from exc
    if not isinstance(value, dict):
        raise FleetContractError("json_object_required")
    return value


def _assert_canonical_value(value: Any, *, path: str = "$") -> None:
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        raise FleetContractError(f"float_not_allowed:{path}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_canonical_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise FleetContractError(f"non_string_key:{path}")
            _assert_canonical_value(item, path=f"{path}.{key}")
        return
    raise FleetContractError(f"unsupported_json_type:{path}")


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    _assert_canonical_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not _ID_RE.fullmatch(value):
        raise FleetContractError(f"invalid_{name}")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise FleetContractError(f"invalid_{name}")
    return value


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise FleetContractError(f"invalid_{name}")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise FleetContractError(f"invalid_{name}") from exc
    if parsed.tzinfo is None:
        raise FleetContractError(f"invalid_{name}")
    return parsed.astimezone(timezone.utc)


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FleetContractError(f"invalid_{name}")
    return value


def _base_fields(payload: Mapping[str, Any], message_type: str) -> None:
    if payload.get("contract_id") != FLEET_CONTRACT_ID:
        raise FleetContractError("contract_id_mismatch")
    if payload.get("contract_version") != FLEET_CONTRACT_VERSION:
        raise FleetContractError("unsupported_contract_version")
    if payload.get("message_type") != message_type:
        raise FleetContractError("message_type_mismatch")
    required_extensions = payload.get("required_extensions", [])
    if required_extensions != []:
        raise FleetContractError("unknown_required_semantic")


def desired_state_digest(payload: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"desired_state_digest", "desired_state_signature"}
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def canonical_desired_state_bytes(payload: Mapping[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "desired_state_signature"}
    return canonical_json_bytes(unsigned)


def validate_desired_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise FleetContractError("desired_state_object_required")
    _base_fields(payload, "desired-state")
    _identifier(payload.get("agent_id"), "agent_id")
    _identifier(payload.get("desired_state_revision"), "desired_state_revision")
    _identifier(payload.get("rollout_id"), "rollout_id")
    _integer(payload.get("control_epoch"), "control_epoch", minimum=1)
    _digest(payload.get("desired_state_digest"), "desired_state_digest")
    _digest(
        payload.get("expected_inventory_digest"),
        "expected_inventory_digest",
    )
    previous_digest = payload.get("previous_digest", "")
    if previous_digest:
        _digest(previous_digest, "previous_digest")
    issued_at = _timestamp(payload.get("issued_at"), "issued_at")
    expires_at = _timestamp(payload.get("expires_at"), "expires_at")
    if expires_at <= issued_at:
        raise FleetContractError("invalid_expiry_window")
    items = payload.get("items")
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        raise FleetContractError("invalid_items")
    pack_ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise FleetContractError(f"invalid_item:{index}")
        _identifier(item.get("attempt_id"), f"items_{index}_attempt_id")
        pack_id = _identifier(item.get("pack_id"), f"items_{index}_pack_id")
        if pack_id in pack_ids:
            raise FleetContractError("duplicate_pack_id")
        pack_ids.add(pack_id)
        _identifier(item.get("release_id"), f"items_{index}_release_id")
        _identifier(item.get("version"), f"items_{index}_version")
        _digest(item.get("archive_sha256"), f"items_{index}_archive_sha256")
        _identifier(
            item.get("activation_nonce"),
            f"items_{index}_activation_nonce",
        )
        action = item.get("action")
        if action not in ALLOWED_ACTIONS:
            raise FleetContractError("unsupported_action")
        if not isinstance(item.get("required"), bool):
            raise FleetContractError(f"invalid_items_{index}_required")
        manifest_ref = item.get("manifest_ref")
        if (
            not isinstance(manifest_ref, str)
            or len(manifest_ref) > 1024
            or not manifest_ref.startswith(_MANIFEST_REF_PREFIXES)
            or "\\" in manifest_ref
            or "\x00" in manifest_ref
        ):
            raise FleetContractError(f"invalid_items_{index}_manifest_ref")
    if desired_state_digest(payload) != payload.get("desired_state_digest"):
        raise FleetContractError("desired_state_digest_mismatch")
    signature = payload.get("desired_state_signature")
    if not isinstance(signature, Mapping):
        raise FleetContractError("desired_state_signature_required")
    expected_signature_fields = {
        "schema_version",
        "algorithm",
        "role",
        "key_id",
        "signed_payload_sha256",
        "signature",
    }
    if set(signature) != expected_signature_fields:
        raise FleetContractError("invalid_desired_state_signature_fields")
    if signature.get("schema_version") != 1:
        raise FleetContractError("invalid_signature_schema_version")
    if signature.get("algorithm") != "ed25519":
        raise FleetContractError("invalid_signature_algorithm")
    if signature.get("role") != DESIRED_STATE_SIGNING_ROLE:
        raise FleetContractError("invalid_signature_role")
    _identifier(signature.get("key_id"), "signature_key_id")
    _digest(signature.get("signed_payload_sha256"), "signed_payload_sha256")
    if not isinstance(signature.get("signature"), str) or not _SIGNATURE_RE.fullmatch(
        str(signature.get("signature"))
    ):
        raise FleetContractError("invalid_signature_encoding")
    return dict(payload)


def verify_desired_state_signature(
    payload: Mapping[str, Any],
    *,
    public_keys: Mapping[str, bytes],
    now: datetime | None = None,
    clock_skew_seconds: int = 300,
) -> dict[str, Any]:
    normalized = validate_desired_state(payload)
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued_at = _timestamp(normalized["issued_at"], "issued_at")
    expires_at = _timestamp(normalized["expires_at"], "expires_at")
    if expires_at <= observed_at:
        raise FleetContractError("desired_state_expired")
    if issued_at > observed_at + timedelta(seconds=max(0, clock_skew_seconds)):
        raise FleetContractError("desired_state_not_yet_valid")
    signature = normalized["desired_state_signature"]
    key_id = str(signature["key_id"])
    public_key = public_keys.get(key_id)
    if public_key is None:
        raise FleetContractError("untrusted_desired_state_key")
    body = canonical_desired_state_bytes(normalized)
    actual_sha = "sha256:" + hashlib.sha256(body).hexdigest()
    if actual_sha != signature["signed_payload_sha256"]:
        raise FleetContractError("signed_payload_sha256_mismatch")
    try:
        raw_signature = base64.urlsafe_b64decode(
            str(signature["signature"]) + ("=" * (-len(str(signature["signature"])) % 4))
        )
        Ed25519PublicKey.from_public_bytes(public_key).verify(raw_signature, body)
    except (InvalidSignature, ValueError) as exc:
        raise FleetContractError("desired_state_signature_invalid") from exc
    return {
        "verified": True,
        "algorithm": "ed25519",
        "role": DESIRED_STATE_SIGNING_ROLE,
        "key_id": key_id,
        "signed_payload_sha256": actual_sha,
        "expires_at": normalized["expires_at"],
    }


def _validate_registration(
    payload: Mapping[str, Any],
    message_type: str,
) -> dict[str, Any]:
    _base_fields(payload, message_type)
    _identifier(payload.get("installation_id"), "installation_id")
    _identifier(payload.get("local_instance_id"), "local_instance_id")
    if message_type == "agent-registration-request":
        if {
            "agent_id",
            "operator_labels",
            "labels",
            "role",
            "environment",
        } & set(payload):
            raise FleetContractError("operator_managed_registration_field_forbidden")
        _identifier(payload.get("runtime_vendor"), "runtime_vendor")
        _identifier(payload.get("adapter_id"), "adapter_id")
        _identifier(payload.get("adapter_version"), "adapter_version")
        capabilities = payload.get("reported_capabilities")
        if not isinstance(capabilities, list) or len(capabilities) > 64:
            raise FleetContractError("invalid_reported_capabilities")
        for capability in capabilities:
            _identifier(capability, "reported_capability")
    else:
        _identifier(payload.get("agent_id"), "agent_id")
        _timestamp(payload.get("server_timestamp"), "server_timestamp")
    return dict(payload)


def _validate_heartbeat(payload: Mapping[str, Any], message_type: str) -> dict[str, Any]:
    _base_fields(payload, message_type)
    _identifier(payload.get("agent_id"), "agent_id")
    _identifier(payload.get("installation_id"), "installation_id")
    if message_type == "heartbeat-request":
        _timestamp(payload.get("client_timestamp"), "client_timestamp")
        generation = payload.get("runtime_generation")
        if generation:
            _identifier(generation, "runtime_generation")
        inventory_digest = payload.get("active_inventory_digest")
        if inventory_digest:
            _digest(inventory_digest, "active_inventory_digest")
    else:
        desired = payload.get("desired_state")
        if desired is not None:
            validate_desired_state(desired)
        _timestamp(payload.get("server_timestamp"), "server_timestamp")
    return dict(payload)


def _validate_receipt_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    _base_fields(payload, "receipt-event")
    for name in (
        "event_id",
        "idempotency_key",
        "rollout_id",
        "attempt_id",
        "agent_id",
        "desired_state_revision",
        "pack_id",
        "release_id",
        "client_version",
        "adapter_version",
    ):
        _identifier(payload.get(name), name)
    _integer(payload.get("control_epoch"), "control_epoch", minimum=1)
    _integer(payload.get("event_seq"), "event_seq", minimum=1)
    _digest(payload.get("archive_sha256"), "archive_sha256")
    _digest(
        payload.get("desired_state_digest"),
        "desired_state_digest",
    )
    event_type = payload.get("event_type")
    if event_type in SERVER_EVENT_TYPES:
        raise FleetContractError("server_authority_event_forbidden")
    if event_type not in CLIENT_EVENT_TYPES:
        raise FleetContractError("invalid_event_type")
    reason_code = payload.get("reason_code", "none")
    if reason_code not in CLIENT_REASON_CODES:
        raise FleetContractError("invalid_reason_code")
    _timestamp(payload.get("client_timestamp"), "client_timestamp")
    generation = payload.get("runtime_generation", "")
    nonce = payload.get("activation_nonce", "")
    if event_type == "RUNTIME_ATTESTED":
        _identifier(generation, "runtime_generation")
        _identifier(nonce, "activation_nonce")
        _digest(payload.get("active_archive_sha256"), "active_archive_sha256")
    elif generation:
        _identifier(generation, "runtime_generation")
    if nonce:
        _identifier(nonce, "activation_nonce")
    attestation = payload.get("runtime_attestation")
    if event_type in {"RUNTIME_ATTESTED", "DRIFT_DETECTED"}:
        if not isinstance(attestation, Mapping):
            raise FleetContractError("runtime_attestation_required")
        allowed_attestation_fields = {
            "kind",
            "activation_nonce",
            "runtime_generation",
            "active_inventory_digest",
            "adapter_version",
        }
        if set(attestation) - allowed_attestation_fields:
            raise FleetContractError(
                "invalid_runtime_attestation_fields"
            )
        if (
            attestation.get("kind")
            != "agent-adapter-runtime-v1"
        ):
            raise FleetContractError(
                "invalid_runtime_attestation_kind"
            )
        attested_generation = _identifier(
            attestation.get("runtime_generation"),
            "attested_runtime_generation",
        )
        attested_inventory = _digest(
            attestation.get("active_inventory_digest"),
            "attested_active_inventory_digest",
        )
        attested_adapter = _identifier(
            attestation.get("adapter_version"),
            "attested_adapter_version",
        )
        if (
            attested_generation != generation
            or attested_adapter != payload.get("adapter_version")
        ):
            raise FleetContractError(
                "runtime_attestation_event_mismatch"
            )
        if event_type == "RUNTIME_ATTESTED":
            attested_nonce = _identifier(
                attestation.get("activation_nonce"),
                "attested_activation_nonce",
            )
            if attested_nonce != nonce:
                raise FleetContractError(
                    "runtime_attestation_nonce_mismatch"
                )
            if not attested_inventory:
                raise FleetContractError(
                    "runtime_attestation_inventory_missing"
                )
    elif attestation is not None:
        raise FleetContractError(
            "runtime_attestation_event_forbidden"
        )
    return dict(payload)


def _validate_receipt_batch(payload: Mapping[str, Any]) -> dict[str, Any]:
    _base_fields(payload, "receipt-batch")
    _identifier(payload.get("installation_id"), "installation_id")
    _identifier(payload.get("batch_id"), "batch_id")
    receipts = payload.get("receipts")
    if not isinstance(receipts, list) or not receipts or len(receipts) > 256:
        raise FleetContractError("invalid_receipt_batch")
    event_ids: set[str] = set()
    for receipt in receipts:
        normalized = _validate_receipt_event(receipt)
        event_id = str(normalized["event_id"])
        if event_id in event_ids:
            raise FleetContractError("duplicate_event_id")
        event_ids.add(event_id)
    return dict(payload)


def _validate_receipt_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    _base_fields(payload, "receipt-response")
    _identifier(payload.get("batch_id"), "batch_id")
    _timestamp(payload.get("server_timestamp"), "server_timestamp")
    for name in ("accepted_event_ids", "duplicate_event_ids", "rejected_events"):
        if not isinstance(payload.get(name), list) or len(payload[name]) > 256:
            raise FleetContractError(f"invalid_{name}")
    accepted = [
        _identifier(event_id, "accepted_event_id")
        for event_id in payload["accepted_event_ids"]
    ]
    duplicate = [
        _identifier(event_id, "duplicate_event_id")
        for event_id in payload["duplicate_event_ids"]
    ]
    rejected_ids: list[str] = []
    for item in payload["rejected_events"]:
        if not isinstance(item, Mapping):
            raise FleetContractError("invalid_rejected_event")
        rejected_ids.append(_identifier(item.get("event_id"), "rejected_event_id"))
        if item.get("reason_code") not in ALLOWED_REASON_CODES:
            raise FleetContractError("invalid_reason_code")
    all_ids = accepted + duplicate + rejected_ids
    if len(all_ids) != len(set(all_ids)):
        raise FleetContractError("duplicate_receipt_response_event_id")
    outcome = payload.get("outcome")
    if outcome is not None and outcome not in {
        "accepted",
        "accepted_duplicate",
        "rejected",
        "conflict",
        "sequence_gap",
        "stale_attempt",
    }:
        raise FleetContractError("invalid_receipt_outcome")
    failed_index = payload.get("first_failed_event_index")
    if failed_index is not None:
        _integer(
            failed_index,
            "first_failed_event_index",
            minimum=0,
        )
        if failed_index > 255:
            raise FleetContractError(
                "invalid_first_failed_event_index"
            )
    expected_sequence = payload.get("expected_next_sequence")
    if expected_sequence is not None:
        _integer(
            expected_sequence,
            "expected_next_sequence",
            minimum=1,
        )
    return dict(payload)


def validate_receipt_against_desired(
    receipt: Mapping[str, Any],
    desired_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Correlate one client observation to one signed desired document."""

    normalized = _validate_receipt_event(receipt)
    desired = validate_desired_state(desired_state)
    exact = {
        "agent_id": desired["agent_id"],
        "rollout_id": desired["rollout_id"],
        "desired_state_revision": desired[
            "desired_state_revision"
        ],
        "control_epoch": desired["control_epoch"],
        "desired_state_digest": desired["desired_state_digest"],
    }
    for field, expected in exact.items():
        if normalized.get(field) != expected:
            raise FleetContractError(
                f"receipt_desired_state_mismatch:{field}"
            )
    item = next(
        (
            candidate
            for candidate in desired["items"]
            if candidate["attempt_id"] == normalized["attempt_id"]
        ),
        None,
    )
    if item is None:
        raise FleetContractError("receipt_attempt_not_in_desired_state")
    for field in ("pack_id", "release_id", "archive_sha256"):
        if normalized[field] != item[field]:
            raise FleetContractError(
                f"receipt_desired_item_mismatch:{field}"
            )
    if normalized["event_type"] == "RUNTIME_ATTESTED":
        attestation = normalized["runtime_attestation"]
        if (
            normalized["activation_nonce"]
            != item["activation_nonce"]
            or attestation["activation_nonce"]
            != item["activation_nonce"]
        ):
            raise FleetContractError(
                "runtime_attestation_nonce_mismatch"
            )
        if (
            attestation["active_inventory_digest"]
            != desired["expected_inventory_digest"]
        ):
            raise FleetContractError(
                "runtime_attestation_inventory_mismatch"
            )
        if (
            normalized["active_archive_sha256"]
            != item["archive_sha256"]
        ):
            raise FleetContractError(
                "runtime_attestation_archive_mismatch"
            )
    elif normalized["event_type"] == "DRIFT_DETECTED":
        if (
            normalized["runtime_attestation"][
                "active_inventory_digest"
            ]
            == desired["expected_inventory_digest"]
        ):
            raise FleetContractError(
                "drift_attestation_inventory_matches_desired"
            )
    return normalized


def validate_contract_message(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise FleetContractError("message_object_required")
    message_type = payload.get("message_type")
    if message_type == "desired-state":
        return validate_desired_state(payload)
    if message_type in {"agent-registration-request", "agent-registration-response"}:
        return _validate_registration(payload, str(message_type))
    if message_type in {"heartbeat-request", "heartbeat-response"}:
        return _validate_heartbeat(payload, str(message_type))
    if message_type == "receipt-event":
        return _validate_receipt_event(payload)
    if message_type == "receipt-batch":
        return _validate_receipt_batch(payload)
    if message_type == "receipt-response":
        return _validate_receipt_response(payload)
    raise FleetContractError("unsupported_message_type")
