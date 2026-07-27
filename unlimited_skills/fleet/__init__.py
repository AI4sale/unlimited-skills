"""Public Fleet Wire Contract and local reconciliation primitives."""

from .adapter import (
    AgentAdapter,
    InstalledRevision,
    RuntimeAttestation,
    RuntimeInventory,
)
from .contract import (
    FLEET_CONTRACT_ID,
    FLEET_CONTRACT_VERSION,
    FleetContractError,
    canonical_desired_state_bytes,
    canonical_json_bytes,
    desired_state_digest,
    load_contract_document,
    parse_json_strict,
    validate_contract_bundle,
    validate_contract_message,
    validate_desired_state,
    verify_desired_state_signature,
)
from .privacy import FleetPrivacyError, assert_receipt_metadata_safe
from .receipts import ReceiptBuilder, ReceiptError
from .reconciler import FleetReconciler, ReconcileError, ReconcileResult
from .spool import ReceiptSpool, ReceiptSpoolError

__all__ = [
    "AgentAdapter",
    "FLEET_CONTRACT_ID",
    "FLEET_CONTRACT_VERSION",
    "FleetContractError",
    "FleetPrivacyError",
    "FleetReconciler",
    "InstalledRevision",
    "ReceiptBuilder",
    "ReceiptError",
    "ReceiptSpool",
    "ReceiptSpoolError",
    "ReconcileError",
    "ReconcileResult",
    "RuntimeAttestation",
    "RuntimeInventory",
    "assert_receipt_metadata_safe",
    "canonical_desired_state_bytes",
    "canonical_json_bytes",
    "desired_state_digest",
    "load_contract_document",
    "parse_json_strict",
    "validate_contract_bundle",
    "validate_contract_message",
    "validate_desired_state",
    "verify_desired_state_signature",
]
