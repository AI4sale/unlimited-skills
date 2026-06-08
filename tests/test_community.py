from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from unlimited_skills.cli import main
from unlimited_skills.community import (
    CommunityClient,
    CommunityError,
    build_submission_draft,
    list_installed_community_items,
)
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity
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
    write_registration(home)
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


def test_community_install_verifies_sha_extracts_and_reindexes_metadata(tmp_path: Path) -> None:
    root = tmp_path / "library"
    archive = make_archive(tmp_path)
    digest = sha256_file(archive)

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/community/install"):
            return FakeResponse(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "browser-qa",
                        "install_plan": {
                            "collection": "community",
                            "version": "2026.06.08",
                            "archive_url": "https://community.example.test/browser-qa.zip",
                            "sha256": digest,
                            "skill_count": 1,
                        },
                    }
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


def test_community_install_rejects_zip_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / "library"
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "no")
    digest = sha256_file(archive)

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/community/install"):
            return FakeResponse(
                json.dumps(
                    {
                        "schema_version": 1,
                        "install_plan": {
                            "collection": "community",
                            "version": "2026.06.08",
                            "archive_url": "https://community.example.test/bad.zip",
                            "sha256": digest,
                        },
                    }
                ).encode("utf-8")
            )
        if url.endswith("/bad.zip"):
            return FakeResponse(archive.read_bytes())
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        with pytest.raises(UpdateError):
            CommunityClient(registered_state()).install_community_item(root, item_id="comm_bad")


def test_community_install_checksum_mismatch_fails_before_extract(tmp_path: Path) -> None:
    root = tmp_path / "library"
    archive = make_archive(tmp_path)

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/community/install"):
            return FakeResponse(
                json.dumps(
                    {
                        "schema_version": 1,
                        "install_plan": {
                            "collection": "community",
                            "version": "2026.06.08",
                            "archive_url": "https://community.example.test/bad-sha.zip",
                            "sha256": "0" * 64,
                        },
                    }
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
