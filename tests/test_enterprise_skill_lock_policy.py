from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.community import CommunityClient
from unlimited_skills.policy import canonical_policy_sha256, install_policy, load_policy, policy_summary, verify_policy_payload
from unlimited_skills.policy_enforcement import (
    PolicyViolation,
    enforce_local_allowlist_signed,
    enforce_registry_url,
    enforce_remote_fallback_allowed,
)
from unlimited_skills.registration import RegistrationState, base64_urlsafe_encode, with_install_identity
from unlimited_skills.signatures import sign_manifest_for_tests, verify_manifest_signature
from unlimited_skills.updates import save_release_channel


def policy_payload(**overrides):
    payload = {
        "schema_version": 1,
        "policy_id": "policy_test",
        "mode": "enforce",
        "allowed_registries": ["https://allowed.example.test"],
        "allowed_release_channels": ["stable"],
        "required_manifest_signatures": True,
        "allowed_key_ids": ["allowed-key"],
        "allowed_key_scopes": ["catalog-updates", "hub-allowlist"],
        "allowed_local_roots": [],
        "community": {"install_allowed": False, "submit_allowed": False},
        "hub": {"remote_required": True, "local_fallback_allowed": False, "unsigned_local_allowlist_allowed": False},
        "audit": {"log_refusals": True},
    }
    payload.update(overrides)
    payload["policy_sha256"] = canonical_policy_sha256(payload)
    return payload


def write_policy(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def install_test_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict | None = None) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    path = write_policy(tmp_path, payload or policy_payload())
    install_policy(path, home=home)
    return home


def registered_state() -> RegistrationState:
    state = with_install_identity(RegistrationState(install_id="uls_inst_policy", server_url="https://allowed.example.test", license_token="tok_policy"))
    return RegistrationState(
        install_id=state.install_id,
        server_url=state.server_url,
        license_token="tok_policy",
        device_private_key=state.device_private_key,
        device_public_key=state.device_public_key,
        key_thumbprint=state.key_thumbprint,
    )


def test_no_policy_existing_registry_behavior_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / "home"))

    enforce_registry_url("https://any.example.test/v1/catalog")

    assert policy_summary(load_policy())["locked"] is False


def test_audit_policy_logs_warning_but_allows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = install_test_policy(tmp_path, monkeypatch, policy_payload(mode="audit"))

    enforce_registry_url("https://blocked.example.test/v1/catalog")

    audit = home / "policy" / "refusals.jsonl"
    assert audit.is_file()
    assert "blocked.example.test" in audit.read_text(encoding="utf-8")


def test_enforce_policy_rejects_disallowed_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_test_policy(tmp_path, monkeypatch)

    with pytest.raises(PolicyViolation, match="registry origin https://blocked.example.test"):
        enforce_registry_url("https://blocked.example.test/v1/catalog")


def test_enforce_policy_rejects_disallowed_channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = install_test_policy(tmp_path, monkeypatch)

    with pytest.raises(PolicyViolation, match="release channel beta"):
        save_release_channel("beta", home=home)


def test_enforce_policy_rejects_unknown_manifest_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_test_policy(tmp_path, monkeypatch)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    manifest = sign_manifest_for_tests({"schema_version": 1, "updates": []}, private_key, key_id="unknown-key")
    monkeypatch.setenv("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", f"unknown-key:{base64_urlsafe_encode(public_key)}")

    with pytest.raises(PolicyViolation, match="manifest key unknown-key"):
        verify_manifest_signature(manifest, purpose="Hosted collection updates", required=True, scope="catalog-updates", registry_url="https://allowed.example.test")


def test_enforce_policy_denies_community_install_and_submit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_test_policy(tmp_path, monkeypatch)
    client = CommunityClient(registered_state())

    with pytest.raises(PolicyViolation, match="community installs are denied"):
        client.install_community_item(tmp_path / "library", item_id="community-skill", dry_run=True)

    with pytest.raises(PolicyViolation, match="community submissions are denied"):
        client.submit_community_skill(object(), dry_run=True)  # type: ignore[arg-type]


def test_enforce_policy_denies_unsigned_local_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_test_policy(tmp_path, monkeypatch)

    with pytest.raises(PolicyViolation, match="unsigned local allowlists"):
        enforce_local_allowlist_signed({"schema_version": 1, "allowlist": []})


def test_enforce_policy_denies_local_fallback_when_remote_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install_test_policy(tmp_path, monkeypatch)

    with pytest.raises(PolicyViolation, match="local fallback is denied"):
        enforce_remote_fallback_allowed()


def test_policy_verify_accepts_hash_pinned_policy(tmp_path: Path) -> None:
    payload = policy_payload()
    result = verify_policy_payload(payload)

    assert result["valid"] is True
    assert result["hash_pinned"] is True
    assert result["signed"] is False


def test_policy_status_and_audit_redact_secret_shaped_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = install_test_policy(tmp_path, monkeypatch)

    with pytest.raises(PolicyViolation):
        enforce_registry_url("https://blocked.example.test/v1/catalog?token=tok_secret_policy")

    summary = json.dumps(policy_summary(load_policy(home)), sort_keys=True)
    audit = (home / "policy" / "refusals.jsonl").read_text(encoding="utf-8")
    assert "tok_secret_policy" not in summary
    assert "tok_secret_policy" not in audit
    assert "private_key" not in summary
    assert "private_key" not in audit
