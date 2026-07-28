from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "contracts" / "fleet" / "v1"
FIXTURE_SEED = bytes(range(1, 33))


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
    )


def build() -> dict[Path, dict[str, Any]]:
    private_key = Ed25519PrivateKey.from_private_bytes(FIXTURE_SEED)
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    desired: dict[str, Any] = {
        "agent_id": "agent_fixture_01",
        "contract_id": "unlimited-skills.fleet-wire",
        "contract_version": 1,
        "control_epoch": 7,
        "desired_state_digest": "",
        "desired_state_revision": "ds_fixture_b",
        "expected_inventory_digest": "sha256:" + ("d" * 64),
        "expires_at": "2099-12-31T00:00:00Z",
        "issued_at": "2026-07-27T00:00:00Z",
        "items": [
            {
                "action": "activate",
                "activation_nonce": "act_fixture_01",
                "archive_sha256": "sha256:" + ("b" * 64),
                "attempt_id": "attempt_fixture_01",
                "manifest_ref": "registry:private-pack/pack_fixture/release_b",
                "pack_id": "pack_fixture",
                "release_id": "release_b",
                "required": True,
                "version": "2.0.0",
            }
        ],
        "message_type": "desired-state",
        "previous_digest": "sha256:" + ("a" * 64),
        "rollout_id": "rollout_fixture_b",
    }
    digest_body = {
        key: value
        for key, value in desired.items()
        if key not in {"desired_state_digest", "desired_state_signature"}
    }
    desired["desired_state_digest"] = digest(canonical(digest_body))
    signed_body = canonical(desired)
    desired["desired_state_signature"] = {
        "algorithm": "ed25519",
        "key_id": "fleet-fixture-key-v1",
        "role": "fleet-desired-state-signing",
        "schema_version": 1,
        "signature": b64url(private_key.sign(signed_body)),
        "signed_payload_sha256": digest(signed_body),
    }
    receipt = {
        "activation_nonce": "act_fixture_01",
        "active_archive_sha256": "sha256:" + ("b" * 64),
        "adapter_version": "1.0.0",
        "agent_id": "agent_fixture_01",
        "archive_sha256": "sha256:" + ("b" * 64),
        "attempt_id": "attempt_fixture_01",
        "client_timestamp": "2026-07-27T00:01:00Z",
        "client_version": "0.6.9",
        "contract_id": "unlimited-skills.fleet-wire",
        "contract_version": 1,
        "control_epoch": 7,
        "desired_state_revision": "ds_fixture_b",
        "desired_state_digest": desired["desired_state_digest"],
        "event_id": "evt_fixture_01",
        "event_seq": 7,
        "event_type": "RUNTIME_ATTESTED",
        "idempotency_key": "evt_fixture_01",
        "message_type": "receipt-event",
        "pack_id": "pack_fixture",
        "reason_code": "none",
        "release_id": "release_b",
        "rollout_id": "rollout_fixture_b",
        "runtime_generation": "generation_fixture_02",
        "runtime_attestation": {
            "activation_nonce": "act_fixture_01",
            "active_inventory_digest": "sha256:" + ("d" * 64),
            "adapter_version": "1.0.0",
            "kind": "agent-adapter-runtime-v1",
            "runtime_generation": "generation_fixture_02",
        },
    }
    registration_request = {
        "adapter_id": "claude-code",
        "adapter_version": "1.0.0",
        "contract_id": "unlimited-skills.fleet-wire",
        "contract_version": 1,
        "installation_id": "uls_inst_fixture",
        "local_instance_id": "local_claude_01",
        "message_type": "agent-registration-request",
        "reported_capabilities": [
            "managed-roots",
            "runtime-attestation"
        ],
        "runtime_vendor": "claude-code",
    }
    registration_response = {
        "agent_id": "agent_fixture_01",
        "contract_id": "unlimited-skills.fleet-wire",
        "contract_version": 1,
        "installation_id": "uls_inst_fixture",
        "local_instance_id": "local_claude_01",
        "message_type": "agent-registration-response",
        "server_timestamp": "2026-07-27T00:00:00Z",
    }
    heartbeat_request = {
        "active_inventory_digest": "sha256:" + ("d" * 64),
        "agent_id": "agent_fixture_01",
        "client_timestamp": "2026-07-27T00:00:30Z",
        "contract_id": "unlimited-skills.fleet-wire",
        "contract_version": 1,
        "installation_id": "uls_inst_fixture",
        "message_type": "heartbeat-request",
        "runtime_generation": "generation_fixture_02",
    }
    heartbeat_response = {
        "agent_id": "agent_fixture_01",
        "contract_id": "unlimited-skills.fleet-wire",
        "contract_version": 1,
        "desired_state": desired,
        "installation_id": "uls_inst_fixture",
        "message_type": "heartbeat-response",
        "server_timestamp": "2026-07-27T00:00:31Z",
    }
    receipt_batch = {
        "batch_id": "batch_fixture_01",
        "contract_id": "unlimited-skills.fleet-wire",
        "contract_version": 1,
        "installation_id": "uls_inst_fixture",
        "message_type": "receipt-batch",
        "receipts": [receipt],
    }
    receipt_response = {
        "accepted_event_ids": ["evt_fixture_01"],
        "batch_id": "batch_fixture_01",
        "contract_id": "unlimited-skills.fleet-wire",
        "contract_version": 1,
        "duplicate_event_ids": [],
        "message_type": "receipt-response",
        "outcome": "accepted",
        "rejected_events": [],
        "server_timestamp": "2026-07-27T00:01:01Z",
    }
    invalid_signature = copy.deepcopy(desired)
    invalid_signature["items"][0]["archive_sha256"] = "sha256:" + ("c" * 64)
    client_verified = copy.deepcopy(receipt)
    client_verified["event_id"] = "evt_invalid_verified"
    client_verified["idempotency_key"] = "evt_invalid_verified"
    client_verified["event_type"] = "VERIFIED_ACTIVE"
    rollback_replay = copy.deepcopy(desired)
    rollback_replay["control_epoch"] = 6
    rollback_replay["items"][0]["attempt_id"] = "attempt_fixture_replay"
    rollback_replay["items"][0]["action"] = "rollback"
    rollback_replay["desired_state_revision"] = "ds_fixture_a_replay"
    nonce_mismatch = copy.deepcopy(receipt)
    nonce_mismatch["event_id"] = "evt_invalid_nonce"
    nonce_mismatch["idempotency_key"] = "evt_invalid_nonce"
    nonce_mismatch["runtime_attestation"]["activation_nonce"] = (
        "act_fixture_wrong"
    )
    inventory_mismatch = copy.deepcopy(receipt)
    inventory_mismatch["event_id"] = "evt_invalid_inventory"
    inventory_mismatch["idempotency_key"] = "evt_invalid_inventory"
    inventory_mismatch["runtime_attestation"][
        "active_inventory_digest"
    ] = "sha256:" + ("e" * 64)
    activation_nonce_tampered = copy.deepcopy(desired)
    activation_nonce_tampered["items"][0]["activation_nonce"] = (
        "act_fixture_tampered"
    )
    signing_contract = {
        "algorithm": "ed25519",
        "canonicalization": {
            "encoding": "utf-8",
            "floats": "forbidden",
            "json": "sort_keys=true,separators=(',',':'),ensure_ascii=false",
            "signature_field_excluded": "desired_state_signature",
        },
        "contract_id": "unlimited-skills.fleet-wire",
        "golden_fixture": {
            "desired_state_path": "fixtures/valid/desired-state.signed.json",
            "public_key": b64url(public_key),
            "signed_payload_sha256": digest(signed_body),
            "single_byte_mutation_result": "reject",
        },
        "major_version": 1,
        "bundle_revision": 2,
        "role": "fleet-desired-state-signing",
        "separate_from_role": "pack-release-signing",
    }
    return {
        CONTRACT_ROOT / "fixtures" / "valid" / "desired-state.signed.json": desired,
        CONTRACT_ROOT / "fixtures" / "valid" / "agent-registration-request.json": registration_request,
        CONTRACT_ROOT / "fixtures" / "valid" / "agent-registration-response.json": registration_response,
        CONTRACT_ROOT / "fixtures" / "valid" / "heartbeat-request.json": heartbeat_request,
        CONTRACT_ROOT / "fixtures" / "valid" / "heartbeat-response.json": heartbeat_response,
        CONTRACT_ROOT / "fixtures" / "valid" / "receipt-runtime-attested.json": receipt,
        CONTRACT_ROOT / "fixtures" / "valid" / "receipt-batch.json": receipt_batch,
        CONTRACT_ROOT / "fixtures" / "valid" / "receipt-response.json": receipt_response,
        CONTRACT_ROOT / "fixtures" / "invalid" / "desired-state-tampered.json": invalid_signature,
        CONTRACT_ROOT / "fixtures" / "invalid" / "receipt-client-verified-active.json": client_verified,
        CONTRACT_ROOT / "fixtures" / "invalid" / "rollback-old-epoch-replay.json": rollback_replay,
        CONTRACT_ROOT / "fixtures" / "invalid" / "desired-state-activation-nonce-tampered.json": activation_nonce_tampered,
        CONTRACT_ROOT / "fixtures" / "invalid" / "receipt-runtime-attestation-nonce-mismatch.json": nonce_mismatch,
        CONTRACT_ROOT / "fixtures" / "invalid" / "receipt-runtime-attestation-inventory-mismatch.json": inventory_mismatch,
        CONTRACT_ROOT / "signing-contract.json": signing_contract,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    expected = build()
    mismatches: list[str] = []
    for path, payload in expected.items():
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.write:
            write_json(path, payload)
        elif not path.is_file() or path.read_text(encoding="utf-8") != rendered:
            mismatches.append(path.relative_to(ROOT).as_posix())
    if mismatches:
        print(json.dumps({"ok": False, "mismatches": mismatches}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "files": len(expected)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
