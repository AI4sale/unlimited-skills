from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.policy import audit_log_path, canonical_policy_sha256, install_policy_payload, load_policy
from unlimited_skills.policy_sync import PolicySyncError, managed_policy_status, sync_managed_policy
from unlimited_skills.registration import RegistrationState, base64_urlsafe_encode, with_install_identity
from unlimited_skills.signatures import sign_manifest_for_tests


def registered_state() -> RegistrationState:
    state = with_install_identity(RegistrationState(install_id="uls_inst_policy_sync", server_url="https://sync.example.test", license_token="tok_policy_sync"))
    return RegistrationState(
        install_id=state.install_id,
        server_url=state.server_url,
        license_token="tok_policy_sync",
        device_private_key=state.device_private_key,
        device_public_key=state.device_public_key,
        key_thumbprint=state.key_thumbprint,
    )


def policy_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "policy_id": "managed_policy_test",
        "mode": "audit",
        "allowed_registries": ["https://sync.example.test"],
        "allowed_release_channels": ["stable"],
        "required_manifest_signatures": True,
        "allowed_key_ids": ["policy-sync-test-key"],
        "allowed_key_scopes": ["enterprise-policy", "catalog-updates"],
        "allowed_local_roots": [],
        "community": {"install_allowed": True, "submit_allowed": False},
        "hub": {"remote_required": False, "local_fallback_allowed": True, "unsigned_local_allowlist_allowed": False},
        "audit": {"log_refusals": True},
    }
    payload.update(overrides)
    payload["policy_sha256"] = canonical_policy_sha256(payload)
    return payload


def signed_assignment(action: str, private_key: Ed25519PrivateKey, *, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "manifest_type": "enterprise-policy-assignment",
        "assignment_id": "assign_test_1",
        "install_id": "uls_inst_policy_sync",
        "action": action,
        "assigned_at": "2026-06-09T00:00:00Z",
    }
    if policy is not None:
        payload["policy"] = policy
    return sign_manifest_for_tests(payload, private_key, key_id="policy-sync-test-key")


def trust_test_key(monkeypatch: pytest.MonkeyPatch, private_key: Ed25519PrivateKey) -> None:
    public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    monkeypatch.setenv("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", f"policy-sync-test-key:{base64_urlsafe_encode(public_raw)}")


def test_managed_policy_sync_dry_run_does_not_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    private_key = Ed25519PrivateKey.generate()
    trust_test_key(monkeypatch, private_key)
    response = signed_assignment("install", private_key, policy=policy_payload())
    monkeypatch.setattr("unlimited_skills.policy_sync.post_json", lambda *args, **kwargs: response)

    payload = sync_managed_policy(home=home, state=registered_state(), dry_run=True)

    assert payload["dry_run"] is True
    assert payload["changed"] is False
    assert payload["assignment"]["signature_verification"]["verified"] is True
    assert not (home / "policy" / "enterprise-skill-lock-policy.json").exists()
    assert not (home / "policy" / "managed-policy-state.json").exists()


def test_managed_policy_sync_installs_and_records_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    private_key = Ed25519PrivateKey.generate()
    trust_test_key(monkeypatch, private_key)
    response = signed_assignment("install", private_key, policy=policy_payload(mode="enforce"))
    monkeypatch.setattr("unlimited_skills.policy_sync.post_json", lambda *args, **kwargs: response)

    payload = sync_managed_policy(home=home, state=registered_state())

    assert payload["changed"] is True
    installed = load_policy(home)
    assert installed["policy_id"] == "managed_policy_test"
    assert installed["mode"] == "enforce"
    status = managed_policy_status(home=home)
    assert status["managed_state"]["managed"] is True
    assert status["managed_state"]["policy_id"] == "managed_policy_test"


def test_managed_policy_sync_remove_uninstalls_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    private_key = Ed25519PrivateKey.generate()
    trust_test_key(monkeypatch, private_key)
    install_response = signed_assignment("install", private_key, policy=policy_payload())
    responses = [install_response, signed_assignment("remove", private_key)]
    monkeypatch.setattr("unlimited_skills.policy_sync.post_json", lambda *args, **kwargs: responses.pop(0))

    sync_managed_policy(home=home, state=registered_state())
    removed = sync_managed_policy(home=home, state=registered_state())

    assert removed["managed_state"]["managed"] is False
    assert removed["managed_state"]["remove_allowed"] is True
    assert removed["managed_state"]["removal_refused"] is False
    assert load_policy(home)["installed"] is False
    assert managed_policy_status(home=home)["managed_state"]["action"] == "remove"


def test_managed_policy_sync_remove_refuses_unmanaged_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    private_key = Ed25519PrivateKey.generate()
    trust_test_key(monkeypatch, private_key)
    install_policy_payload(policy_payload(policy_id="local_unmanaged_policy"), home=home, source="local-admin")
    monkeypatch.setattr("unlimited_skills.policy_sync.post_json", lambda *args, **kwargs: signed_assignment("remove", private_key))

    removed = sync_managed_policy(home=home, state=registered_state())

    assert removed["changed"] is False
    assert removed["managed_state"]["managed"] is False
    assert removed["managed_state"]["remove_allowed"] is False
    assert removed["managed_state"]["removal_refused"] is True
    assert removed["managed_state"]["refusal_reason"] == "installed_policy_not_managed"
    assert "not managed by registry sync" in removed["managed_state"]["message"]
    assert load_policy(home)["policy_id"] == "local_unmanaged_policy"
    audit_text = audit_log_path(home).read_text(encoding="utf-8")
    assert "managed_policy_remove_refused" in audit_text
    assert "installed_policy_not_managed" in audit_text
    assert "tok_policy_sync" not in audit_text


def test_managed_policy_sync_remove_dry_run_refuses_unmanaged_without_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    private_key = Ed25519PrivateKey.generate()
    trust_test_key(monkeypatch, private_key)
    install_policy_payload(policy_payload(policy_id="local_unmanaged_policy"), home=home, source="local-admin")
    monkeypatch.setattr("unlimited_skills.policy_sync.post_json", lambda *args, **kwargs: signed_assignment("remove", private_key))

    removed = sync_managed_policy(home=home, state=registered_state(), dry_run=True)

    assert removed["dry_run"] is True
    assert removed["changed"] is False
    assert removed["managed_state"]["remove_allowed"] is False
    assert removed["managed_state"]["removal_refused"] is True
    assert load_policy(home)["policy_id"] == "local_unmanaged_policy"
    assert not audit_log_path(home).exists()
    assert not (home / "policy" / "managed-policy-state.json").exists()


def test_managed_policy_sync_requires_registration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / "home"))

    with pytest.raises(PolicySyncError, match="requires registration"):
        sync_managed_policy(state=RegistrationState())


def test_managed_policy_sync_rejects_unsigned_assignment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("unlimited_skills.policy_sync.post_json", lambda *args, **kwargs: {"schema_version": 1, "action": "none"})

    with pytest.raises(PolicySyncError, match="must include manifest_signature"):
        sync_managed_policy(state=registered_state())
