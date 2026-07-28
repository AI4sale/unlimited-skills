from __future__ import annotations

import base64
import copy
import hashlib
import json
import urllib.error
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.fleet import (
    FleetAgentClient,
    FleetAgentClientError,
    FleetAgentIdentityStore,
    InstalledRevision,
    ReceiptSpool,
    RuntimeAttestation,
    RuntimeInventory,
    canonical_desired_state_bytes,
    desired_state_digest,
)
from unlimited_skills import __version__
from unlimited_skills.commands.fleet import (
    FLEET_CLIENT_VERSION_CAPABILITY,
    FLEET_PAYLOAD_CAPABILITY,
)
from unlimited_skills.registration import (
    RegistrationState,
    base64_urlsafe_decode,
    with_install_identity,
)
from unlimited_skills.service_client import ServiceClientError, request_json


ROOT = Path(__file__).resolve().parents[1]
VALID_DESIRED = json.loads(
    (
        ROOT
        / "contracts"
        / "fleet"
        / "v1"
        / "fixtures"
        / "valid"
        / "desired-state.signed.json"
    ).read_text(encoding="utf-8")
)
FIXTURE_SEED = bytes(range(1, 33))


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(
            install_id="uls_inst_fleet_client",
            server_url="https://registry.example.test",
            plan="business",
            license_token="tok_fleet_client",
            features_enabled=("fleet_control_plane",),
        )
    )


def registration_response(
    *,
    local_instance_id: str,
    agent_id: str = "agent_fleet_client_01",
    installation_id: str = "uls_inst_fleet_client",
) -> dict[str, Any]:
    return {
        "contract_id": "unlimited-skills.fleet-wire",
        "contract_version": 1,
        "message_type": "agent-registration-response",
        "agent_id": agent_id,
        "installation_id": installation_id,
        "local_instance_id": local_instance_id,
        "server_timestamp": "2026-07-27T12:00:00Z",
    }


def heartbeat_response(
    *,
    desired_state: dict[str, Any] | None,
    agent_id: str = "agent_fleet_client_01",
    installation_id: str = "uls_inst_fleet_client",
) -> dict[str, Any]:
    return {
        "contract_id": "unlimited-skills.fleet-wire",
        "contract_version": 1,
        "message_type": "heartbeat-response",
        "agent_id": agent_id,
        "installation_id": installation_id,
        "server_timestamp": "2026-07-27T12:00:01Z",
        "desired_state": desired_state,
    }


def receipt_response(
    batch: Mapping[str, Any],
    *,
    outcome: str = "accepted",
    accepted_event_ids: list[str] | None = None,
    duplicate_event_ids: list[str] | None = None,
    rejected_events: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "contract_id": "unlimited-skills.fleet-wire",
        "contract_version": 1,
        "message_type": "receipt-response",
        "batch_id": str(batch["batch_id"]),
        "server_timestamp": "2026-07-27T12:00:02Z",
        "accepted_event_ids": (
            accepted_event_ids
            if accepted_event_ids is not None
            else [
                str(item["event_id"])
                for item in batch["receipts"]
            ]
        ),
        "duplicate_event_ids": duplicate_event_ids or [],
        "rejected_events": rejected_events or [],
        "outcome": outcome,
    }


def sign_desired_for_agent(agent_id: str) -> dict[str, Any]:
    private_key = Ed25519PrivateKey.from_private_bytes(FIXTURE_SEED)
    desired = copy.deepcopy(VALID_DESIRED)
    desired["agent_id"] = agent_id
    desired.pop("desired_state_signature", None)
    desired["desired_state_digest"] = desired_state_digest(desired)
    body = canonical_desired_state_bytes(desired)
    desired["desired_state_signature"] = {
        "algorithm": "ed25519",
        "key_id": "fleet-fixture-key-v1",
        "role": "fleet-desired-state-signing",
        "schema_version": 1,
        "signature": b64url(private_key.sign(body)),
        "signed_payload_sha256": (
            "sha256:" + hashlib.sha256(body).hexdigest()
        ),
    }
    return desired


class FakeAdapter:
    adapter_id = "codex"
    adapter_version = "1.0.0"

    def __init__(self) -> None:
        self.activated = False

    def discover(self) -> RuntimeInventory:
        return RuntimeInventory(
            runtime_generation=(
                "generation_fleet_client_post"
                if self.activated
                else "generation_fleet_client_pre"
            ),
            active_revisions={},
            inventory_digest="sha256:" + ("d" * 64),
        )

    def install_revision(
        self,
        item: Mapping[str, Any],
    ) -> InstalledRevision:
        return InstalledRevision(
            pack_id=str(item["pack_id"]),
            release_id=str(item["release_id"]),
            version=str(item["version"]),
            archive_sha256=str(item["archive_sha256"]),
            install_committed=True,
        )

    def verify_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
    ) -> None:
        assert installed.archive_sha256 == item["archive_sha256"]

    def activate_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
        *,
        activation_nonce: str,
    ) -> None:
        self.activated = True

    def attest_runtime(
        self,
        item: Mapping[str, Any],
        *,
        activation_nonce: str,
    ) -> RuntimeAttestation:
        return RuntimeAttestation(
            runtime_generation="generation_fleet_client_post",
            activation_nonce=activation_nonce,
            pack_id=str(item["pack_id"]),
            release_id=str(item["release_id"]),
            active_archive_sha256=str(item["archive_sha256"]),
            active_inventory_digest="sha256:" + ("d" * 64),
            adapter_version=self.adapter_version,
        )

    def detect_drift(self, item: Mapping[str, Any]) -> bool:
        return False

    def rollback_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
        *,
        activation_nonce: str,
    ) -> None:
        return None


def public_keys() -> dict[str, bytes]:
    private_key = Ed25519PrivateKey.from_private_bytes(FIXTURE_SEED)
    return {
        "fleet-fixture-key-v1": private_key.public_key().public_bytes(
            Encoding.Raw,
            PublicFormat.Raw,
        )
    }


def client(
    tmp_path: Path,
    transport,
    *,
    keys: Mapping[str, bytes] | None = None,
) -> FleetAgentClient:
    return FleetAgentClient(
        registration=registered_state(),
        runtime_vendor="codex",
        adapter=FakeAdapter(),
        identity_store=FleetAgentIdentityStore(
            tmp_path / "agent-identity.json"
        ),
        public_keys=keys if keys is not None else public_keys(),
        reconcile_state_path=tmp_path / "reconcile-state.json",
        spool=ReceiptSpool(tmp_path / "receipts"),
        client_version="0.6.9",
        reported_capabilities=(
            "desired-state-v1",
            "receipt-spool-v1",
        ),
        organization_id="org_fleet_client",
        auto_activate=True,
        transport=transport,
    )


def test_fcp008c_client_capabilities_are_exact_and_version_bound() -> None:
    assert FLEET_PAYLOAD_CAPABILITY == "fleet-payload-v2"
    assert FLEET_CLIENT_VERSION_CAPABILITY == (
        f"client-version-{__version__}"
    )
    assert __version__ == "0.6.9rc2"


def test_local_instance_uuid4_is_created_once_under_concurrency(
    tmp_path: Path,
) -> None:
    store = FleetAgentIdentityStore(tmp_path / "agent-identity.json")

    with ThreadPoolExecutor(max_workers=12) as pool:
        identities = list(
            pool.map(
                lambda _: store.load_or_create("uls_inst_fleet_client"),
                range(48),
            )
        )

    values = {item.local_instance_id for item in identities}
    assert len(values) == 1
    parsed = uuid.UUID(values.pop())
    assert parsed.version == 4
    persisted = json.loads(
        (tmp_path / "agent-identity.json").read_text(encoding="utf-8")
    )
    assert persisted == {
        "agent_id": "",
        "installation_id": "uls_inst_fleet_client",
        "local_instance_id": str(parsed),
        "schema_version": 1,
    }


def test_registration_persists_uuid_before_network_and_is_idempotent(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    def transport(state, path, payload, **kwargs):
        calls.append({"path": path, "payload": dict(payload)})
        if len(calls) == 1:
            raise FleetAgentClientError("network_offline")
        return registration_response(
            local_instance_id=str(payload["local_instance_id"])
        )

    instance = client(tmp_path, transport)
    with pytest.raises(FleetAgentClientError, match="network_offline"):
        instance.register()

    persisted_before_retry = json.loads(
        (tmp_path / "agent-identity.json").read_text(encoding="utf-8")
    )
    assert persisted_before_retry["agent_id"] == ""
    local_instance_id = persisted_before_retry["local_instance_id"]

    first = instance.register()
    second = instance.register()

    assert first == second
    assert first.agent_id == "agent_fleet_client_01"
    assert first.local_instance_id == local_instance_id
    assert {
        call["payload"]["local_instance_id"] for call in calls
    } == {local_instance_id}
    assert all(
        "agent_id" not in call["payload"]
        and "labels" not in call["payload"]
        and "environment" not in call["payload"]
        for call in calls
    )


def test_default_transport_binds_device_proof_to_exact_body_and_org(
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def request_json(url, *, body, headers, **kwargs):
        captured.update(
            {
                "url": url,
                "body": body,
                "headers": dict(headers),
                "kwargs": kwargs,
            }
        )
        payload = json.loads(body)
        return registration_response(
            local_instance_id=str(payload["local_instance_id"])
        )

    instance = FleetAgentClient(
        registration=registered_state(),
        runtime_vendor="codex",
        adapter=FakeAdapter(),
        identity_store=FleetAgentIdentityStore(
            tmp_path / "agent-identity.json"
        ),
        public_keys=public_keys(),
        reconcile_state_path=tmp_path / "reconcile-state.json",
        spool=ReceiptSpool(tmp_path / "receipts"),
        client_version="0.6.9",
        organization_id="org_fleet_client",
    )
    with patch(
        "unlimited_skills.fleet.client.request_json",
        request_json,
    ):
        instance.register()

    assert captured["url"].endswith("/v1/fleet/agents/register")
    assert captured["headers"]["Authorization"] == (
        "Bearer tok_fleet_client"
    )
    assert captured["headers"]["X-ULS-Organization"] == (
        "org_fleet_client"
    )
    encoded_proof = captured["headers"]["X-ULS-Proof"]
    proof = json.loads(base64_urlsafe_decode(encoded_proof))
    assert proof["install_id"] == "uls_inst_fleet_client"
    assert proof["body_sha256"] == hashlib.sha256(
        captured["body"]
    ).hexdigest()
    assert captured["kwargs"]["retry_safe"] is True
    assert captured["kwargs"]["max_response_bytes"] == 256 * 1024
    assert callable(captured["kwargs"]["headers_factory"])


def test_retry_refreshes_device_proof_nonce_for_the_same_body(
    tmp_path: Path,
) -> None:
    state = registered_state()
    proofs: list[dict[str, Any]] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size: int = -1) -> bytes:
            return b'{"status":"ok"}'

    def urlopen(request, timeout):
        encoded = request.get_header("X-uls-proof")
        proofs.append(
            json.loads(base64_urlsafe_decode(str(encoded)))
        )
        if len(proofs) == 1:
            raise urllib.error.URLError("temporary offline")
        return Response()

    body = b'{"contract_id":"unlimited-skills.fleet-wire"}'

    def headers_factory() -> dict[str, str]:
        from unlimited_skills.registration import proof_headers

        return proof_headers(
            state,
            "POST",
            "https://registry.example.test/v1/fleet/heartbeat",
            body,
        )

    with (
        patch(
            "unlimited_skills.service_client.urllib.request.urlopen",
            urlopen,
        ),
        patch("unlimited_skills.service_client.time.sleep"),
    ):
        response = request_json(
            "https://registry.example.test/v1/fleet/heartbeat",
            body=body,
            headers=headers_factory(),
            retry_safe=True,
            max_retries=1,
            headers_factory=headers_factory,
        )

    assert response == {"status": "ok"}
    assert len(proofs) == 2
    assert proofs[0]["nonce"] != proofs[1]["nonce"]
    assert {
        proof["body_sha256"] for proof in proofs
    } == {hashlib.sha256(body).hexdigest()}


def test_fleet_response_size_limit_fails_closed() -> None:
    class OversizedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size: int = -1) -> bytes:
            return b"x" * size

    with patch(
        "unlimited_skills.service_client.urllib.request.urlopen",
        return_value=OversizedResponse(),
    ):
        with pytest.raises(
            ServiceClientError,
            match="response exceeded the configured size limit",
        ):
            request_json(
                "https://registry.example.test/v1/fleet/heartbeat",
                body=b"{}",
                headers={},
                max_response_bytes=64,
            )


def test_run_once_registers_heartbeats_and_reconciles_signed_desired(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    def transport(state, path, payload, **kwargs):
        calls.append({"path": path, "payload": copy.deepcopy(payload)})
        if path == "/v1/fleet/agents/register":
            return registration_response(
                local_instance_id=str(payload["local_instance_id"])
            )
        if path == "/v1/fleet/heartbeat":
            return heartbeat_response(
                desired_state=sign_desired_for_agent(
                    "agent_fleet_client_01"
                )
            )
        if path == "/v1/fleet/receipts":
            return receipt_response(payload)
        raise AssertionError(path)

    result = client(tmp_path, transport).run_once()

    assert result.identity.agent_id == "agent_fleet_client_01"
    assert result.desired_state_received is True
    assert result.reconcile_result is not None
    event_types = [
        receipt["event_type"]
        for receipt in result.reconcile_result.receipts
    ]
    assert event_types[-1] == "RUNTIME_ATTESTED"
    assert "VERIFIED_ACTIVE" not in event_types
    heartbeat = calls[1]["payload"]
    assert heartbeat["message_type"] == "heartbeat-request"
    assert heartbeat["runtime_generation"] == (
        "generation_fleet_client_pre"
    )
    assert heartbeat["active_inventory_digest"].startswith("sha256:")
    assert not {
        "installed",
        "active",
        "verified_active",
        "compliant",
        "receipts",
    } & set(heartbeat)
    assert calls[2]["path"] == "/v1/fleet/heartbeat"
    assert calls[2]["payload"]["runtime_generation"] == (
        "generation_fleet_client_post"
    )
    assert calls[3]["path"] == "/v1/fleet/receipts"
    assert result.receipt_upload is not None
    assert result.receipt_upload.accepted_count == 6
    assert result.receipt_upload.pending_count == 0


def test_atomic_receipt_rejection_keeps_the_entire_spool(
    tmp_path: Path,
) -> None:
    receipt_batches: list[dict[str, Any]] = []

    def transport(state, path, payload, **kwargs):
        if path == "/v1/fleet/agents/register":
            return registration_response(
                local_instance_id=str(payload["local_instance_id"])
            )
        if path == "/v1/fleet/heartbeat":
            return heartbeat_response(
                desired_state=sign_desired_for_agent(
                    "agent_fleet_client_01"
                )
            )
        if path == "/v1/fleet/receipts":
            receipt_batches.append(copy.deepcopy(payload))
            failed = payload["receipts"][3]
            return receipt_response(
                payload,
                outcome="sequence_gap",
                accepted_event_ids=[],
                rejected_events=[
                    {
                        "event_id": failed["event_id"],
                        "reason_code": "invalid_event_sequence",
                    }
                ],
            ) | {
                "first_failed_event_index": 3,
                "expected_next_sequence": 4,
            }
        raise AssertionError(path)

    instance = client(tmp_path, transport)
    result = instance.run_once()

    assert len(receipt_batches) == 1
    assert result.receipt_upload is not None
    assert result.receipt_upload.outcome == "sequence_gap"
    assert result.receipt_upload.accepted_count == 0
    assert result.receipt_upload.pending_count == 6
    assert len(instance.spool.pending()) == 6


def test_receipt_upload_chunks_at_100_and_acks_duplicates(
    tmp_path: Path,
) -> None:
    batches: list[dict[str, Any]] = []

    def transport(state, path, payload, **kwargs):
        assert path == "/v1/fleet/receipts"
        batches.append(copy.deepcopy(payload))
        ids = [
            str(item["event_id"]) for item in payload["receipts"]
        ]
        return receipt_response(
            payload,
            outcome="accepted_duplicate",
            accepted_event_ids=[],
            duplicate_event_ids=ids,
        )

    instance = client(tmp_path, transport)
    template = copy.deepcopy(
        json.loads(
            (
                ROOT
                / "contracts"
                / "fleet"
                / "v1"
                / "fixtures"
                / "valid"
                / "receipt-runtime-attested.json"
            ).read_text(encoding="utf-8")
        )
    )
    for index in range(201):
        receipt = copy.deepcopy(template)
        receipt["event_id"] = f"evt_chunk_{index:04d}"
        receipt["idempotency_key"] = receipt["event_id"]
        receipt["attempt_id"] = f"attempt_chunk_{index:04d}"
        instance.spool.append(receipt)

    identity = instance.identity_store.bind_agent(
        instance.identity_store.load_or_create(
            "uls_inst_fleet_client"
        ),
        "agent_fleet_client_01",
    )
    result = instance.upload_pending_receipts(identity)

    assert [len(batch["receipts"]) for batch in batches] == [
        100,
        100,
        1,
    ]
    assert len({batch["batch_id"] for batch in batches}) == 3
    assert result.accepted_count == 0
    assert result.duplicate_count == 201
    assert result.pending_count == 0
    assert instance.spool.pending() == []


@pytest.mark.parametrize(
    "mutation, reason",
    [
        (
            lambda response: response.update(
                {"installation_id": "uls_inst_other"}
            ),
            "fleet_registration_installation_mismatch",
        ),
        (
            lambda response: response.update(
                {"local_instance_id": str(uuid.uuid4())}
            ),
            "fleet_registration_local_instance_mismatch",
        ),
    ],
)
def test_registration_binding_mismatch_never_overwrites_identity(
    tmp_path: Path,
    mutation,
    reason: str,
) -> None:
    def transport(state, path, payload, **kwargs):
        response = registration_response(
            local_instance_id=str(payload["local_instance_id"])
        )
        mutation(response)
        return response

    instance = client(tmp_path, transport)
    with pytest.raises(FleetAgentClientError, match=reason):
        instance.register()

    persisted = json.loads(
        (tmp_path / "agent-identity.json").read_text(encoding="utf-8")
    )
    assert persisted["agent_id"] == ""


def test_heartbeat_rejects_untrusted_or_cross_agent_desired_state(
    tmp_path: Path,
) -> None:
    desired = sign_desired_for_agent("agent_other")

    def transport(state, path, payload, **kwargs):
        if path == "/v1/fleet/agents/register":
            return registration_response(
                local_instance_id=str(payload["local_instance_id"])
            )
        return heartbeat_response(desired_state=desired)

    with pytest.raises(
        FleetAgentClientError,
        match="fleet_desired_agent_binding_mismatch",
    ):
        client(tmp_path, transport).run_once()

    trusted_desired = sign_desired_for_agent("agent_fleet_client_01")

    def untrusted_transport(state, path, payload, **kwargs):
        if path == "/v1/fleet/agents/register":
            return registration_response(
                local_instance_id=str(payload["local_instance_id"])
            )
        return heartbeat_response(desired_state=trusted_desired)

    with pytest.raises(
        FleetAgentClientError,
        match="untrusted_desired_state_key",
    ):
        client(
            tmp_path / "second",
            untrusted_transport,
            keys={},
        ).run_once()


def test_heartbeat_requires_the_persisted_bound_identity(
    tmp_path: Path,
) -> None:
    def transport(state, path, payload, **kwargs):
        return registration_response(
            local_instance_id=str(payload["local_instance_id"])
        )

    instance = client(tmp_path, transport)
    identity = instance.register()
    forged = type(identity)(
        installation_id=identity.installation_id,
        local_instance_id=identity.local_instance_id,
        agent_id="agent_forged",
    )

    with pytest.raises(
        FleetAgentClientError,
        match="fleet_heartbeat_local_identity_mismatch",
    ):
        instance.heartbeat(forged)


def test_corrupt_or_other_install_identity_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agent-identity.json"
    path.write_text("{not-json", encoding="utf-8")
    store = FleetAgentIdentityStore(path)
    with pytest.raises(
        FleetAgentClientError,
        match="fleet_agent_identity_invalid",
    ):
        store.load_or_create("uls_inst_fleet_client")

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "installation_id": "uls_inst_other",
                "local_instance_id": str(uuid.uuid4()),
                "agent_id": "",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        FleetAgentClientError,
        match="fleet_agent_identity_installation_mismatch",
    ):
        store.load_or_create("uls_inst_fleet_client")
