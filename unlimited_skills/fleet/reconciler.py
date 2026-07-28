"""Finite-action local fleet reconciler.

The reconciler proves local milestones through receipts.  It never emits the
server-authority states TARGETED or VERIFIED_ACTIVE.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .adapter import (
    AgentAdapter,
    InventoryAgentAdapter,
    InstalledRevision,
    ManagedFleetAdapterError,
    RuntimeAttestation,
    RuntimeInventory,
    RuntimeInventoryAttestation,
)
from .contract import (
    FleetContractError,
    validate_desired_state,
    verify_desired_state_signature,
)
from .receipts import ReceiptBuilder
from .spool import ReceiptSpool


class ReconcileError(RuntimeError):
    pass


def _adapter_failure_receipt(
    exc: ManagedFleetAdapterError,
) -> tuple[str, str]:
    code = str(exc)
    if code == "runtime_attestation_pending":
        return "FAILED_RETRYABLE", "activation_pending"
    if code == "runtime_attestation_invalid":
        return "FAILED_TERMINAL", "runtime_attestation_invalid"
    if code.startswith("pack_manifest"):
        return "FAILED_TERMINAL", "manifest_invalid"
    if code in {
        "pack_archive_hash_mismatch",
        "artifact_hash_mismatch",
    }:
        return "FAILED_TERMINAL", "artifact_hash_mismatch"
    terminal_prefixes = (
        "activation_",
        "active_state_",
        "installed_revision_",
        "managed_inventory_",
        "managed_root_",
        "managed_skill_",
        "pack_archive_",
        "pack_skill_",
        "pack_skills_",
        "runtime_path_",
        "unmanaged_skill_",
    )
    if code.startswith(terminal_prefixes):
        return "FAILED_TERMINAL", "install_failed"
    return "FAILED_RETRYABLE", "adapter_unavailable"


@dataclass(frozen=True)
class ReconcileResult:
    agent_id: str
    rollout_id: str
    desired_state_revision: str
    control_epoch: int
    receipts: tuple[dict[str, Any], ...]
    activation_pending: bool


class FleetReconciler:
    def __init__(
        self,
        *,
        agent_id: str,
        adapter: AgentAdapter,
        public_keys: Mapping[str, bytes],
        state_path: Path,
        spool: ReceiptSpool,
        client_version: str,
        auto_activate: bool | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.adapter = adapter
        self.public_keys = dict(public_keys)
        self.state_path = Path(state_path)
        self.spool = spool
        self.client_version = client_version
        if auto_activate is None:
            auto_activate = os.environ.get(
                "UNLIMITED_SKILLS_FLEET_AUTO_ACTIVATE",
                "0",
            ).strip().lower() in {"1", "true", "yes", "on"}
        self.auto_activate = bool(auto_activate)

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {"control_epoch": 0, "desired_state_digest": "", "desired_state_revision": ""}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReconcileError("local_reconcile_state_invalid") from exc
        if not isinstance(value, dict):
            raise ReconcileError("local_reconcile_state_invalid")
        return value

    def _write_state(self, value: Mapping[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(
            prefix=".fleet-state-",
            suffix=".tmp",
            dir=self.state_path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.state_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _check_epoch(self, desired: Mapping[str, Any]) -> bool:
        local = self._read_state()
        current_epoch = int(local.get("control_epoch") or 0)
        desired_epoch = int(desired["control_epoch"])
        if desired_epoch < current_epoch:
            raise ReconcileError("stale_control_epoch")
        if desired_epoch == current_epoch:
            if local.get("desired_state_digest") != desired["desired_state_digest"]:
                raise ReconcileError("control_epoch_digest_conflict")
            return True
        return False

    def _spool_receipt(
        self,
        receipts: list[dict[str, Any]],
        builder: ReceiptBuilder,
        event_type: str,
        **values: Any,
    ) -> None:
        receipt = builder.build(event_type, **values)
        self.spool.append(receipt)
        receipts.append(receipt)

    def _receipt_builder(
        self,
        desired: Mapping[str, Any],
        item: Mapping[str, Any],
    ) -> ReceiptBuilder:
        return ReceiptBuilder(
            rollout_id=str(desired["rollout_id"]),
            attempt_id=str(item["attempt_id"]),
            agent_id=self.agent_id,
            desired_state_revision=str(desired["desired_state_revision"]),
            desired_state_digest=str(desired["desired_state_digest"]),
            control_epoch=int(desired["control_epoch"]),
            pack_id=str(item["pack_id"]),
            release_id=str(item["release_id"]),
            archive_sha256=str(item["archive_sha256"]),
            client_version=self.client_version,
            adapter_version=self.adapter.adapter_version,
            starting_event_seq=self.spool.last_event_sequence(
                str(item["attempt_id"])
            ),
        )

    def _write_epoch_state(
        self,
        desired: Mapping[str, Any],
        *,
        already_seen: bool,
    ) -> None:
        if already_seen:
            return
        self._write_state(
            {
                "agent_id": self.agent_id,
                "control_epoch": desired["control_epoch"],
                "desired_state_digest": desired["desired_state_digest"],
                "desired_state_revision": desired["desired_state_revision"],
                "rollout_id": desired["rollout_id"],
            }
        )

    def _result(
        self,
        desired: Mapping[str, Any],
        receipts: list[dict[str, Any]],
        *,
        activation_pending: bool,
        already_seen: bool,
    ) -> ReconcileResult:
        self._write_epoch_state(desired, already_seen=already_seen)
        return ReconcileResult(
            agent_id=self.agent_id,
            rollout_id=str(desired["rollout_id"]),
            desired_state_revision=str(desired["desired_state_revision"]),
            control_epoch=int(desired["control_epoch"]),
            receipts=tuple(receipts),
            activation_pending=activation_pending,
        )

    def _reconcile_inventory(
        self,
        desired: Mapping[str, Any],
        inventory: RuntimeInventory,
        *,
        already_seen: bool,
    ) -> ReconcileResult:
        adapter = self.adapter
        if not isinstance(adapter, InventoryAgentAdapter):
            raise ReconcileError("adapter_inventory_activation_required")
        items = [
            {
                **dict(item),
                "agent_id": str(desired["agent_id"]),
                "rollout_id": str(desired["rollout_id"]),
                "desired_state_revision": str(
                    desired["desired_state_revision"]
                ),
            }
            for item in desired["items"]
        ]
        receipts: list[dict[str, Any]] = []
        builders = {
            str(item["pack_id"]): self._receipt_builder(desired, item)
            for item in items
        }
        installed: dict[str, InstalledRevision] = {}
        activation_pending = False
        install_failed = False

        for item in items:
            pack_id = str(item["pack_id"])
            builder = builders[pack_id]
            self._spool_receipt(
                receipts,
                builder,
                "DESIRED_SEEN",
                runtime_generation=inventory.runtime_generation,
            )
            try:
                revision = adapter.install_revision(item)
                if (
                    not isinstance(revision, InstalledRevision)
                    or not revision.install_committed
                    or revision.pack_id != item["pack_id"]
                    or revision.release_id != item["release_id"]
                    or revision.version != item["version"]
                ):
                    raise ReconcileError("install_failed")
                adapter.verify_revision(item, revision)
                self._spool_receipt(
                    receipts,
                    builder,
                    "MANIFEST_VERIFIED",
                )
                if revision.archive_sha256 != item["archive_sha256"]:
                    raise ReconcileError("artifact_hash_mismatch")
                self._spool_receipt(
                    receipts,
                    builder,
                    "ARTIFACT_VERIFIED",
                )
                self._spool_receipt(
                    receipts,
                    builder,
                    "INSTALL_COMMITTED",
                )
                installed[pack_id] = revision
            except ReconcileError as exc:
                self._spool_receipt(
                    receipts,
                    builder,
                    "FAILED_TERMINAL",
                    reason_code=(
                        str(exc)
                        if str(exc)
                        in {"artifact_hash_mismatch", "install_failed"}
                        else "install_failed"
                    ),
                )
                install_failed = True
                activation_pending = True
            except ManagedFleetAdapterError as exc:
                event_type, reason_code = _adapter_failure_receipt(
                    exc
                )
                self._spool_receipt(
                    receipts,
                    builder,
                    event_type,
                    reason_code=reason_code,
                )
                install_failed = True
                activation_pending = True
            except Exception as exc:
                self._spool_receipt(
                    receipts,
                    builder,
                    "FAILED_RETRYABLE",
                    reason_code="adapter_unavailable",
                )
                install_failed = True
                activation_pending = True
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise

        if install_failed:
            for item in items:
                pack_id = str(item["pack_id"])
                if pack_id not in installed:
                    continue
                self._spool_receipt(
                    receipts,
                    builders[pack_id],
                    "ACTIVATION_PENDING",
                    reason_code="install_failed",
                    activation_nonce=str(item["activation_nonce"]),
                )
            return self._result(
                desired,
                receipts,
                activation_pending=activation_pending,
                already_seen=already_seen,
            )

        activation_nonces = {
            str(item["pack_id"]): str(item["activation_nonce"])
            for item in items
        }
        if not self.auto_activate:
            for item in items:
                self._spool_receipt(
                    receipts,
                    builders[str(item["pack_id"])],
                    "ACTIVATION_PENDING",
                    reason_code="activation_pending",
                    activation_nonce=str(item["activation_nonce"]),
                )
            return self._result(
                desired,
                receipts,
                activation_pending=True,
                already_seen=already_seen,
            )

        try:
            adapter.activate_inventory(
                items,
                installed,
                activation_nonces=activation_nonces,
            )
            for item in items:
                self._spool_receipt(
                    receipts,
                    builders[str(item["pack_id"])],
                    "ACTIVATION_PENDING",
                    reason_code="activation_pending",
                    activation_nonce=str(item["activation_nonce"]),
                )
            attestation = adapter.attest_inventory(
                items,
                activation_nonces=activation_nonces,
            )
            if not isinstance(
                attestation,
                RuntimeInventoryAttestation,
            ):
                raise ReconcileError("runtime_attestation_invalid")
            expected_revisions = {
                str(item["pack_id"]): str(item["release_id"])
                for item in items
            }
            expected_archives = {
                str(item["pack_id"]): str(item["archive_sha256"])
                for item in items
            }
            if (
                dict(attestation.activation_nonces)
                != activation_nonces
                or dict(attestation.active_revisions)
                != expected_revisions
                or dict(attestation.active_archive_sha256)
                != expected_archives
                or attestation.active_inventory_digest
                != desired["expected_inventory_digest"]
                or attestation.adapter_version
                != adapter.adapter_version
            ):
                raise ReconcileError("runtime_attestation_invalid")
            for item in items:
                pack_id = str(item["pack_id"])
                self._spool_receipt(
                    receipts,
                    builders[pack_id],
                    "RUNTIME_ATTESTED",
                    runtime_generation=attestation.runtime_generation,
                    activation_nonce=activation_nonces[pack_id],
                    active_archive_sha256=(
                        attestation.active_archive_sha256[pack_id]
                    ),
                    active_inventory_digest=(
                        attestation.active_inventory_digest
                    ),
                )
            if adapter.detect_inventory_drift(items):
                for item in items:
                    pack_id = str(item["pack_id"])
                    self._spool_receipt(
                        receipts,
                        builders[pack_id],
                        "DRIFT_DETECTED",
                        reason_code="drift_detected",
                        runtime_generation=(
                            attestation.runtime_generation
                        ),
                        activation_nonce=activation_nonces[pack_id],
                        active_inventory_digest=(
                            attestation.active_inventory_digest
                        ),
                    )
                activation_pending = True
        except ReconcileError as exc:
            for item in items:
                self._spool_receipt(
                    receipts,
                    builders[str(item["pack_id"])],
                    "FAILED_TERMINAL",
                    reason_code=(
                        str(exc)
                        if str(exc) == "runtime_attestation_invalid"
                        else "install_failed"
                    ),
                )
            activation_pending = True
        except ManagedFleetAdapterError as exc:
            event_type, reason_code = _adapter_failure_receipt(exc)
            for item in items:
                self._spool_receipt(
                    receipts,
                    builders[str(item["pack_id"])],
                    event_type,
                    reason_code=reason_code,
                )
            activation_pending = True
        except Exception as exc:
            for item in items:
                self._spool_receipt(
                    receipts,
                    builders[str(item["pack_id"])],
                    "FAILED_RETRYABLE",
                    reason_code="adapter_unavailable",
                )
            activation_pending = True
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
        return self._result(
            desired,
            receipts,
            activation_pending=activation_pending,
            already_seen=already_seen,
        )

    def reconcile(self, desired_state: Mapping[str, Any]) -> ReconcileResult:
        if os.environ.get("UNLIMITED_SKILLS_FLEET_DISABLE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            raise ReconcileError("fleet_reconciliation_disabled")
        try:
            desired = validate_desired_state(desired_state)
            verify_desired_state_signature(desired, public_keys=self.public_keys)
        except FleetContractError as exc:
            raise ReconcileError(str(exc)) from exc
        if desired["agent_id"] != self.agent_id:
            raise ReconcileError("agent_binding_mismatch")
        already_seen = self._check_epoch(desired)
        try:
            inventory = self.adapter.discover()
            if not isinstance(inventory, RuntimeInventory):
                raise ReconcileError("adapter_unavailable")
        except Exception as exc:
            raise ReconcileError("adapter_unavailable") from exc
        items = [
            {
                **dict(item),
                "agent_id": str(desired["agent_id"]),
                "rollout_id": str(desired["rollout_id"]),
                "desired_state_revision": str(
                    desired["desired_state_revision"]
                ),
            }
            for item in desired["items"]
        ]
        if isinstance(self.adapter, InventoryAgentAdapter):
            return self._reconcile_inventory(
                desired,
                inventory,
                already_seen=already_seen,
            )
        if len(items) > 1:
            raise ReconcileError(
                "adapter_inventory_activation_required"
            )
        receipts: list[dict[str, Any]] = []
        activation_pending = False
        for item in items:
            builder = self._receipt_builder(desired, item)
            self._spool_receipt(
                receipts,
                builder,
                "DESIRED_SEEN",
                runtime_generation=inventory.runtime_generation,
            )
            try:
                installed = self.adapter.install_revision(item)
                if not isinstance(installed, InstalledRevision) or not installed.install_committed:
                    raise ReconcileError("install_failed")
                if (
                    installed.pack_id != item["pack_id"]
                    or installed.release_id != item["release_id"]
                    or installed.version != item["version"]
                ):
                    raise ReconcileError("install_failed")
                self.adapter.verify_revision(item, installed)
                self._spool_receipt(receipts, builder, "MANIFEST_VERIFIED")
                if installed.archive_sha256 != item["archive_sha256"]:
                    raise ReconcileError("artifact_hash_mismatch")
                self._spool_receipt(receipts, builder, "ARTIFACT_VERIFIED")
                self._spool_receipt(receipts, builder, "INSTALL_COMMITTED")
                activation_nonce = str(item["activation_nonce"])
                if not self.auto_activate:
                    self._spool_receipt(
                        receipts,
                        builder,
                        "ACTIVATION_PENDING",
                        reason_code="activation_pending",
                        activation_nonce=activation_nonce,
                    )
                    activation_pending = True
                    continue
                if item["action"] == "rollback":
                    self.adapter.rollback_revision(
                        item,
                        installed,
                        activation_nonce=activation_nonce,
                    )
                elif item["action"] == "activate":
                    self.adapter.activate_revision(
                        item,
                        installed,
                        activation_nonce=activation_nonce,
                    )
                else:
                    raise ReconcileError("unsupported_action")
                self._spool_receipt(
                    receipts,
                    builder,
                    "ACTIVATION_PENDING",
                    reason_code="activation_pending",
                    activation_nonce=activation_nonce,
                )
                attestation = self.adapter.attest_runtime(
                    item,
                    activation_nonce=activation_nonce,
                )
                if not isinstance(attestation, RuntimeAttestation):
                    raise ReconcileError("runtime_attestation_invalid")
                if (
                    attestation.activation_nonce != activation_nonce
                    or attestation.pack_id != item["pack_id"]
                    or attestation.release_id != item["release_id"]
                    or attestation.active_archive_sha256 != item["archive_sha256"]
                    or attestation.active_inventory_digest
                    != desired["expected_inventory_digest"]
                    or attestation.adapter_version != self.adapter.adapter_version
                ):
                    raise ReconcileError("runtime_attestation_invalid")
                self._spool_receipt(
                    receipts,
                    builder,
                    "RUNTIME_ATTESTED",
                    runtime_generation=attestation.runtime_generation,
                    activation_nonce=attestation.activation_nonce,
                    active_archive_sha256=attestation.active_archive_sha256,
                    active_inventory_digest=(
                        attestation.active_inventory_digest
                    ),
                )
                if self.adapter.detect_drift(item):
                    self._spool_receipt(
                        receipts,
                        builder,
                        "DRIFT_DETECTED",
                        reason_code="drift_detected",
                        runtime_generation=attestation.runtime_generation,
                        activation_nonce=attestation.activation_nonce,
                        active_inventory_digest=(
                            attestation.active_inventory_digest
                        ),
                    )
                    activation_pending = True
            except ReconcileError as exc:
                self._spool_receipt(
                    receipts,
                    builder,
                    "FAILED_TERMINAL",
                    reason_code=str(exc)
                    if str(exc)
                    in {
                        "artifact_hash_mismatch",
                        "install_failed",
                        "runtime_attestation_invalid",
                        "unsupported_action",
                    }
                    else "install_failed",
                )
                activation_pending = True
            except ManagedFleetAdapterError as exc:
                event_type, reason_code = _adapter_failure_receipt(
                    exc
                )
                self._spool_receipt(
                    receipts,
                    builder,
                    event_type,
                    reason_code=reason_code,
                )
                activation_pending = True
            except Exception as exc:
                self._spool_receipt(
                    receipts,
                    builder,
                    "FAILED_RETRYABLE",
                    reason_code="adapter_unavailable",
                )
                activation_pending = True
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
        return self._result(
            desired,
            receipts,
            activation_pending=activation_pending,
            already_seen=already_seen,
        )
