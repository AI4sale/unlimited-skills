from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from unlimited_skills.fleet import (
    FleetContractError,
    FleetPrivacyError,
    ReceiptBuilder,
    ReceiptError,
    ReceiptSpool,
    ReceiptSpoolError,
    assert_receipt_metadata_safe,
    load_contract_document,
    parse_json_strict,
    validate_contract_bundle,
    validate_contract_message,
    validate_desired_state,
    validate_receipt_against_desired,
    verify_desired_state_signature,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "contracts" / "fleet" / "v1"
SCHEMA_FOR_FIXTURE = {
    "agent-registration-request.json": "agent-registration-request.schema.json",
    "agent-registration-response.json": "agent-registration-response.schema.json",
    "desired-state.signed.json": "desired-state.schema.json",
    "heartbeat-request.json": "heartbeat-request.schema.json",
    "heartbeat-response.json": "heartbeat-response.schema.json",
    "receipt-batch.json": "receipt-batch.schema.json",
    "receipt-response.json": "receipt-response.schema.json",
    "receipt-runtime-attested.json": "receipt-event.schema.json",
}


def read_fixture(kind: str, name: str) -> dict:
    return json.loads(
        (CONTRACT_ROOT / "fixtures" / kind / name).read_text(encoding="utf-8")
    )


def schema_registry() -> tuple[dict[str, dict], Registry]:
    schemas = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in CONTRACT_ROOT.glob("*.schema.json")
    }
    registry = Registry().with_resources(
        [
            (schema["$id"], Resource.from_contents(schema))
            for schema in schemas.values()
        ]
    )
    return schemas, registry


def test_contract_bundle_is_hash_pinned_and_complete() -> None:
    result = validate_contract_bundle(CONTRACT_ROOT)

    assert result["contract_id"] == "unlimited-skills.fleet-wire"
    assert result["major_version"] == 1
    assert result["bundle_revision"] == 2
    assert result["manifest_sha256"].startswith("sha256:")
    assert {
        "desired-state.schema.json",
        "receipt-event.schema.json",
        "state-machine.json",
        "signing-contract.json",
        "fixtures/valid/desired-state.signed.json",
        "fixtures/invalid/receipt-client-verified-active.json",
    } <= set(result["verified_files"])


@pytest.mark.parametrize(
    "raw, reason",
    [
        ('{"event_id":"one","event_id":"two"}', "duplicate_json_property"),
        ('{"value":NaN}', "invalid_json_constant"),
    ],
)
def test_strict_json_parser_rejects_ambiguous_or_nonstandard_json(
    raw: str,
    reason: str,
) -> None:
    with pytest.raises(FleetContractError, match=reason):
        parse_json_strict(raw)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "agent-registration-request.json",
        "agent-registration-response.json",
        "desired-state.signed.json",
        "heartbeat-request.json",
        "heartbeat-response.json",
        "receipt-batch.json",
        "receipt-response.json",
        "receipt-runtime-attested.json",
    ],
)
def test_valid_golden_messages_pass_reference_validator(fixture_name: str) -> None:
    payload = read_fixture("valid", fixture_name)
    assert validate_contract_message(payload)["message_type"] == payload["message_type"]


@pytest.mark.parametrize("fixture_name", sorted(SCHEMA_FOR_FIXTURE))
def test_valid_golden_messages_pass_authoritative_json_schema(
    fixture_name: str,
) -> None:
    schemas, registry = schema_registry()
    schema = schemas[SCHEMA_FOR_FIXTURE[fixture_name]]
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(read_fixture("valid", fixture_name))


def test_golden_desired_state_signature_verifies_with_separate_role_key() -> None:
    desired = read_fixture("valid", "desired-state.signed.json")
    signing_contract = load_contract_document("signing-contract.json")
    encoded = signing_contract["golden_fixture"]["public_key"]
    public_key = base64.urlsafe_b64decode(encoded + ("=" * (-len(encoded) % 4)))

    result = verify_desired_state_signature(
        desired,
        public_keys={"fleet-fixture-key-v1": public_key},
    )

    assert result["verified"] is True
    assert result["role"] == "fleet-desired-state-signing"


def test_tampered_desired_state_fails_closed() -> None:
    payload = read_fixture("invalid", "desired-state-tampered.json")

    with pytest.raises(FleetContractError, match="desired_state_digest_mismatch"):
        validate_desired_state(payload)


def test_signed_activation_nonce_is_covered_by_desired_digest() -> None:
    payload = read_fixture(
        "invalid",
        "desired-state-activation-nonce-tampered.json",
    )

    with pytest.raises(
        FleetContractError,
        match="desired_state_digest_mismatch",
    ):
        validate_desired_state(payload)


@pytest.mark.parametrize(
    "fixture_name, reason",
    [
        (
            "receipt-runtime-attestation-nonce-mismatch.json",
            "runtime_attestation_nonce_mismatch",
        ),
        (
            "receipt-runtime-attestation-inventory-mismatch.json",
            "runtime_attestation_inventory_mismatch",
        ),
    ],
)
def test_runtime_attestation_must_match_signed_desired_state(
    fixture_name: str,
    reason: str,
) -> None:
    with pytest.raises(FleetContractError, match=reason):
        validate_receipt_against_desired(
            read_fixture("invalid", fixture_name),
            read_fixture("valid", "desired-state.signed.json"),
        )


def test_expired_desired_state_is_rejected_after_signature_validation() -> None:
    desired = read_fixture("valid", "desired-state.signed.json")
    signing_contract = load_contract_document("signing-contract.json")
    encoded = signing_contract["golden_fixture"]["public_key"]
    public_key = base64.urlsafe_b64decode(encoded + ("=" * (-len(encoded) % 4)))

    with pytest.raises(FleetContractError, match="desired_state_expired"):
        verify_desired_state_signature(
            desired,
            public_keys={"fleet-fixture-key-v1": public_key},
            now=datetime(2100, 1, 1, tzinfo=timezone.utc),
        )


def test_noncanonical_timestamps_fail_closed() -> None:
    heartbeat = read_fixture("valid", "heartbeat-request.json")
    heartbeat["client_timestamp"] = "2026-07-27 00:00:30Z"

    with pytest.raises(FleetContractError, match="invalid_client_timestamp"):
        validate_contract_message(heartbeat)


def test_receipt_response_event_ids_are_unique_across_outcomes() -> None:
    response = read_fixture("valid", "receipt-response.json")
    response["duplicate_event_ids"] = list(response["accepted_event_ids"])

    with pytest.raises(
        FleetContractError,
        match="duplicate_receipt_response_event_id",
    ):
        validate_contract_message(response)


def test_client_cannot_report_server_authority_verified_active() -> None:
    payload = read_fixture("invalid", "receipt-client-verified-active.json")

    with pytest.raises(FleetContractError, match="server_authority_event_forbidden"):
        validate_contract_message(payload)


def test_unknown_required_semantic_and_action_fail_closed() -> None:
    desired = read_fixture("valid", "desired-state.signed.json")
    desired["required_extensions"] = ["fleet.example.required"]
    with pytest.raises(FleetContractError, match="unknown_required_semantic"):
        validate_contract_message(desired)

    desired = read_fixture("valid", "desired-state.signed.json")
    desired["items"][0]["action"] = "execute-shell"
    with pytest.raises(FleetContractError, match="unsupported_action"):
        validate_contract_message(desired)


def test_desired_item_requires_server_issued_attempt_identity() -> None:
    desired = read_fixture("valid", "desired-state.signed.json")
    desired["items"][0].pop("attempt_id")

    with pytest.raises(FleetContractError, match="invalid_items_0_attempt_id"):
        validate_contract_message(desired)


def test_registration_request_cannot_set_operator_labels_or_server_agent_id() -> None:
    payload = read_fixture("valid", "agent-registration-request.json")
    payload["agent_id"] = "agent_client_chosen"
    payload["operator_labels"] = {"environment": "production"}

    with pytest.raises(
        FleetContractError,
        match="operator_managed_registration_field_forbidden",
    ):
        validate_contract_message(payload)

    assert "operator_labels" not in load_contract_document(
        "agent-registration-request.schema.json"
    )["properties"]


def test_receipt_builder_rejects_server_only_states() -> None:
    builder = ReceiptBuilder(
        rollout_id="rollout_1",
        attempt_id="attempt_1",
        agent_id="agent_1",
        desired_state_revision="desired_1",
        desired_state_digest="sha256:" + ("b" * 64),
        control_epoch=1,
        pack_id="pack_1",
        release_id="release_1",
        archive_sha256="sha256:" + ("a" * 64),
        client_version="0.6.9",
        adapter_version="1.0.0",
    )

    with pytest.raises(ReceiptError, match="client_event_type_forbidden"):
        builder.build("VERIFIED_ACTIVE")


def test_receipt_builder_resumes_after_prior_event_sequence() -> None:
    builder = ReceiptBuilder(
        rollout_id="rollout_1",
        attempt_id="attempt_1",
        agent_id="agent_1",
        desired_state_revision="desired_1",
        desired_state_digest="sha256:" + ("b" * 64),
        control_epoch=1,
        pack_id="pack_1",
        release_id="release_1",
        archive_sha256="sha256:" + ("a" * 64),
        client_version="0.6.9",
        adapter_version="1.0.0",
        starting_event_seq=6,
    )

    assert builder.build("DESIRED_SEEN")["event_seq"] == 7


def test_receipt_privacy_allowlist_blocks_paths_secrets_and_nested_metadata() -> None:
    receipt = read_fixture("valid", "receipt-runtime-attested.json")
    assert_receipt_metadata_safe(receipt)

    for key, value in (
        ("local_path", r"C:\Users\alice\.claude"),
        ("prompt", "customer prompt"),
        ("debug", {"stderr": "trace"}),
    ):
        unsafe = dict(receipt)
        unsafe[key] = value
        with pytest.raises(FleetPrivacyError):
            assert_receipt_metadata_safe(unsafe)


def test_receipt_spool_is_atomic_idempotent_and_acknowledgeable(tmp_path: Path) -> None:
    receipt = read_fixture("valid", "receipt-runtime-attested.json")
    spool = ReceiptSpool(tmp_path / "spool")

    first = spool.append(receipt)
    second = spool.append(receipt)

    assert first == second
    assert spool.pending() == [receipt]
    assert spool.acknowledge([receipt["event_id"]]) == 1
    assert spool.pending() == []
    assert spool.last_event_sequence(receipt["attempt_id"]) == receipt["event_seq"]


def test_receipt_spool_rejects_same_event_id_with_different_body(tmp_path: Path) -> None:
    receipt = read_fixture("valid", "receipt-runtime-attested.json")
    spool = ReceiptSpool(tmp_path / "spool")
    spool.append(receipt)
    conflicting = dict(receipt)
    conflicting["event_seq"] = 8

    with pytest.raises(ReceiptSpoolError, match="event_id_collision"):
        spool.append(conflicting)


def test_receipt_spool_orders_each_attempt_by_event_sequence(tmp_path: Path) -> None:
    template = read_fixture("valid", "receipt-runtime-attested.json")
    earlier = dict(template)
    earlier["event_id"] = "evt_z_late_filename"
    earlier["idempotency_key"] = earlier["event_id"]
    earlier["event_seq"] = 1
    earlier["event_type"] = "DESIRED_SEEN"
    earlier["runtime_generation"] = ""
    earlier["activation_nonce"] = ""
    earlier["active_archive_sha256"] = ""
    earlier.pop("runtime_attestation")
    later = dict(template)
    later["event_id"] = "evt_a_early_filename"
    later["idempotency_key"] = later["event_id"]
    later["event_seq"] = 2
    later["event_type"] = "MANIFEST_VERIFIED"
    later["runtime_generation"] = ""
    later["activation_nonce"] = ""
    later["active_archive_sha256"] = ""
    later.pop("runtime_attestation")
    spool = ReceiptSpool(tmp_path / "spool")
    spool.append(later)
    spool.append(earlier)

    assert [item["event_seq"] for item in spool.pending()] == [1, 2]
