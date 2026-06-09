from __future__ import annotations

import io
import json
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
    monkeypatch.setenv("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", f"private-test-key:{base64_urlsafe_encode(public_key)}")
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
