"""Registered fleet agent client and atomic FCP-004 receipt uploader.

This module owns client-generated local agent identity, body-bound
registration and heartbeat requests, and the handoff of verified desired
state to the local reconciler.  Heartbeat is liveness and inventory only; it
does not report installation, activation, compliance, or server-authority
states.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .. import __version__
from ..policy_enforcement import enforce_registry_url
from ..registration import (
    RegistrationState,
    proof_headers,
    redact_sensitive_text,
    require_secure_url,
)
from ..service_client import ServiceClientError, request_json
from .adapter import AgentAdapter, RuntimeInventory
from .contract import (
    FLEET_CONTRACT_ID,
    FLEET_CONTRACT_VERSION,
    MAX_MESSAGE_BYTES,
    FleetContractError,
    validate_contract_message,
    verify_desired_state_signature,
)
from .receipts import utc_now
from .reconciler import FleetReconciler, ReconcileError, ReconcileResult
from .spool import ReceiptSpool


_IDENTIFIER_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}$"
)
_IDENTITY_FIELDS = {
    "schema_version",
    "installation_id",
    "local_instance_id",
    "agent_id",
}


class FleetAgentClientError(RuntimeError):
    """Raised when fleet agent identity or wire processing fails closed."""


@dataclass(frozen=True)
class FleetAgentIdentity:
    installation_id: str
    local_instance_id: str
    agent_id: str = ""
    schema_version: int = 1

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "installation_id": self.installation_id,
            "local_instance_id": self.local_instance_id,
            "agent_id": self.agent_id,
        }


@dataclass(frozen=True)
class FleetAgentRunResult:
    identity: FleetAgentIdentity
    server_timestamp: str
    desired_state_received: bool
    reconcile_result: ReconcileResult | None
    receipt_upload: FleetReceiptUploadResult | None


@dataclass(frozen=True)
class FleetReceiptUploadResult:
    batch_count: int
    accepted_count: int
    duplicate_count: int
    pending_count: int
    outcome: str


FleetTransport = Callable[..., dict[str, Any]]


def _identifier(value: str, name: str) -> str:
    normalized = str(value or "")
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise FleetAgentClientError(f"fleet_agent_{name}_invalid")
    return normalized


def _canonical_uuid4(value: str) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except ValueError as exc:
        raise FleetAgentClientError(
            "fleet_agent_local_instance_id_invalid"
        ) from exc
    if (
        parsed.version != 4
        or str(parsed) != str(value).lower()
        or str(value) != str(value).lower()
    ):
        raise FleetAgentClientError(
            "fleet_agent_local_instance_id_invalid"
        )
    return str(parsed)


class FleetAgentIdentityStore:
    """Atomic persisted UUIDv4 identity bound to one installation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _decode(self, value: Any) -> FleetAgentIdentity:
        if not isinstance(value, dict) or set(value) != _IDENTITY_FIELDS:
            raise FleetAgentClientError("fleet_agent_identity_invalid")
        if value.get("schema_version") != 1:
            raise FleetAgentClientError("fleet_agent_identity_invalid")
        try:
            installation_id = _identifier(
                str(value.get("installation_id") or ""),
                "installation_id",
            )
            local_instance_id = _canonical_uuid4(
                str(value.get("local_instance_id") or "")
            )
            raw_agent_id = str(value.get("agent_id") or "")
            agent_id = (
                _identifier(raw_agent_id, "agent_id")
                if raw_agent_id
                else ""
            )
        except FleetAgentClientError as exc:
            raise FleetAgentClientError(
                "fleet_agent_identity_invalid"
            ) from exc
        return FleetAgentIdentity(
            installation_id=installation_id,
            local_instance_id=local_instance_id,
            agent_id=agent_id,
        )

    def load(self) -> FleetAgentIdentity | None:
        if not self.path.exists():
            return None
        if self.path.is_symlink() or not self.path.is_file():
            raise FleetAgentClientError("fleet_agent_identity_unsafe")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FleetAgentClientError(
                "fleet_agent_identity_invalid"
            ) from exc
        return self._decode(value)

    def _write_new(self, identity: FleetAgentIdentity) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        payload = (
            json.dumps(
                identity.to_json(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(
            prefix=".fleet-identity-",
            suffix=".tmp",
            dir=self.path.parent,
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
            try:
                os.link(temporary, self.path)
            except FileExistsError:
                return
            except OSError as exc:
                if self.path.exists():
                    return
                raise FleetAgentClientError(
                    "fleet_agent_identity_write_failed"
                ) from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _replace(self, identity: FleetAgentIdentity) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(
                identity.to_json(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(
            prefix=".fleet-identity-",
            suffix=".tmp",
            dir=self.path.parent,
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
            if self.path.is_symlink():
                raise FleetAgentClientError(
                    "fleet_agent_identity_unsafe"
                )
            os.replace(temporary, self.path)
        except OSError as exc:
            raise FleetAgentClientError(
                "fleet_agent_identity_write_failed"
            ) from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def load_or_create(
        self,
        installation_id: str,
    ) -> FleetAgentIdentity:
        safe_installation_id = _identifier(
            installation_id,
            "installation_id",
        )
        current = self.load()
        if current is None:
            self._write_new(
                FleetAgentIdentity(
                    installation_id=safe_installation_id,
                    local_instance_id=str(uuid.uuid4()),
                )
            )
            current = self.load()
        if current is None:
            raise FleetAgentClientError(
                "fleet_agent_identity_write_failed"
            )
        if current.installation_id != safe_installation_id:
            raise FleetAgentClientError(
                "fleet_agent_identity_installation_mismatch"
            )
        return current

    def bind_agent(
        self,
        identity: FleetAgentIdentity,
        agent_id: str,
    ) -> FleetAgentIdentity:
        safe_agent_id = _identifier(agent_id, "agent_id")
        current = self.load_or_create(identity.installation_id)
        if current.local_instance_id != identity.local_instance_id:
            raise FleetAgentClientError(
                "fleet_agent_identity_local_instance_mismatch"
            )
        if current.agent_id and current.agent_id != safe_agent_id:
            raise FleetAgentClientError(
                "fleet_agent_identity_agent_mismatch"
            )
        if current.agent_id == safe_agent_id:
            return current
        bound = FleetAgentIdentity(
            installation_id=current.installation_id,
            local_instance_id=current.local_instance_id,
            agent_id=safe_agent_id,
        )
        self._replace(bound)
        verified = self.load()
        if verified != bound:
            raise FleetAgentClientError(
                "fleet_agent_identity_write_failed"
            )
        return bound


def post_fleet_json(
    state: RegistrationState,
    path: str,
    payload: Mapping[str, Any],
    *,
    organization_id: str = "",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Send one proof-bound, retry-safe fleet POST request."""

    if not state.registered:
        raise FleetAgentClientError(
            "fleet_registered_installation_required"
        )
    if not path.startswith("/v1/fleet/") or "?" in path:
        raise FleetAgentClientError("fleet_endpoint_invalid")
    base_url = str(state.server_url or "").rstrip("/")
    url = base_url + path
    try:
        require_secure_url(url, purpose="Fleet registry")
        enforce_registry_url(url, action="fleet control-plane request")
    except Exception as exc:
        raise FleetAgentClientError(redact_sensitive_text(exc)) from exc
    body = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    base_headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {state.license_token}",
        "Content-Type": "application/json",
        "User-Agent": f"unlimited-skills/{__version__} fleet-v1",
    }
    if organization_id:
        base_headers["X-ULS-Organization"] = _identifier(
            organization_id,
            "organization_id",
        )

    def attempt_headers() -> dict[str, str]:
        headers = dict(base_headers)
        proof = proof_headers(state, "POST", url, body)
        if not proof.get("X-ULS-Proof"):
            raise FleetAgentClientError("fleet_device_proof_required")
        headers.update(proof)
        return headers

    initial_headers = attempt_headers()
    try:
        return request_json(
            url,
            body=body,
            headers=initial_headers,
            method="POST",
            timeout=timeout,
            retry_safe=True,
            redactor=redact_sensitive_text,
            max_response_bytes=MAX_MESSAGE_BYTES,
            headers_factory=attempt_headers,
        )
    except ServiceClientError as exc:
        raise FleetAgentClientError(
            redact_sensitive_text(exc)
        ) from exc


class FleetAgentClient:
    """One registered agent's registration and heartbeat control loop."""

    def __init__(
        self,
        *,
        registration: RegistrationState,
        runtime_vendor: str,
        adapter: AgentAdapter,
        identity_store: FleetAgentIdentityStore,
        public_keys: Mapping[str, bytes],
        reconcile_state_path: Path,
        spool: ReceiptSpool,
        client_version: str,
        reported_capabilities: tuple[str, ...] = (),
        organization_id: str = "",
        timeout: float = 30.0,
        auto_activate: bool | None = None,
        transport: FleetTransport | None = None,
    ) -> None:
        self.registration = registration
        self.runtime_vendor = runtime_vendor
        self.adapter = adapter
        self.identity_store = identity_store
        self.public_keys = {
            str(key_id): bytes(public_key)
            for key_id, public_key in public_keys.items()
        }
        for key_id, public_key in self.public_keys.items():
            _identifier(key_id, "public_key_id")
            if len(public_key) != 32:
                raise FleetAgentClientError(
                    "fleet_public_key_invalid"
                )
        self.reconcile_state_path = Path(reconcile_state_path)
        self.spool = spool
        self.client_version = client_version
        self.reported_capabilities = tuple(
            sorted(set(str(value) for value in reported_capabilities))
        )
        self.organization_id = organization_id
        self.timeout = max(1.0, float(timeout))
        self.auto_activate = auto_activate
        self.transport = transport or post_fleet_json

    def _send(
        self,
        path: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            response = self.transport(
                self.registration,
                path,
                dict(payload),
                organization_id=self.organization_id,
                timeout=self.timeout,
            )
        except FleetAgentClientError:
            raise
        except Exception as exc:
            raise FleetAgentClientError(
                redact_sensitive_text(exc)
            ) from exc
        if not isinstance(response, dict):
            raise FleetAgentClientError(
                "fleet_registry_response_object_required"
            )
        return response

    def register(self) -> FleetAgentIdentity:
        if not self.registration.registered:
            raise FleetAgentClientError(
                "fleet_registered_installation_required"
            )
        identity = self.identity_store.load_or_create(
            self.registration.install_id
        )
        payload = {
            "contract_id": FLEET_CONTRACT_ID,
            "contract_version": FLEET_CONTRACT_VERSION,
            "message_type": "agent-registration-request",
            "installation_id": self.registration.install_id,
            "local_instance_id": identity.local_instance_id,
            "runtime_vendor": self.runtime_vendor,
            "adapter_id": str(self.adapter.adapter_id),
            "adapter_version": str(self.adapter.adapter_version),
            "reported_capabilities": list(
                self.reported_capabilities
            ),
            "required_extensions": [],
        }
        try:
            request = validate_contract_message(payload)
            response = validate_contract_message(
                self._send("/v1/fleet/agents/register", request)
            )
        except FleetContractError as exc:
            raise FleetAgentClientError(str(exc)) from exc
        if response["installation_id"] != identity.installation_id:
            raise FleetAgentClientError(
                "fleet_registration_installation_mismatch"
            )
        if response["local_instance_id"] != identity.local_instance_id:
            raise FleetAgentClientError(
                "fleet_registration_local_instance_mismatch"
            )
        return self.identity_store.bind_agent(
            identity,
            str(response["agent_id"]),
        )

    def heartbeat(
        self,
        identity: FleetAgentIdentity,
        *,
        inventory: RuntimeInventory | None = None,
    ) -> dict[str, Any]:
        if not identity.agent_id:
            raise FleetAgentClientError(
                "fleet_agent_registration_required"
            )
        persisted = self.identity_store.load_or_create(
            self.registration.install_id
        )
        if persisted != identity:
            raise FleetAgentClientError(
                "fleet_heartbeat_local_identity_mismatch"
            )
        if inventory is None:
            try:
                inventory = self.adapter.discover()
            except Exception as exc:
                raise FleetAgentClientError(
                    "fleet_adapter_discovery_failed"
                ) from exc
        if not isinstance(inventory, RuntimeInventory):
            raise FleetAgentClientError(
                "fleet_adapter_inventory_invalid"
            )
        payload = {
            "contract_id": FLEET_CONTRACT_ID,
            "contract_version": FLEET_CONTRACT_VERSION,
            "message_type": "heartbeat-request",
            "agent_id": identity.agent_id,
            "installation_id": identity.installation_id,
            "client_timestamp": utc_now(),
            "runtime_generation": inventory.runtime_generation,
            "active_inventory_digest": inventory.inventory_digest,
            "required_extensions": [],
        }
        try:
            request = validate_contract_message(payload)
            response = validate_contract_message(
                self._send("/v1/fleet/heartbeat", request)
            )
        except FleetContractError as exc:
            raise FleetAgentClientError(str(exc)) from exc
        if response["installation_id"] != identity.installation_id:
            raise FleetAgentClientError(
                "fleet_heartbeat_installation_mismatch"
            )
        if response["agent_id"] != identity.agent_id:
            raise FleetAgentClientError(
                "fleet_heartbeat_agent_mismatch"
            )
        desired = response.get("desired_state")
        if desired is not None:
            try:
                verify_desired_state_signature(
                    desired,
                    public_keys=self.public_keys,
                )
            except FleetContractError as exc:
                raise FleetAgentClientError(str(exc)) from exc
            if desired["agent_id"] != identity.agent_id:
                raise FleetAgentClientError(
                    "fleet_desired_agent_binding_mismatch"
                )
        return response

    def upload_pending_receipts(
        self,
        identity: FleetAgentIdentity,
    ) -> FleetReceiptUploadResult:
        """Upload atomic batches while acknowledging only safe outcomes."""

        persisted = self.identity_store.load_or_create(
            self.registration.install_id
        )
        if persisted != identity or not identity.agent_id:
            raise FleetAgentClientError(
                "fleet_receipt_local_identity_mismatch"
            )
        batch_count = 0
        accepted_count = 0
        duplicate_count = 0
        final_outcome = "accepted"
        while True:
            receipts = self.spool.pending(limit=100)
            if not receipts:
                break
            receipt_bytes = json.dumps(
                receipts,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            batch_id = (
                "batch_"
                + hashlib.sha256(receipt_bytes).hexdigest()[:48]
            )
            payload = {
                "contract_id": FLEET_CONTRACT_ID,
                "contract_version": FLEET_CONTRACT_VERSION,
                "message_type": "receipt-batch",
                "installation_id": identity.installation_id,
                "batch_id": batch_id,
                "receipts": receipts,
                "required_extensions": [],
            }
            try:
                request = validate_contract_message(payload)
                response = validate_contract_message(
                    self._send("/v1/fleet/receipts", request)
                )
            except FleetContractError as exc:
                raise FleetAgentClientError(str(exc)) from exc
            if response["batch_id"] != batch_id:
                raise FleetAgentClientError(
                    "fleet_receipt_batch_response_mismatch"
                )
            sent_ids = {
                str(item["event_id"]) for item in receipts
            }
            accepted_ids = {
                str(item) for item in response["accepted_event_ids"]
            }
            duplicate_ids = {
                str(item) for item in response["duplicate_event_ids"]
            }
            rejected_ids = {
                str(item["event_id"])
                for item in response["rejected_events"]
            }
            returned_ids = (
                accepted_ids | duplicate_ids | rejected_ids
            )
            if (
                not returned_ids <= sent_ids
                or accepted_ids & duplicate_ids
                or accepted_ids & rejected_ids
                or duplicate_ids & rejected_ids
            ):
                raise FleetAgentClientError(
                    "fleet_receipt_response_identity_mismatch"
                )
            outcome = str(response.get("outcome") or "")
            if not outcome:
                outcome = (
                    "rejected"
                    if rejected_ids
                    else (
                        "accepted_duplicate"
                        if duplicate_ids and not accepted_ids
                        else "accepted"
                    )
                )
            final_outcome = outcome
            if outcome in {
                "rejected",
                "conflict",
                "sequence_gap",
                "stale_attempt",
            } or rejected_ids:
                if accepted_ids:
                    raise FleetAgentClientError(
                        "fleet_receipt_atomic_response_invalid"
                    )
                break
            if returned_ids != sent_ids:
                raise FleetAgentClientError(
                    "fleet_receipt_response_incomplete"
                )
            acknowledged = accepted_ids | duplicate_ids
            removed = self.spool.acknowledge(acknowledged)
            if removed != len(acknowledged):
                raise FleetAgentClientError(
                    "fleet_receipt_spool_ack_mismatch"
                )
            batch_count += 1
            accepted_count += len(accepted_ids)
            duplicate_count += len(duplicate_ids)
        return FleetReceiptUploadResult(
            batch_count=batch_count,
            accepted_count=accepted_count,
            duplicate_count=duplicate_count,
            pending_count=len(self.spool.pending(limit=256)),
            outcome=final_outcome,
        )

    def run_once(self) -> FleetAgentRunResult:
        identity = self.register()
        try:
            inventory = self.adapter.discover()
        except Exception as exc:
            raise FleetAgentClientError(
                "fleet_adapter_discovery_failed"
            ) from exc
        response = self.heartbeat(identity, inventory=inventory)
        desired = response.get("desired_state")
        reconcile_result: ReconcileResult | None = None
        receipt_upload: FleetReceiptUploadResult | None = None
        if desired is not None:
            reconciler = FleetReconciler(
                agent_id=identity.agent_id,
                adapter=self.adapter,
                public_keys=self.public_keys,
                state_path=self.reconcile_state_path,
                spool=self.spool,
                client_version=self.client_version,
                auto_activate=self.auto_activate,
            )
            try:
                reconcile_result = reconciler.reconcile(desired)
            except ReconcileError as exc:
                raise FleetAgentClientError(str(exc)) from exc
            try:
                post_inventory = self.adapter.discover()
            except Exception as exc:
                raise FleetAgentClientError(
                    "fleet_adapter_discovery_failed"
                ) from exc
            if not isinstance(post_inventory, RuntimeInventory):
                raise FleetAgentClientError(
                    "fleet_adapter_inventory_invalid"
                )
            response = self.heartbeat(
                identity,
                inventory=post_inventory,
            )
        if self.spool.pending(limit=1):
            receipt_upload = self.upload_pending_receipts(identity)
        return FleetAgentRunResult(
            identity=identity,
            server_timestamp=str(response["server_timestamp"]),
            desired_state_received=desired is not None,
            reconcile_result=reconcile_result,
            receipt_upload=receipt_upload,
        )
