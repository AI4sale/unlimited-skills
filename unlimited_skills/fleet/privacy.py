"""Privacy allowlist for fleet receipt metadata."""

from __future__ import annotations

import re
from typing import Any, Mapping


ALLOWED_RECEIPT_KEYS = {
    "contract_id",
    "contract_version",
    "message_type",
    "event_id",
    "idempotency_key",
    "rollout_id",
    "attempt_id",
    "agent_id",
    "desired_state_revision",
    "desired_state_digest",
    "control_epoch",
    "pack_id",
    "release_id",
    "archive_sha256",
    "event_type",
    "event_seq",
    "runtime_generation",
    "activation_nonce",
    "active_archive_sha256",
    "client_timestamp",
    "reason_code",
    "client_version",
    "adapter_version",
    "runtime_attestation",
}
ALLOWED_RUNTIME_ATTESTATION_KEYS = {
    "kind",
    "activation_nonce",
    "runtime_generation",
    "active_inventory_digest",
    "adapter_version",
}
PROHIBITED_KEY_PARTS = {
    "prompt",
    "stderr",
    "stdout",
    "traceback",
    "exception",
    "secret",
    "token",
    "password",
    "private_key",
    "environment",
    "env",
    "path",
    "cwd",
    "home",
    "content",
    "body",
}
_WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\[a-z0-9_.-]+\\)")
_POSIX_PATH_RE = re.compile(r"(?:^|[\s\"'])/(?:home|users|var|tmp|etc|opt)/")
_SECRET_RE = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._~-]{12,}|(?:api[_-]?key|token|secret|password)\s*[:=])"
)


class FleetPrivacyError(ValueError):
    """Raised before unsafe receipt metadata can enter the spool."""


def assert_receipt_metadata_safe(receipt: Mapping[str, Any]) -> None:
    unknown = set(receipt) - ALLOWED_RECEIPT_KEYS
    if unknown:
        raise FleetPrivacyError("receipt_field_not_allowlisted")
    for key, value in receipt.items():
        lowered = str(key).lower()
        if any(part == lowered or part in lowered.split("_") for part in PROHIBITED_KEY_PARTS):
            raise FleetPrivacyError("receipt_field_prohibited")
        if key == "runtime_attestation":
            if not isinstance(value, Mapping):
                raise FleetPrivacyError(
                    "invalid_runtime_attestation_metadata"
                )
            if set(value) - ALLOWED_RUNTIME_ATTESTATION_KEYS:
                raise FleetPrivacyError(
                    "runtime_attestation_field_not_allowlisted"
                )
            for nested_key, nested_value in value.items():
                if isinstance(nested_value, (dict, list)):
                    raise FleetPrivacyError(
                        "nested_receipt_metadata_forbidden"
                    )
                if isinstance(nested_value, str):
                    if (
                        "\x00" in nested_value
                        or "\n" in nested_value
                        or "\r" in nested_value
                        or _WINDOWS_PATH_RE.search(nested_value)
                        or _POSIX_PATH_RE.search(nested_value)
                        or _SECRET_RE.search(nested_value)
                    ):
                        raise FleetPrivacyError(
                            "unsafe_runtime_attestation_metadata"
                        )
            continue
        if isinstance(value, (dict, list)):
            raise FleetPrivacyError("nested_receipt_metadata_forbidden")
        if isinstance(value, str):
            if "\x00" in value or "\n" in value or "\r" in value:
                raise FleetPrivacyError("multiline_receipt_metadata_forbidden")
            if _WINDOWS_PATH_RE.search(value) or _POSIX_PATH_RE.search(value):
                raise FleetPrivacyError("local_path_in_receipt")
            if _SECRET_RE.search(value):
                raise FleetPrivacyError("secret_like_value_in_receipt")
