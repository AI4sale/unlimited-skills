from __future__ import annotations

import io
import json
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from unlimited_skills.cli import main
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity
from unlimited_skills.team import TeamState, audit_log_path, save_team_state
from unlimited_skills.updates import sha256_file


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
        RegistrationState(install_id="uls_inst_master", server_url="https://team.example.test", license_token="tok_test")
    )


def write_registration(home: Path) -> None:
    save_registration(registered_state(), home=home / ".unlimited-skills")


def write_team(home: Path, *, status: str = "approved", role: str = "master") -> None:
    save_team_state(
        TeamState(
            team_id="team_123",
            team_name="Example Team",
            team_token="team_tok",
            install_id="uls_inst_master",
            role=role,
            status=status,
            limits={"max_instances": 10, "auto_approval_max_hours": 24},
        ),
        home=home / ".unlimited-skills",
    )


def write_skill(root: Path) -> None:
    skill = root / "local" / "skills" / "local-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: local-skill\ndescription: local\n---\n\n# local\n", encoding="utf-8")


def make_archive(tmp_path: Path, *, traversal: bool = False) -> Path:
    archive = tmp_path / "team.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        if traversal:
            zf.writestr("../escape.txt", "no")
        else:
            zf.writestr("team-web/skills/browser-qa/SKILL.md", "---\nname: browser-qa\ndescription: qa\n---\n\n# qa\n")
    return archive


def test_unregistered_team_sync_returns_friendly_error(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    assert main(["--root", str(tmp_path / "library"), "team", "sync", "--dry-run"]) == 2

    assert "Registration is required for Team Free sync" in capsys.readouterr().err


def test_unregistered_local_search_still_works(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_skill(root)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    monkeypatch.setenv("UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC", "1")

    assert main(["--root", str(root), "search", "local", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["name"] == "local-skill"


def test_team_status_json_redacts_auth_state(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    write_registration(home)
    write_team(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    assert main(["team", "status", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(payload)
    assert payload["redacted_auth_state"]["token_present"] is True
    assert payload["redacted_auth_state"]["proof_key_present"] is True
    assert "tok_test" not in serialized
    assert "device_private_key" not in serialized
    assert "team_tok" not in serialized


def test_team_auto_approval_duration_over_24h_is_rejected(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    write_registration(home)
    write_team(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    assert main(["team", "mode", "auto", "--duration", "48h"]) == 2

    assert "Team Free auto-approval is capped at 24 hours" in capsys.readouterr().err


def test_pending_approval_error_suggests_admin_approve(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    write_registration(home)
    write_team(home, status="pending", role="pending")
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    assert main(["--root", str(tmp_path / "library"), "team", "sync", "--dry-run"]) == 2

    assert "unlimited-skills team approve <install_id>" in capsys.readouterr().err


def test_member_limit_error_is_displayed_clearly(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    write_registration(home)
    write_team(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    def fake_urlopen(request, timeout=30.0):
        body = b'{"error":{"code":"member_limit_reached"}}'
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(body))

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["team", "members"]) == 2

    assert "Team Free supports up to 10 approved instances" in capsys.readouterr().err


def test_team_sync_dry_run_json_writes_no_library_files_and_logs_audit(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_registration(home)
    write_team(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    def fake_urlopen(request, timeout=30.0):
        assert request.full_url.endswith("/v1/teams/team_123/sync")
        return FakeResponse(
            json.dumps(
                {
                    "schema_version": 1,
                    "team_id": "team_123",
                    "plan": "team-free",
                    "limits": {"max_instances": 10, "auto_approval_max_hours": 24},
                    "collections": [
                        {
                            "collection": "team-web",
                            "version": "2026.06.08",
                            "visibility": "team-free",
                            "archive_url": "https://team.example.test/team-web.zip",
                            "sha256": "a" * 64,
                            "format": "skill-collection-zip-v1",
                            "archive_size": 1024,
                        }
                    ],
                    "removals": [],
                }
            ).encode("utf-8")
        )

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["--root", str(root), "team", "sync", "--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["plan"]["collections"][0]["collection"] == "team-web"
    assert not (root / "team-web").exists()
    log = audit_log_path(home / ".unlimited-skills").read_text(encoding="utf-8")
    assert "team_sync_dry_run" in log
    assert "tok_test" not in log
    assert "Bearer" not in log


def test_team_sync_yes_applies_verified_archive_and_reindexes(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    archive = make_archive(tmp_path)
    digest = sha256_file(archive)
    write_registration(home)
    write_team(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url
        if url.endswith("/v1/teams/team_123/sync"):
            return FakeResponse(json.dumps({"collections": [{"collection": "team-web", "version": "2026.06.08", "archive_url": "https://team.example.test/team.zip", "sha256": digest}]}).encode("utf-8"))
        if url.endswith("/team.zip"):
            return FakeResponse(archive.read_bytes())
        raise AssertionError(url)

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["--root", str(root), "team", "sync", "--yes", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"][0]["collection"] == "team-web"
    assert (root / "team-web" / "skills" / "browser-qa" / "SKILL.md").is_file()
    assert (root / ".unlimited-skills-index.json").is_file()
    assert "team_sync_applied" in audit_log_path(home / ".unlimited-skills").read_text(encoding="utf-8")


def test_team_sync_rejects_zip_path_traversal(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    archive = make_archive(tmp_path, traversal=True)
    digest = sha256_file(archive)
    write_registration(home)
    write_team(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url
        if url.endswith("/v1/teams/team_123/sync"):
            return FakeResponse(json.dumps({"collections": [{"collection": "team-web", "version": "2026.06.08", "archive_url": "https://team.example.test/bad.zip", "sha256": digest}]}).encode("utf-8"))
        if url.endswith("/bad.zip"):
            return FakeResponse(archive.read_bytes())
        raise AssertionError(url)

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["--root", str(root), "team", "sync", "--yes"]) == 2

    assert "Unsafe archive path" in capsys.readouterr().err


def test_team_revoke_requires_confirmation_unless_yes(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    write_registration(home)
    write_team(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    assert main(["team", "revoke", "uls_inst_old", "--reason", "old machine"]) == 2

    assert "Pass --yes" in capsys.readouterr().err


def test_team_approve_and_revoke_write_redacted_audit(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    write_registration(home)
    write_team(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    def fake_urlopen(request, timeout=30.0):
        if request.full_url.endswith("/approve"):
            return FakeResponse(b'{"status":"approved","request_id":"req_approve"}')
        if request.full_url.endswith("/revoke"):
            return FakeResponse(b'{"status":"revoked","request_id":"req_revoke"}')
        raise AssertionError(request.full_url)

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["team", "approve", "uls_inst_new", "--json"]) == 0
        assert main(["team", "revoke", "uls_inst_old", "--reason", "old machine", "--yes", "--json"]) == 0

    log = audit_log_path(home / ".unlimited-skills").read_text(encoding="utf-8")
    assert "team_member_approved" in log
    assert "team_member_revoked" in log
    assert "tok_test" not in log
    assert "Authorization" not in log
