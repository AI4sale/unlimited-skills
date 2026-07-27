"""Deterministic client receipt construction."""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from .contract import (
    CLIENT_EVENT_TYPES,
    FLEET_CONTRACT_ID,
    FLEET_CONTRACT_VERSION,
    FleetContractError,
    validate_contract_message,
)
from .privacy import assert_receipt_metadata_safe


class ReceiptError(ValueError):
    pass


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class ReceiptBuilder:
    rollout_id: str
    attempt_id: str
    agent_id: str
    desired_state_revision: str
    control_epoch: int
    pack_id: str
    release_id: str
    archive_sha256: str
    client_version: str
    adapter_version: str
    _sequence: int = field(default=0, init=False, repr=False)

    def build(
        self,
        event_type: str,
        *,
        reason_code: str = "none",
        runtime_generation: str = "",
        activation_nonce: str = "",
        active_archive_sha256: str = "",
        event_id: str | None = None,
        client_timestamp: str | None = None,
    ) -> dict[str, Any]:
        if event_type not in CLIENT_EVENT_TYPES:
            raise ReceiptError("client_event_type_forbidden")
        self._sequence += 1
        attempt_bucket = hashlib.sha256(
            self.attempt_id.encode("utf-8")
        ).hexdigest()[:16]
        generated_event_id = event_id or (
            f"evt_{attempt_bucket}_{self._sequence:010d}_{uuid.uuid4().hex}"
        )
        receipt: dict[str, Any] = {
            "contract_id": FLEET_CONTRACT_ID,
            "contract_version": FLEET_CONTRACT_VERSION,
            "message_type": "receipt-event",
            "event_id": generated_event_id,
            "idempotency_key": generated_event_id,
            "rollout_id": self.rollout_id,
            "attempt_id": self.attempt_id,
            "agent_id": self.agent_id,
            "desired_state_revision": self.desired_state_revision,
            "control_epoch": self.control_epoch,
            "pack_id": self.pack_id,
            "release_id": self.release_id,
            "archive_sha256": self.archive_sha256,
            "event_type": event_type,
            "event_seq": self._sequence,
            "runtime_generation": runtime_generation,
            "activation_nonce": activation_nonce,
            "active_archive_sha256": active_archive_sha256,
            "client_timestamp": client_timestamp or utc_now(),
            "reason_code": reason_code,
            "client_version": self.client_version,
            "adapter_version": self.adapter_version,
        }
        try:
            normalized = validate_contract_message(receipt)
            assert_receipt_metadata_safe(normalized)
        except (FleetContractError, ValueError) as exc:
            self._sequence -= 1
            raise ReceiptError(str(exc)) from exc
        return normalized
