from __future__ import annotations

import io
import json
import os
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.cli import main
from unlimited_skills.private_packs import PrivatePackClient, PrivatePackError, list_installed_private_packs, remove_private_pack
from unlimited_skills.registration import RegistrationState, base64_urlsafe_encode, save_registration, with_install_identity
from unlimited_skills.signatures import sign_manifest_for_tests
from unlimited_skills.updates import sha256_file


PACK_ID = "team_pack_acme_private_skills"


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(install_id="uls_inst_master", server_url="https://private.example.test", license_token="tok_test")
    )


def write_registration(home: Path) -> None:
    save_registration(registered_state(), home=home / ".unlimited-skills")


def make_archive(tmp_path: Path, *, traversal: bool = False) -> Path:
    archive = tmp_path / "private.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        if traversal:
            zf.writestr("../escape.txt", "no")
        else:
            zf.writestr(f"{PACK_ID}/skills/browser-qa/SKILL.md", "---\nname: browser-qa\ndescription: qa\n---\n\n# qa\n")
    return archive


def signed_private_manifest(tmp_path: Path, monkeypatch, *, archive: Path | None = None, sha256: str = "") -> dict:
    archive = archive or make_archive(tmp_path)
    digest = sha256 or sha256_file(archive)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    if not os.environ.get("UNLIMITED_SKILLS_HOME"):
        monkeypatch.setenv(
            "UNLIMITED_SKILLS_HOME",
            str(tmp_path / ".unlimited-skills"),
        )
    trust_file = tmp_path / "private-pack-public-keys.json"
    trust_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "keys": [
                    {
                        "key_id": "private-test-key",
                        "algorithm": "ed25519",
                        "public_key": base64_urlsafe_encode(public_key),
                        "status": "active",
                        "scopes": ["private-team-pack"],
                        "registry_origins": [
                            "https://private.example.test"
                        ],
                        "role": "private-team-pack-manifest",
                        "not_after": "2099-01-01T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv(
        "UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS",
        raising=False,
    )
    monkeypatch.setenv(
        "UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS_FILE",
        str(trust_file),
    )
    return sign_manifest_for_tests(
        {
            "schema_version": 1,
            "manifest_type": "private-team-pack-manifest",
            "pack_id": PACK_ID,
            "team_id": "team_acme_fixture",
            "namespace": "team/acme",
            "name": "acme-private-skills",
            "version": "2026.01.01",
            "visibility": "private-team",
            "archive_url": "archives/private.zip",
            "sha256": digest,
            "bytes": archive.stat().st_size,
            "allowed_agents": ["codex"],
            "allowed_install_ids": ["uls_inst_master"],
            "allowed_channel": "stable",
            "revoked": False,
            "contains_private_skill_bodies": False,
        },
        private_key,
        key_id="private-test-key",
    )


def fake_service(manifest: dict, archive: Path):
    def _urlopen(request, timeout=30.0):
        url = request.full_url
        if url.endswith("/v1/private-packs/list"):
            return FakeResponse(
                json.dumps(
                    {
                        "schema_version": 1,
                        "distribution_mode": "private_team_pack",
                        "packs": [
                            {
                                "schema_version": 1,
                                "pack_id": PACK_ID,
                                "team_id": "team_acme_fixture",
                                "namespace": "team/acme",
                                "name": "acme-private-skills",
                                "version": "2026.01.01",
                                "visibility": "private-team",
                                "revoked": False,
                                "private_skill_bodies_included": False,
                                "archive_sha256": manifest["sha256"],
                                "archive": {"filename": "private.zip", "sha256": manifest["sha256"], "bytes": archive.stat().st_size},
                            }
                        ],
                    }
                ).encode("utf-8")
            )
        if url.endswith("/v1/private-packs/preview"):
            return FakeResponse(
                json.dumps(
                    {
                        "schema_version": 1,
                        "pack": {
                            "schema_version": 1,
                            "pack_id": PACK_ID,
                            "team_id": "team_acme_fixture",
                            "namespace": "team/acme",
                            "name": "acme-private-skills",
                            "version": "2026.01.01",
                            "visibility": "private-team",
                            "revoked": False,
                            "private_skill_bodies_included": False,
                            "archive_sha256": manifest["sha256"],
                            "archive": {"filename": "private.zip", "sha256": manifest["sha256"], "bytes": archive.stat().st_size},
                        },
                    }
                ).encode("utf-8")
            )
        if url.endswith("/v1/private-packs/manifest"):
            return FakeResponse(json.dumps({"schema_version": 1, "manifest": manifest, "verification": {"verified": True}}).encode("utf-8"))
        if url.endswith("/v1/private-packs/access-check"):
            return FakeResponse(json.dumps({"schema_version": 1, "authorized": True, "access_policy": {"current_install_authorized": True}}).encode("utf-8"))
        if url.endswith("/v1/private-packs/download"):
            assert any(key.lower() == "x-uls-proof" for key in request.headers)
            return FakeResponse(archive.read_bytes())
        raise AssertionError(f"Unexpected URL: {url}")

    return _urlopen


def fake_access_check(payload: dict):
    def _urlopen(request, timeout=30.0):
        if request.full_url.endswith("/v1/private-packs/access-check"):
            return FakeResponse(json.dumps(payload).encode("utf-8"))
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    return _urlopen


def test_private_packs_require_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / "home" / ".unlimited-skills"))

    assert main(["--root", str(tmp_path / "library"), "private-packs", "list"]) == 2

    assert "Registration is required for private team packs" in capsys.readouterr().err


def test_private_pack_list_preview_and_install_are_signed_and_redacted(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    archive = make_archive(tmp_path)
    manifest = signed_private_manifest(tmp_path, monkeypatch, archive=archive)

    with patch("urllib.request.urlopen", fake_service(manifest, archive)):
        assert main(["--root", str(root), "private-packs", "list", "--json"]) == 0
        listed = json.loads(capsys.readouterr().out)
        assert listed["items"][0]["pack_id"] == PACK_ID
        assert "When to use" not in json.dumps(listed)
        assert main(["--root", str(root), "private-packs", "preview", PACK_ID, "--json"]) == 0
        preview = json.loads(capsys.readouterr().out)
        assert preview["pack"]["archive_sha256"] == manifest["sha256"]
        assert "tok_test" not in json.dumps(preview)
        assert main(["--root", str(root), "private-packs", "install", PACK_ID, "--yes", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["installed"] is True
    assert (root / "registry" / "private" / PACK_ID / "skills" / "browser-qa" / "SKILL.md").is_file()
    installed = list_installed_private_packs(root)
    assert installed[0].pack_id == PACK_ID
    assert installed[0].target == f"registry\\private\\{PACK_ID}" or installed[0].target == f"registry/private/{PACK_ID}"
    assert (root / ".unlimited-skills-index.json").is_file()


@pytest.mark.parametrize(
    ("service_payload", "expected_reason", "expected_status"),
    [
        ({"authorized": False, "denial_reasons": ["no_entitlement"], "plan": "registered-community"}, "no_entitlement", "denied"),
        ({"authorized": False, "denial_reasons": ["not_team_member"]}, "not_team_member", "denied"),
        ({"authorized": False, "denial_reasons": ["wrong_agent"]}, "wrong_agent", "denied"),
        ({"authorized": False, "denial_reasons": ["wrong_channel"]}, "wrong_channel", "denied"),
        ({"authorized": False, "revoked": True}, "revoked", "denied"),
        ({"authorized": False, "policy_denied": True}, "policy_denied", "denied"),
        ({"authorized": False, "reason_code": "wrong_agent", "access_policy": {"reason_code": "wrong_agent"}}, "wrong_agent", "denied"),
        ({"authorized": True, "access_policy": {"current_install_authorized": True}}, None, "authorized"),
    ],
)
def test_private_pack_access_check_reports_policy_reasons(
    tmp_path: Path,
    monkeypatch,
    capsys,
    service_payload: dict,
    expected_reason: str | None,
    expected_status: str,
) -> None:
    home = tmp_path / "home"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    with patch("urllib.request.urlopen", fake_access_check(service_payload)):
        assert main(["private-packs", "access-check", PACK_ID, "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == expected_status
    assert payload["privacy"]["pack_id_included"] is False
    assert payload["pack_ref"].startswith("pack:")
    if expected_reason:
        assert expected_reason in payload["denial_reasons"]
    serialized = json.dumps(payload)
    assert PACK_ID not in serialized
    assert '"archive_url":' not in serialized
    assert "tok_test" not in serialized


def test_private_pack_access_check_reports_service_unavailable(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
        assert main(["private-packs", "access-check", PACK_ID, "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unavailable"
    assert payload["denial_reasons"] == ["service_unavailable"]


def test_private_pack_doctor_is_local_and_redacted(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    with patch("urllib.request.urlopen") as urlopen:
        assert main(["--root", str(root), "private-packs", "doctor", "--json"]) == 0

    urlopen.assert_not_called()
    payload = json.loads(capsys.readouterr().out)
    assert payload["network_calls"] is False
    assert payload["privacy"]["tokens_included"] is False


def test_private_pack_sync_dry_run_and_apply(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    archive = make_archive(tmp_path)
    manifest = signed_private_manifest(tmp_path, monkeypatch, archive=archive)

    with patch("urllib.request.urlopen", fake_service(manifest, archive)):
        assert main(["--root", str(root), "private-packs", "sync", "--json"]) == 0
        dry_run = json.loads(capsys.readouterr().out)
        assert dry_run["dry_run"] is True
        assert dry_run["planned"][0]["action"] == "install_or_update"
        assert not (root / "registry" / "private" / PACK_ID).exists()

        assert main(["--root", str(root), "private-packs", "sync", "--yes", "--json"]) == 0

    applied = json.loads(capsys.readouterr().out)
    assert applied["applied"][0]["installed"] is True
    assert (root / "registry" / "private" / PACK_ID / "skills" / "browser-qa" / "SKILL.md").is_file()


def test_private_pack_remove_is_owned_only(tmp_path: Path) -> None:
    root = tmp_path / "library"
    unmanaged = root / "registry" / "private" / "manual" / "skills" / "manual-skill"
    unmanaged.mkdir(parents=True)
    (unmanaged / "SKILL.md").write_text("---\nname: manual\ndescription: manual\n---\n", encoding="utf-8")

    with pytest.raises(PrivatePackError):
        remove_private_pack(root, "manual", dry_run=False)

    assert (unmanaged / "SKILL.md").is_file()


def test_private_pack_rejects_sha_mismatch_and_zip_traversal(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    archive = make_archive(tmp_path)
    manifest = signed_private_manifest(tmp_path, monkeypatch, archive=archive, sha256="0" * 64)
    with patch("urllib.request.urlopen", fake_service(manifest, archive)):
        with pytest.raises(PrivatePackError, match="SHA256 mismatch"):
            PrivatePackClient(registered_state()).install(root, PACK_ID)

    bad_archive = make_archive(tmp_path, traversal=True)
    bad_manifest = signed_private_manifest(tmp_path, monkeypatch, archive=bad_archive)
    with patch("urllib.request.urlopen", fake_service(bad_manifest, bad_archive)):
        with pytest.raises(Exception, match="Unsafe archive path"):
            PrivatePackClient(registered_state()).install(root, PACK_ID)

    assert not (root / "registry" / "private" / PACK_ID).exists()


def test_fleet_private_pack_requests_are_scope_bound_in_body_and_headers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive = make_archive(tmp_path)
    manifest = signed_private_manifest(
        tmp_path,
        monkeypatch,
        archive=archive,
    )
    expected_sha256 = "sha256:" + sha256_file(archive)
    context = {
        "agent_id": "agent_fixture_01",
        "rollout_id": "rollout_fixture_01",
        "attempt_id": "attempt_fixture_01",
        "desired_state_revision": "desired_fixture_01",
        "release_id": "release_fixture_01",
        "archive_sha256": expected_sha256,
    }
    requests: list[dict] = []

    def _urlopen(request, timeout=30.0):
        del timeout
        requests.append(
            {
                "url": request.full_url,
                "headers": {
                    key.lower(): value
                    for key, value in request.headers.items()
                },
                "body": json.loads(request.data),
            }
        )
        if request.full_url.endswith(
            "/v1/fleet/private-packs/manifest"
        ):
            return FakeResponse(
                json.dumps(
                    {
                        "schema_version": 1,
                        "manifest": manifest,
                    }
                ).encode("utf-8")
            )
        if request.full_url.endswith(
            "/v1/fleet/private-packs/download"
        ):
            return FakeResponse(archive.read_bytes())
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    client = PrivatePackClient(
        registered_state(),
        endpoint_prefix="/v1/fleet/private-packs",
    )
    with patch("urllib.request.urlopen", _urlopen):
        client.signed_manifest(PACK_ID, request_context=context)
        assert (
            client.download_archive(
                PACK_ID,
                release_id=context["release_id"],
                expected_sha256=expected_sha256,
                request_context=context,
            )
            == archive.read_bytes()
        )

    assert len(requests) == 2
    for request in requests:
        assert request["body"] == {
            "schema_version": 1,
            "install_id": "uls_inst_master",
            "client": {
                "name": "unlimited-skills",
                "version": client._client_payload()["version"],
            },
            "pack_id": PACK_ID,
            "agent_id": context["agent_id"],
            "rollout_id": context["rollout_id"],
            "attempt_id": context["attempt_id"],
            "desired_state_revision": context[
                "desired_state_revision"
            ],
            "release_id": context["release_id"],
            "expected_sha256": expected_sha256,
        }
        assert request["headers"]["x-uls-agent-id"] == context[
            "agent_id"
        ]
        assert request["headers"]["x-uls-rollout-id"] == context[
            "rollout_id"
        ]
        assert request["headers"]["x-uls-attempt-id"] == context[
            "attempt_id"
        ]
        assert request["headers"][
            "x-uls-desired-state-revision"
        ] == context["desired_state_revision"]
        assert request["headers"]["x-uls-pack-id"] == PACK_ID
        assert request["headers"]["x-uls-release-id"] == context[
            "release_id"
        ]
        assert request["headers"]["x-uls-archive-sha256"] == (
            expected_sha256
        )
        assert "x-uls-proof" in request["headers"]


def test_fleet_private_pack_requests_fail_closed_without_full_scope() -> None:
    client = PrivatePackClient(
        registered_state(),
        endpoint_prefix="/v1/fleet/private-packs",
    )

    with pytest.raises(
        PrivatePackError,
        match="fleet_payload_scope_required",
    ):
        client.signed_manifest(
            PACK_ID,
            request_context={
                "agent_id": "agent_fixture_01",
                "rollout_id": "rollout_fixture_01",
            },
        )


def test_fleet_private_pack_scope_rejects_header_injection() -> None:
    client = PrivatePackClient(
        registered_state(),
        endpoint_prefix="/v1/fleet/private-packs",
    )
    context = {
        "agent_id": "agent_fixture_01\r\nX-Evil: injected",
        "rollout_id": "rollout_fixture_01",
        "attempt_id": "attempt_fixture_01",
        "desired_state_revision": "desired_fixture_01",
        "release_id": "release_fixture_01",
        "archive_sha256": "sha256:" + ("a" * 64),
    }

    with pytest.raises(
        PrivatePackError,
        match="additional_request_header_invalid",
    ):
        client.signed_manifest(
            PACK_ID,
            request_context=context,
        )


def test_legacy_private_pack_client_keeps_legacy_route() -> None:
    client = PrivatePackClient(registered_state())

    assert client.endpoint_prefix == "/v1/private-packs"
