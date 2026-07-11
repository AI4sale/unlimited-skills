"""Public structural contract for signed completion receipts.

The MIT client never owns trust keys and never decides that a receipt is
authentic.  It only rejects malformed or unbounded envelopes before forwarding
the exact signed JSON object to an owner-configured provider.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Mapping


RECEIPT_SCHEMA = "unlimited-skills.accepted-completion-receipt.v1"
SIGNATURE_ALGORITHM = "ed25519"
PURPOSE = "completion_memory"
MAX_RECEIPT_BYTES = 32_768
MAX_SUMMARY_CHARS = 6_000
MAX_REF_CHARS = 1_200
MAX_ID_CHARS = 160
ALLOWED_ARTIFACT_TYPES = {"pull_request", "release", "file", "decision"}
ALLOWED_DESTINATION_STATUSES = {"accepted", "merged", "published", "disputed"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SIGNATURE_RE = re.compile(r"^[A-Za-z0-9_-]{86}$")
_REF_PREFIXES = ("https://", "git:", "pypi:", "urn:", "artifact:")


class CompletionReceiptError(ValueError):
    pass


def parse_json_strict(raw: bytes | str, *, maximum: int = MAX_RECEIPT_BYTES) -> dict[str, Any]:
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    if not data or len(data) > maximum:
        raise CompletionReceiptError("invalid_request_size")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise CompletionReceiptError("duplicate_json_property")
            value[key] = item
        return value

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)
    except CompletionReceiptError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompletionReceiptError("invalid_json") from exc
    if not isinstance(value, dict):
        raise CompletionReceiptError("json_object_required")
    return value


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _exact(value: Mapping[str, Any], keys: set[str], name: str) -> None:
    if set(value) != keys:
        raise CompletionReceiptError(f"invalid_{name}_fields")


def _text(value: Any, name: str, maximum: int, *, whitespace: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum or "\x00" in value:
        raise CompletionReceiptError(f"invalid_{name}")
    if not whitespace and any(char.isspace() for char in value):
        raise CompletionReceiptError(f"invalid_{name}")
    return value


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, MAX_ID_CHARS)
    if not _ID_RE.fullmatch(text):
        raise CompletionReceiptError(f"invalid_{name}")
    return text


def _reference(value: Any, name: str) -> str:
    text = _text(value, name, MAX_REF_CHARS)
    if not text.startswith(_REF_PREFIXES):
        raise CompletionReceiptError(f"invalid_{name}")
    return text


def _digest(value: Any, name: str) -> str:
    text = _text(value, name, 71)
    if not _DIGEST_RE.fullmatch(text):
        raise CompletionReceiptError(f"invalid_{name}")
    return text


def validate_receipt(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CompletionReceiptError("invalid_receipt")
    try:
        encoded = canonical_json(raw)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CompletionReceiptError("invalid_receipt") from exc
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise CompletionReceiptError("invalid_receipt")
    _exact(
        raw,
        {
            "schema_version",
            "audience",
            "purpose",
            "project_scope",
            "entity",
            "sensitivity",
            "issued_at",
            "summary",
            "producer",
            "artifact",
            "destination",
            "checker",
            "signature",
        },
        "receipt",
    )
    if raw.get("schema_version") != RECEIPT_SCHEMA:
        raise CompletionReceiptError("invalid_receipt_schema")
    _identifier(raw.get("audience"), "audience")
    if raw.get("purpose") != PURPOSE:
        raise CompletionReceiptError("invalid_purpose")
    for name in ("project_scope", "entity", "sensitivity"):
        _identifier(raw.get(name), name)
    issued_at = _text(raw.get("issued_at"), "issued_at", 40)
    try:
        parsed = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise CompletionReceiptError("invalid_issued_at") from exc
    _text(raw.get("summary"), "summary", MAX_SUMMARY_CHARS, whitespace=True)

    producer = raw.get("producer")
    artifact = raw.get("artifact")
    destination = raw.get("destination")
    checker = raw.get("checker")
    signature = raw.get("signature")
    if not all(isinstance(item, Mapping) for item in (producer, artifact, destination, checker, signature)):
        raise CompletionReceiptError("invalid_nested_receipt_object")
    _exact(producer, {"id"}, "producer")
    _exact(artifact, {"type", "logical_ref", "canonical_ref", "revision", "digest", "supersedes"}, "artifact")
    _exact(destination, {"status", "receipt_id"}, "destination")
    _exact(checker, {"id", "status", "evidence_digest"}, "checker")
    _exact(signature, {"algorithm", "key_id", "value"}, "signature")
    _identifier(producer.get("id"), "producer_id")
    artifact_type = str(artifact.get("type") or "")
    if artifact_type not in ALLOWED_ARTIFACT_TYPES:
        raise CompletionReceiptError("invalid_artifact_type")
    _reference(artifact.get("logical_ref"), "artifact_logical_ref")
    _reference(artifact.get("canonical_ref"), "artifact_canonical_ref")
    _identifier(artifact.get("revision"), "artifact_revision")
    _digest(artifact.get("digest"), "artifact_digest")
    if artifact.get("supersedes") is not None:
        _identifier(artifact.get("supersedes"), "artifact_supersedes")
    if destination.get("status") not in ALLOWED_DESTINATION_STATUSES:
        raise CompletionReceiptError("invalid_destination_status")
    _identifier(destination.get("receipt_id"), "destination_receipt_id")
    _identifier(checker.get("id"), "checker_id")
    if checker.get("status") != "passed":
        raise CompletionReceiptError("checker_not_passed")
    _digest(checker.get("evidence_digest"), "checker_evidence_digest")
    if signature.get("algorithm") != SIGNATURE_ALGORITHM:
        raise CompletionReceiptError("invalid_signature_algorithm")
    _identifier(signature.get("key_id"), "signature_key_id")
    signature_value = _text(signature.get("value"), "signature_value", 86)
    if not _SIGNATURE_RE.fullmatch(signature_value):
        raise CompletionReceiptError("invalid_signature_encoding")
    return json.loads(encoded.decode("utf-8"))
