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
from unlimited_skills.community import (
    CommunityClient,
    CommunityError,
    build_submission_draft,
    list_installed_community_items,
)
from unlimited_skills.registration import RegistrationState, base64_urlsafe_encode, save_registration, with_install_identity
from unlimited_skills.signatures import sign_manifest_for_tests
from unlimited_skills.updates import UpdateError, sha256_file


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
        RegistrationState(install_id="uls_inst_test", server_url="https://community.example.test", license_token="tok_test")
    )


def write_registration(home: Path) -> None:
    save_registration(registered_state(), home=home / ".unlimited-skills")


def write_skill(path: Path, *, body: str = "# Body\n") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text("---\nname: browser-qa\ndescription: Browser QA checks\n---\n\n" + body, encoding="utf-8")


def make_archive(tmp_path: Path, collection: str = "community", skill: str = "browser-qa") -> Path:
    archive = tmp_path / "community.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{collection}/skills/{skill}/SKILL.md", f"---\nname: {skill}\ndescription: test\n---\n\n# {skill}\n")
    return archive


def trust_test_key(monkeypatch) -> Ed25519PrivateKey:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    monkeypatch.setenv("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", f"community-test-key:{base64_urlsafe_encode(public_key)}")
    return private_key


def sign_community_payload(payload: dict, private_key: Ed25519PrivateKey) -> dict:
    body = {"schema_version": 1, "manifest_type": "community-catalog", **payload}
    return sign_manifest_for_tests(body, private_key, key_id="community-test-key")


def test_community_hosted_commands_require_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    assert main(["--root", str(root), "community", "list"]) == 2

    captured = capsys.readouterr()
    assert "Registration is required for hosted community skills" in captured.err
    assert "MIT local core still works offline" in captured.err


def test_unregistered_local_search_list_view_still_work(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_skill(root / "local" / "skills" / "browser-qa")
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    monkeypatch.setenv("UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC", "1")

    assert main(["--root", str(root), "list", "--filter", "browser", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 1

    assert main(["--root", str(root), "search", "browser qa", "--json"]) == 0
    search_payload = json.loads(capsys.readouterr().out)
    assert search_payload[0]["name"] == "browser-qa"


def test_community_installed_is_local_only_without_refresh(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    root.mkdir(parents=True)
    (root / ".unlimited-skills-community.json").write_text(
        json.dumps({"schema_version": 1, "items": {"community": {"item_id": "comm_browser_qa", "name": "browser-qa", "version": "1", "source": "community"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    def fail_urlopen(request, timeout=30.0):
        raise AssertionError("community installed must not call hosted service without --refresh")

    with patch("urllib.request.urlopen", fail_urlopen):
        assert main(["--root", str(root), "community", "installed", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["items"][0]["name"] == "browser-qa"


def test_submit_dry_run_writes_preview_and_sends_no_request(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    skill = tmp_path / "browser-qa"
    write_skill(skill)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    def fail_urlopen(request, timeout=30.0):
        raise AssertionError("dry-run submit must not upload")

    with patch("urllib.request.urlopen", fail_urlopen):
        assert main(["--root", str(root), "community", "submit", str(skill), "--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["uploaded"] is False
    assert Path(payload["preview_path"]).is_file()
    assert payload["skills"] == ["browser-qa"]


def test_submit_refuses_blocked_files(tmp_path: Path) -> None:
    skill = tmp_path / "browser-qa"
    write_skill(skill)
    (skill / ".env").write_text("API_KEY=secret-value\n", encoding="utf-8")

    with pytest.raises(CommunityError):
        build_submission_draft(skill)


def test_submit_warns_on_obvious_secret_patterns(tmp_path: Path) -> None:
    skill = tmp_path / "browser-qa"
    write_skill(skill, body="Use TOKEN=abc123456 for test only\n")

    draft = build_submission_draft(skill, home=tmp_path / "home")

    assert any("possible secret pattern" in warning for warning in draft.warnings)
    preview = json.loads(Path(draft.preview_path).read_text(encoding="utf-8"))
    assert "content_base64" not in json.dumps(preview)


def test_submit_requires_confirmation_unless_yes(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_registration(home)
    skill = tmp_path / "browser-qa"
    write_skill(skill)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    assert main(["--root", str(root), "community", "submit", str(skill)]) == 2
    assert "requires --yes" in capsys.readouterr().err


def test_community_install_verifies_sha_extracts_and_reindexes_metadata(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    archive = make_archive(tmp_path)
    digest = sha256_file(archive)
    private_key = trust_test_key(monkeypatch)

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/community/install"):
            return FakeResponse(
                json.dumps(
                    sign_community_payload(
                        {
                            "schema_version": 1,
                            "item": {"item_id": "comm_browser_qa", "name": "browser-qa", "status": "approved", "channel": "canary"},
                            "name": "browser-qa",
                            "install_plan": {
                                "collection": "community",
                                "version": "2026.06.08",
                                "archive_url": "https://community.example.test/browser-qa.zip",
                                "sha256": digest,
                                "skill_count": 1,
                            },
                        },
                        private_key,
                    )
                ).encode("utf-8")
            )
        if url.endswith("/browser-qa.zip"):
            return FakeResponse(archive.read_bytes())
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        result = CommunityClient(registered_state()).install_community_item(root, item_id="comm_browser_qa")

    assert result.installed is True
    assert (root / "registry" / "community" / "skills" / "browser-qa" / "SKILL.md").is_file()
    installed = list_installed_community_items(root)
    assert installed[0].source == "community"


def test_community_install_rejects_zip_path_traversal(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    private_key = trust_test_key(monkeypatch)
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "no")
    digest = sha256_file(archive)

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/community/install"):
            return FakeResponse(
                json.dumps(
                    sign_community_payload(
                        {
                            "schema_version": 1,
                            "item": {"item_id": "comm_bad", "name": "bad", "status": "approved", "channel": "canary"},
                            "install_plan": {
                                "collection": "community",
                                "version": "2026.06.08",
                                "archive_url": "https://community.example.test/bad.zip",
                                "sha256": digest,
                            },
                        },
                        private_key,
                    )
                ).encode("utf-8")
            )
        if url.endswith("/bad.zip"):
            return FakeResponse(archive.read_bytes())
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        with pytest.raises(UpdateError):
            CommunityClient(registered_state()).install_community_item(root, item_id="comm_bad")


def test_community_install_checksum_mismatch_fails_before_extract(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    archive = make_archive(tmp_path)
    private_key = trust_test_key(monkeypatch)

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/community/install"):
            return FakeResponse(
                json.dumps(
                    sign_community_payload(
                        {
                            "schema_version": 1,
                            "item": {"item_id": "comm_bad_sha", "name": "bad-sha", "status": "approved", "channel": "canary"},
                            "install_plan": {
                                "collection": "community",
                                "version": "2026.06.08",
                                "archive_url": "https://community.example.test/bad-sha.zip",
                                "sha256": "0" * 64,
                            },
                        },
                        private_key,
                    )
                ).encode("utf-8")
            )
        if url.endswith("/bad-sha.zip"):
            return FakeResponse(archive.read_bytes())
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        with pytest.raises(CommunityError):
            CommunityClient(registered_state()).install_community_item(root, item_id="comm_bad_sha")

    assert not (root / "registry" / "community" / "skills" / "browser-qa" / "SKILL.md").exists()
    assert not (root / ".unlimited-skills-community.json").exists()


def test_community_list_requires_signed_payload_and_filters_channel(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    private_key = trust_test_key(monkeypatch)
    response = sign_community_payload(
        {
            "items": [
                {"item_id": "canary_pack", "name": "canary", "kind": "skill-pack", "status": "approved", "channel": "canary"},
                {"item_id": "stable_pack", "name": "stable", "kind": "skill-pack", "status": "approved", "channel": "stable"},
                {"item_id": "pending_pack", "name": "pending", "kind": "skill-pack", "status": "pending_review", "channel": "canary"},
            ]
        },
        private_key,
    )

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/community/list"):
            return FakeResponse(json.dumps(response).encode("utf-8"))
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        items = CommunityClient(registered_state()).list_community_items_v2(root, channel="canary")

    assert [item.item_id for item in items] == ["canary_pack"]

    def unsigned_urlopen(request, timeout=30.0):
        return FakeResponse(json.dumps({"items": [{"item_id": "unsafe", "name": "unsafe"}]}).encode("utf-8"))

    with patch("urllib.request.urlopen", unsigned_urlopen):
        with pytest.raises(CommunityError):
            CommunityClient(registered_state()).list_community_items_v2(root)


def test_community_install_rejects_signed_but_unapproved_item(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    private_key = trust_test_key(monkeypatch)

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/community/install"):
            return FakeResponse(
                json.dumps(
                    sign_community_payload(
                        {
                            "item": {"item_id": "pending", "name": "pending", "status": "pending_review", "channel": "canary"},
                            "install_plan": {
                                "collection": "community",
                                "version": "2026.06.08",
                                "archive_url": "https://community.example.test/pending.zip",
                                "sha256": "0" * 64,
                            },
                        },
                        private_key,
                    )
                ).encode("utf-8")
            )
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        with pytest.raises(CommunityError, match="approved or published"):
            CommunityClient(registered_state()).install_community_item(root, item_id="pending")


def test_community_submission_status_withdraw_and_review_notes_commands(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    seen_paths: list[str] = []

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        seen_paths.append(url)
        if url.endswith("/v1/community/submission-status"):
            return FakeResponse(json.dumps({"submission_id": "sub_1", "status": "pending_review"}).encode("utf-8"))
        if url.endswith("/v1/community/withdraw"):
            return FakeResponse(json.dumps({"submission_id": "sub_1", "status": "withdrawn"}).encode("utf-8"))
        if url.endswith("/v1/community/review-notes"):
            return FakeResponse(json.dumps({"submission_id": "sub_1", "reviewer_notes": "needs docs"}).encode("utf-8"))
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["--root", str(root), "community", "submission-status", "sub_1"]) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "pending_review"
        assert main(["--root", str(root), "community", "withdraw", "sub_1"]) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "withdrawn"
        assert main(["--root", str(root), "community", "review-notes", "sub_1"]) == 0
        assert json.loads(capsys.readouterr().out)["reviewer_notes"] == "needs docs"

    assert any(path.endswith("/v1/community/withdraw") for path in seen_paths)


def test_community_install_falls_back_to_signed_catalog_when_endpoint_missing(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    archive = make_archive(tmp_path, collection="community")
    digest = sha256_file(archive)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    monkeypatch.setenv("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", f"community-test-key:{base64_urlsafe_encode(public_key)}")
    catalog = sign_manifest_for_tests(
        {
            "schema_version": 1,
            "manifest_type": "catalog-updates",
            "packs": [
                {
                    "pack_id": "comm_browser_qa",
                    "collection": "community",
                    "version": "2026.06.08",
                    "channel": "community",
                    "license": "registered-community-terms",
                    "min_core_version": "0.1.0",
                    "format": "skill-collection-zip-v1",
                    "requires_registration": True,
                    "archive": {"filename": "community.zip", "sha256": digest, "bytes": archive.stat().st_size},
                    "notes": "Browser QA pack",
                    "skill_count": 1,
                }
            ],
        },
        private_key,
        key_id="community-test-key",
    )

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/community/install"):
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=io.BytesIO(b'{"detail":"Not Found"}'))
        if url.endswith("/v1/catalog"):
            return FakeResponse(json.dumps(catalog).encode("utf-8"))
        if url.endswith("/v1/catalog/packs/community/2026.06.08/community.zip"):
            return FakeResponse(archive.read_bytes())
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        result = CommunityClient(registered_state()).install_community_item(root, item_id="comm_browser_qa")

    assert result.installed is True
    assert (root / "registry" / "community" / "skills" / "browser-qa" / "SKILL.md").is_file()
