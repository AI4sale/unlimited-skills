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
    ManagedFleetAdapterError,
    ReceiptSpool,
    ReconcileError,
    RuntimeAttestation,
    RuntimeInventory,
    RuntimeInventoryAttestation,
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
        self.install_items: list[dict[str, Any]] = []

    def discover(self) -> RuntimeInventory:
        return RuntimeInventory(
            runtime_generation="generation_fixture_01",
            active_revisions={},
            inventory_digest="sha256:" + ("d" * 64),
        )

    def install_revision(self, item: Mapping[str, Any]) -> InstalledRevision:
        self.install_items.append(dict(item))
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


class BundleFakeAdapter(FakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.bundle_activations = 0
        self.bundle_items: list[str] = []
        self.call_log: list[str] = []

    def install_revision(self, item: Mapping[str, Any]) -> InstalledRevision:
        self.call_log.append(f"install:{item['pack_id']}")
        return super().install_revision(item)

    def verify_revision(
        self,
        item: Mapping[str, Any],
        installed: InstalledRevision,
    ) -> None:
        self.call_log.append(f"verify:{item['pack_id']}")
        super().verify_revision(item, installed)

    def activate_inventory(
        self,
        items: list[Mapping[str, Any]],
        installed: Mapping[str, InstalledRevision],
        *,
        activation_nonces: Mapping[str, str],
    ) -> None:
        self.call_log.append("activate-inventory")
        self.bundle_activations += 1
        self.bundle_items = [str(item["pack_id"]) for item in items]
        assert set(installed) == set(self.bundle_items)
        assert set(activation_nonces) == set(self.bundle_items)

    def attest_inventory(
        self,
        items: list[Mapping[str, Any]],
        *,
        activation_nonces: Mapping[str, str],
    ) -> RuntimeInventoryAttestation:
        self.call_log.append("attest-inventory")
        return RuntimeInventoryAttestation(
            runtime_generation="generation_fixture_bundle_02",
            activation_nonces=dict(activation_nonces),
            active_revisions={
                str(item["pack_id"]): str(item["release_id"])
                for item in items
            },
            active_archive_sha256={
                str(item["pack_id"]): str(item["archive_sha256"])
                for item in items
            },
            active_inventory_digest="sha256:" + ("d" * 64),
            adapter_version=self.adapter_version,
        )

    def detect_inventory_drift(
        self,
        items: list[Mapping[str, Any]],
    ) -> bool:
        self.call_log.append("detect-inventory-drift")
        return self.drifted


class PartialFailureBundleAdapter(BundleFakeAdapter):
    def install_revision(
        self,
        item: Mapping[str, Any],
    ) -> InstalledRevision:
        installed = super().install_revision(item)
        if item["pack_id"] == "pack_fixture_b":
            return InstalledRevision(
                pack_id=installed.pack_id,
                release_id="release_wrong",
                version=installed.version,
                archive_sha256=installed.archive_sha256,
                install_committed=True,
            )
        return installed


class TerminalActivationBundleAdapter(BundleFakeAdapter):
    def activate_inventory(
        self,
        items: list[Mapping[str, Any]],
        installed: Mapping[str, InstalledRevision],
        *,
        activation_nonces: Mapping[str, str],
    ) -> None:
        del items, installed, activation_nonces
        raise ManagedFleetAdapterError("managed_skill_collision")


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
    assert adapter.install_items[0]["agent_id"] == (
        VALID_DESIRED["agent_id"]
    )
    assert adapter.install_items[0]["rollout_id"] == (
        VALID_DESIRED["rollout_id"]
    )
    assert adapter.install_items[0]["desired_state_revision"] == (
        VALID_DESIRED["desired_state_revision"]
    )
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


def two_pack_desired_state() -> dict[str, Any]:
    desired = copy.deepcopy(VALID_DESIRED)
    desired["desired_state_revision"] = "ds_fixture_two_packs"
    desired["rollout_id"] = "rollout_fixture_two_packs"
    desired["items"][0]["attempt_id"] = "attempt_fixture_pack_a"
    desired["items"].append(
        {
            "attempt_id": "attempt_fixture_pack_b",
            "pack_id": "pack_fixture_b",
            "release_id": "release_fixture_b",
            "version": "2.0.0",
            "archive_sha256": "sha256:" + ("b" * 64),
            "activation_nonce": "nonce_fixture_pack_b",
            "manifest_ref": (
                "registry:private-pack/pack_fixture_b/release_fixture_b"
            ),
            "required": True,
            "action": "activate",
        }
    )
    return sign_desired(desired)


def test_reconciler_activates_multi_pack_inventory_once_after_all_verification(
    tmp_path: Path,
) -> None:
    adapter = BundleFakeAdapter()

    result = reconciler(tmp_path, adapter).reconcile(
        two_pack_desired_state()
    )

    assert adapter.bundle_activations == 1
    assert adapter.activations == 0
    assert adapter.bundle_items == ["pack_fixture", "pack_fixture_b"]
    assert adapter.call_log == [
        "install:pack_fixture",
        "verify:pack_fixture",
        "install:pack_fixture_b",
        "verify:pack_fixture_b",
        "activate-inventory",
        "attest-inventory",
        "detect-inventory-drift",
    ]
    assert [
        (row["attempt_id"], row["event_type"])
        for row in result.receipts
        if row["event_type"] in {"ACTIVATION_PENDING", "RUNTIME_ATTESTED"}
    ] == [
        ("attempt_fixture_pack_a", "ACTIVATION_PENDING"),
        ("attempt_fixture_pack_b", "ACTIVATION_PENDING"),
        ("attempt_fixture_pack_a", "RUNTIME_ATTESTED"),
        ("attempt_fixture_pack_b", "RUNTIME_ATTESTED"),
    ]
    assert result.activation_pending is False


def test_reconciler_rejects_multi_pack_for_legacy_single_item_adapter(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter()

    with pytest.raises(
        ReconcileError,
        match="adapter_inventory_activation_required",
    ):
        reconciler(tmp_path, adapter).reconcile(two_pack_desired_state())

    assert adapter.activations == 0
    assert adapter.rollbacks == 0


def test_partial_bundle_install_failure_never_activates_and_receipts_validate(
    tmp_path: Path,
) -> None:
    adapter = PartialFailureBundleAdapter()

    result = reconciler(tmp_path, adapter).reconcile(
        two_pack_desired_state()
    )

    assert adapter.bundle_activations == 0
    assert result.activation_pending is True
    assert any(
        row["attempt_id"] == "attempt_fixture_pack_b"
        and row["event_type"] == "FAILED_TERMINAL"
        and row["reason_code"] == "install_failed"
        for row in result.receipts
    )
    assert any(
        row["attempt_id"] == "attempt_fixture_pack_a"
        and row["event_type"] == "ACTIVATION_PENDING"
        and row["reason_code"] == "install_failed"
        for row in result.receipts
    )


def test_terminal_adapter_policy_failure_is_not_reported_retryable(
    tmp_path: Path,
) -> None:
    adapter = TerminalActivationBundleAdapter()

    result = reconciler(tmp_path, adapter).reconcile(
        two_pack_desired_state()
    )

    failures = [
        row
        for row in result.receipts
        if row["event_type"].startswith("FAILED_")
    ]
    assert len(failures) == 2
    assert {
        (row["event_type"], row["reason_code"])
        for row in failures
    } == {("FAILED_TERMINAL", "install_failed")}
    assert "attest-inventory" not in adapter.call_log
