from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

from unlimited_skills.cli import main
from unlimited_skills.org_status import load_cached_org_status
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity
from unlimited_skills.team import TeamState, save_team_state


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._stream = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(install_id="uls_inst_org", server_url="https://org.example.test", license_token="tok_org")
    )


def test_org_status_uses_local_cache_without_network(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    save_team_state(TeamState(team_id="team_1", team_name="Platform", role="member", status="approved"), home=home)
    (home / "org-status.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "last_refreshed_at": "2026-06-09T00:00:00Z",
                "plan": "business",
                "organization": {"org_id": "org_1", "name": "Acme", "role": "admin", "status": "active"},
                "entitlements": {"private_packs": {"status": "allowed"}},
            }
        ),
        encoding="utf-8",
    )

    with patch("urllib.request.urlopen") as urlopen:
        assert main(["org", "status", "--json"]) == 0

    urlopen.assert_not_called()
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "cache"
    assert payload["plan"] == "business"
    assert payload["entitlements"]["private_packs"] == "allowed"
    assert "tok_org" not in json.dumps(payload)


def test_org_status_refresh_requires_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["org", "status", "--refresh", "--json"]) == 2

    assert "Registration is required" in capsys.readouterr().err


def test_org_status_refresh_saves_redacted_cache(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)

    def fake_urlopen(request, timeout=30.0):
        assert request.full_url.endswith("/v1/org/status")
        return FakeResponse(
            {
                "schema_version": 1,
                "plan": "enterprise",
                "organization": {"org_id": "org_1", "name": "Acme", "role": "owner", "status": "active"},
                "entitlements": {"private_packs": True, "community_catalog": True, "team_sync": True},
                "archive_url": "https://example.invalid/private.zip",
                "license_token": "should-not-survive",
            }
        )

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["org", "status", "--refresh", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "hosted"
    assert payload["plan"] == "enterprise"
    serialized = json.dumps(payload)
    assert "archive_url" not in serialized
    assert "should-not-survive" not in serialized
    cached = load_cached_org_status(home)
    assert cached["plan"] == "enterprise"


def test_org_status_refresh_reports_service_errors(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
        assert main(["org", "status", "--refresh", "--json"]) == 2

    assert "unreachable" in capsys.readouterr().err.lower()
