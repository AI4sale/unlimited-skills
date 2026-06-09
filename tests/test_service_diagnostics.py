from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.registration import RegistrationState, base64_urlsafe_encode, save_registration, with_install_identity
from unlimited_skills.service_diagnostics import (
    assert_service_diagnostics_do_not_contain_forbidden_fields,
    configure_service,
    doctor,
    local_status,
    registration_dry_run,
    service_health_snapshot,
    test_proof as build_test_proof,
    verify_trust,
)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._stream = io.BytesIO(json.dumps(payload).encode("utf-8"))
        self.status = 200

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._stream.read()


def registered_state(url: str = "http://127.0.0.1:8765") -> RegistrationState:
    state = with_install_identity(RegistrationState(install_id="uls_inst_service_test", server_url=url, license_token="uls_secret_token"))
    return RegistrationState(
        install_id=state.install_id,
        server_url=state.server_url,
        plan="registered-community",
        license_token="uls_secret_token",
        device_private_key=state.device_private_key,
        device_public_key=state.device_public_key,
        key_thumbprint=state.key_thumbprint,
        proof_required=True,
        features_enabled=("hosted_catalog",),
    )


def public_key_manifest() -> tuple[dict, dict[str, str]]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public_b64 = base64_urlsafe_encode(public_key)
    key_id = "service-test-key"
    return (
        {
            "schema_version": 1,
            "keys": [
                {
                    "key_id": key_id,
                    "algorithm": "ed25519",
                    "public_key": public_b64,
                    "status": "active",
                    "scopes": ["hub-allowlist", "catalog-updates", "enhancement-manifest", "team-sync-manifest", "release-channels"],
                    "registry_origins": ["*"],
                }
            ],
        },
        {"UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS": f"{key_id}:{public_b64}"},
    )


def test_configure_service_rejects_plain_http_non_localhost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / "home"))
    with pytest.raises(RuntimeError):
        configure_service("http://registry.example.test")


def test_configure_service_allows_explicit_localhost_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))

    payload = configure_service("http://127.0.0.1:8765", allow_insecure_localhost=True)

    assert payload["service_url"] == "http://127.0.0.1:8765"
    assert payload["insecure_localhost"] is True
    assert (home / "service.json").is_file()


def test_service_status_is_local_only_without_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / "home"))
    save_registration(registered_state(), home=tmp_path / "home")

    def fake_urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("status without --refresh must not contact the service")

    with patch("urllib.request.urlopen", fake_urlopen):
        payload = local_status()

    assert payload["network"]["performed"] is False
    assert payload["registration"]["registered"] is True
    assert_service_diagnostics_do_not_contain_forbidden_fields(payload)


def test_service_health_snapshot_v2_is_local_only_and_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)

    def fake_urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("service health snapshot must be local-only unless refresh=True")

    with patch("urllib.request.urlopen", fake_urlopen):
        payload = service_health_snapshot(home=home)

    serialized = json.dumps(payload)
    assert payload["snapshot_version"] == 2
    assert payload["network"]["performed"] is False
    assert payload["registration"]["registered"] is True
    assert payload["registration"]["hosted_credential"] == "present"
    assert payload["registration"]["device_identity"] == "present"
    assert "uls_secret_token" not in serialized
    assert "device_private_key" not in serialized
    assert "X-ULS-Proof" not in serialized
    assert "unlimited-skills service doctor" in payload["next_commands"]
    assert_service_diagnostics_do_not_contain_forbidden_fields(payload)


def test_verify_trust_matches_remote_public_key_to_local_trust(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    manifest, env = public_key_manifest()

    def fake_urlopen(request, timeout=10.0):
        assert request.full_url == "http://127.0.0.1:8765/v1/public-keys"
        return FakeResponse(manifest)

    with patch.dict("os.environ", env, clear=False), patch("urllib.request.urlopen", fake_urlopen):
        payload = verify_trust()

    assert payload["signed_manifest_compatibility"]["compatible"] is True
    assert payload["trusted_remote_key_ids"] == ["service-test-key"]
    assert payload["endpoints_contacted"] == ["http://127.0.0.1:8765/v1/public-keys"]
    assert_service_diagnostics_do_not_contain_forbidden_fields(payload)


def test_service_doctor_contacts_only_declared_get_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    manifest, env = public_key_manifest()
    seen: list[tuple[str, str]] = []

    def fake_urlopen(request, timeout=10.0):
        seen.append((request.get_method(), request.full_url))
        if request.full_url.endswith("/health"):
            return FakeResponse({"status": "healthy"})
        if request.full_url.endswith("/ready"):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error":"not_found"}'))
        if request.full_url.endswith("/v1/public-keys"):
            return FakeResponse(manifest)
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    with patch.dict("os.environ", env, clear=False), patch("urllib.request.urlopen", fake_urlopen):
        payload = doctor()

    assert payload["ok"] is True
    assert payload["endpoints_contacted"] == [
        "http://127.0.0.1:8765/health",
        "http://127.0.0.1:8765/ready",
        "http://127.0.0.1:8765/v1/public-keys",
    ]
    assert {method for method, _url in seen} == {"GET"}
    assert seen == [
        ("GET", "http://127.0.0.1:8765/health"),
        ("GET", "http://127.0.0.1:8765/ready"),
        ("GET", "http://127.0.0.1:8765/v1/public-keys"),
    ]
    assert payload["privacy"]["uploads_local_data"] is False
    assert '"public_key"' not in json.dumps(payload)
    assert_service_diagnostics_do_not_contain_forbidden_fields(payload)


def test_registration_dry_run_is_redacted_and_sends_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / "home"))

    def fake_urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("dry-run registration must not contact the service")

    with patch("urllib.request.urlopen", fake_urlopen):
        payload = registration_dry_run(service_url="http://127.0.0.1:8765", agent="codex")

    serialized = json.dumps(payload)
    assert payload["would_send"] is False
    assert payload["payload"]["public_key"] == "present"
    assert "SKILL.md" not in serialized
    assert "C:\\" not in serialized
    assert "uls_secret_token" not in serialized
    assert "private_key" not in serialized
    assert_service_diagnostics_do_not_contain_forbidden_fields(payload)


def test_service_test_proof_redacts_header_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)

    payload = build_test_proof()

    assert payload["generated"] is True
    assert payload["headers"] == {"X-ULS-Proof": "present"}
    assert payload["proof_value"] == "[redacted]"
    assert "uls_secret_token" not in json.dumps(payload)
    assert_service_diagnostics_do_not_contain_forbidden_fields(payload)
