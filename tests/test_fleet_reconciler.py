from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.fleet import (
    FleetReconciler,
    InstalledRevision,
    ReceiptSpool,
    ReconcileError,
    RuntimeAttestation,
    RuntimeInventory,
    canonical_desired_state_bytes,
    canonical_json_bytes,
    desired_state_digest,
)


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


def sign_desired(payload: dict[str, Any]) -> dict[str, Any]:
    private_key = Ed25519PrivateKey.from_private_bytes(FIXTURE_SEED)
    signed = copy.deepcopy(payload)
    signed.pop("desired_state_signature", None)
    signed["desired_state_digest"] = desired_state_digest(signed)
    body = canonical_desired_state_bytes(signed)
    signed["desired_state_signature"] = {
        "algorithm": "ed25519",
        "key_id": "fleet-fixture-key-v1",
        "role": "fleet-desired-state-signing",
        "schema_version": 1,
        "signature": b64url(private_key.sign(body)),
        "signed_payload_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
    }
    return signed


class FakeAdapter:
    adapter_id = "claude-code"
    adapter_version = "1.0.0"

    def __init__(self) -> None:
        self.activations = 0
        self.rollbacks = 0
        self.drifted = False
        self.last_nonce = ""
        self.installed_release_override = ""
        self.attested_adapter_override = ""

    def discover(self) -> RuntimeInventory:
        return RuntimeInventory(
            runtime_generation="generation_fixture_01",
            active_revisions={},
            inventory_digest="sha256:" + ("d" * 64),
        )

    def install_revision(self, item: Mapping[str, Any]) -> InstalledRevision:
        return InstalledRevision(
            pack_id=str(item["pack_id"]),
            release_id=self.installed_release_override or str(item["release_id"]),
            version=str(item["version"]),
            archive_sha256=str(item["archive_sha256"]),
            install_committed=True,
        )

    def verify_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
    ) -> None:
        assert installed.pack_id == item["pack_id"]

    def activate_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
        *,
        activation_nonce: str,
    ) -> None:
        self.activations += 1
        self.last_nonce = activation_nonce

    def attest_runtime(
        self,
        item: Mapping[str, Any],
        *,
        activation_nonce: str,
    ) -> RuntimeAttestation:
        return RuntimeAttestation(
            runtime_generation="generation_fixture_02",
            activation_nonce=activation_nonce,
            pack_id=str(item["pack_id"]),
            release_id=str(item["release_id"]),
            active_archive_sha256=str(item["archive_sha256"]),
            active_inventory_digest="sha256:" + ("d" * 64),
            adapter_version=self.attested_adapter_override or self.adapter_version,
        )

    def detect_drift(self, item: Mapping[str, Any]) -> bool:
        return self.drifted

    def rollback_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
        *,
        activation_nonce: str,
    ) -> None:
        self.rollbacks += 1
        self.last_nonce = activation_nonce


def reconciler(tmp_path: Path, adapter: FakeAdapter) -> FleetReconciler:
    private_key = Ed25519PrivateKey.from_private_bytes(FIXTURE_SEED)
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return FleetReconciler(
        agent_id="agent_fixture_01",
        adapter=adapter,
        public_keys={"fleet-fixture-key-v1": public_key},
        state_path=tmp_path / "fleet-state.json",
        spool=ReceiptSpool(tmp_path / "receipts"),
        client_version="0.6.9",
        auto_activate=True,
    )


def test_reconciler_emits_runtime_proof_but_never_verified_active(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    result = reconciler(tmp_path, adapter).reconcile(VALID_DESIRED)

    event_types = [item["event_type"] for item in result.receipts]
    assert event_types == [
        "DESIRED_SEEN",
        "MANIFEST_VERIFIED",
        "ARTIFACT_VERIFIED",
        "INSTALL_COMMITTED",
        "ACTIVATION_PENDING",
        "RUNTIME_ATTESTED",
    ]
    assert "VERIFIED_ACTIVE" not in event_types
    assert {
        item["attempt_id"] for item in result.receipts
    } == {"attempt_fixture_01"}
    assert adapter.activations == 1
    assert result.activation_pending is False
    state = json.loads((tmp_path / "fleet-state.json").read_text(encoding="utf-8"))
    assert state["control_epoch"] == 7


def test_reconciler_rejects_lower_epoch_even_when_resigned(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    instance = reconciler(tmp_path, adapter)
    instance.reconcile(VALID_DESIRED)
    stale = copy.deepcopy(VALID_DESIRED)
    stale["control_epoch"] = 6
    stale["desired_state_revision"] = "ds_fixture_stale"
    stale = sign_desired(stale)

    with pytest.raises(ReconcileError, match="stale_control_epoch"):
        instance.reconcile(stale)


def test_rollback_is_a_new_higher_epoch_signed_rollout(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    instance = reconciler(tmp_path, adapter)
    instance.reconcile(VALID_DESIRED)
    rollback = copy.deepcopy(VALID_DESIRED)
    rollback["control_epoch"] = 8
    rollback["desired_state_revision"] = "ds_fixture_rollback_a"
    rollback["rollout_id"] = "rollout_fixture_rollback_a"
    rollback["previous_digest"] = VALID_DESIRED["desired_state_digest"]
    rollback["items"][0]["attempt_id"] = "attempt_fixture_rollback_a"
    rollback["items"][0]["action"] = "rollback"
    rollback["items"][0]["release_id"] = "release_a"
    rollback["items"][0]["version"] = "1.0.0"
    rollback["items"][0]["archive_sha256"] = "sha256:" + ("a" * 64)
    rollback = sign_desired(rollback)

    result = instance.reconcile(rollback)

    assert adapter.rollbacks == 1
    assert result.control_epoch == 8
    assert result.receipts[-1]["event_type"] == "RUNTIME_ATTESTED"


def test_canonical_json_forbids_floats() -> None:
    with pytest.raises(Exception, match="float_not_allowed"):
        canonical_json_bytes({"latency": 1.5})


def test_auto_activation_defaults_off(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.from_private_bytes(FIXTURE_SEED)
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    adapter = FakeAdapter()
    instance = FleetReconciler(
        agent_id="agent_fixture_01",
        adapter=adapter,
        public_keys={"fleet-fixture-key-v1": public_key},
        state_path=tmp_path / "fleet-state.json",
        spool=ReceiptSpool(tmp_path / "receipts"),
        client_version="0.6.9",
        auto_activate=False,
    )

    result = instance.reconcile(VALID_DESIRED)

    assert result.activation_pending is True
    assert result.receipts[-1]["event_type"] == "ACTIVATION_PENDING"
    assert adapter.activations == 0


@pytest.mark.parametrize(
    "adapter_field, value",
    [
        ("installed_release_override", "release_wrong"),
        ("attested_adapter_override", "adapter_wrong"),
    ],
)
def test_reconciler_fails_closed_on_adapter_identity_mismatch(
    tmp_path: Path,
    adapter_field: str,
    value: str,
) -> None:
    adapter = FakeAdapter()
    setattr(adapter, adapter_field, value)

    result = reconciler(tmp_path, adapter).reconcile(VALID_DESIRED)

    assert result.activation_pending is True
    assert result.receipts[-1]["event_type"] == "FAILED_TERMINAL"


def test_global_fleet_disable_blocks_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FakeAdapter()
    monkeypatch.setenv("UNLIMITED_SKILLS_FLEET_DISABLE", "1")

    with pytest.raises(ReconcileError, match="fleet_reconciliation_disabled"):
        reconciler(tmp_path, adapter).reconcile(VALID_DESIRED)

    assert adapter.activations == 0
