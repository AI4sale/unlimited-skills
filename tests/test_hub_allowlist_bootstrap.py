from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from unlimited_skills.cli import main
from unlimited_skills.hub import create_hub_token
from unlimited_skills.hub_allowlist import allowlist_sha256
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "hub" / "allowlist-fixture.v1.json"


def valid_allowlist() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def write_allowlist(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(
            install_id="uls_inst_hub_allowlist",
            server_url="https://updates.example.test",
            plan="registered-community",
            license_token="tok_secret_hub_allowlist",
        )
    )


def test_hub_init_creates_layout_and_config_dirs(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "init", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "initialized"
    assert (uls_home / "hub" / "hub.json").is_file()
    assert (uls_home / "hub" / "clients.json").is_file()
    assert (uls_home / "hub" / "logs").is_dir()
    assert payload["allowlist"]["present"] is False


def test_hub_init_allowlist_fixture_validates_and_caches(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "init", "--allowlist", str(FIXTURE), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    cached = uls_home / "hub" / "allowlist.v1.json"
    meta = uls_home / "hub" / "allowlist.meta.json"
    assert cached.is_file()
    assert meta.is_file()
    assert payload["allowlist"]["distribution_mode"] == "allowlist_only"
    assert payload["allowlist"]["full_catalog_distribution_allowed"] is False
    assert payload["allowlist"]["requires_registration"] is True
    assert payload["allowlist"]["free_active_client_instance_limit"] == 100

    assert main(["hub", "status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["allowlist"]["present"] is True
    assert status["allowlist"]["full_catalog_distribution_allowed"] is False


def test_invalid_allowlist_is_rejected(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    invalid = valid_allowlist()
    invalid["schema_version"] = 2
    path = write_allowlist(tmp_path / "invalid.json", invalid)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "init", "--allowlist", str(path)]) == 2

    assert "schema_version must be 1" in capsys.readouterr().err


def test_allowlist_with_full_catalog_distribution_is_rejected(tmp_path: Path, monkeypatch, capsys) -> None:
    data = valid_allowlist()
    data["policy"]["full_catalog_distribution_allowed"] = True
    path = write_allowlist(tmp_path / "full-catalog.json", data)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["hub", "init", "--allowlist", str(path)]) == 2

    assert "full_catalog_distribution_allowed must be false" in capsys.readouterr().err


def test_allowlist_with_blocked_skill_is_rejected(tmp_path: Path, monkeypatch, capsys) -> None:
    data = valid_allowlist()
    data["allowlist"].append(
        {
            "skill_id": "blocked-fixture",
            "name": "blocked-fixture",
            "collection": "fixture-pack",
            "sha256": "c" * 64,
            "primary_category": "HUB_READY_PURE_TEXT",
            "hub_behavior": "distribute_body",
        }
    )
    path = write_allowlist(tmp_path / "blocked.json", data)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["hub", "init", "--allowlist", str(path)]) == 2

    assert "includes excluded skill fixture-pack/blocked-fixture" in capsys.readouterr().err


def test_allowlist_with_embedded_skill_body_is_rejected(tmp_path: Path, monkeypatch, capsys) -> None:
    data = valid_allowlist()
    data["allowlist"][0]["body"] = "---\nname: private\n---\n\nPRIVATE_BODY_SENTINEL"
    path = write_allowlist(tmp_path / "body.json", data)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["hub", "init", "--allowlist", str(path)]) == 2

    assert "must not embed a skill body" in capsys.readouterr().err


def test_hub_serve_uses_cached_allowlist_when_explicit_path_absent(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    root = tmp_path / "library"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    assert main(["hub", "init", "--allowlist", str(FIXTURE), "--json"]) == 0
    capsys.readouterr()
    create_hub_token("server", home=uls_home)
    calls: list[dict[str, object]] = []

    def fake_run(app: str, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    assert main(["--root", str(root), "hub", "serve", "--host", "127.0.0.1"]) == 0

    assert calls[0]["app"] == "unlimited_skills.hub_server:create_app"
    assert calls[0]["factory"] is True
    assert calls[0]["host"] == "127.0.0.1"
    assert str(uls_home / "hub" / "allowlist.v1.json") == __import__("os").environ["UNLIMITED_SKILLS_HUB_ALLOWLIST"]


def test_hub_serve_fails_when_no_cached_allowlist_and_no_explicit_path(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "serve", "--host", "127.0.0.1"]) == 2

    assert "No hub allowlist is configured" in capsys.readouterr().err


def test_unregistered_hub_sync_fails_friendly_and_local_commands_still_work(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    root = tmp_path / "library"
    skill = root / "local" / "skills" / "local-only" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("---\nname: local-only\ndescription: Local only\n---\n\n# Local only\n", encoding="utf-8")
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "sync"]) == 2
    assert "Registration is required for Local Skill Hub allowlist sync. The MIT local core still works offline." in capsys.readouterr().err

    assert main(["--root", str(root), "search", "local only", "--mode", "lexical", "--no-native-sync"]) == 0
    assert "local-only [local]" in capsys.readouterr().out


def test_hub_sync_dry_run_writes_nothing(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    data = valid_allowlist()

    def fake_post_json(url, payload, **kwargs):
        assert url == "https://updates.example.test/v1/hub/allowlist"
        assert payload["current_allowlist_sha256"] == ""
        return {
            "schema_version": 1,
            "distribution_mode": "allowlist_only",
            "catalog_audit_verdict": "YES_WITH_ALLOWLIST",
            "full_catalog_distribution_allowed": False,
            "requires_registration": True,
            "free_active_client_instance_limit": 100,
            "allowlist": data,
            "allowlist_sha256": allowlist_sha256(data),
            "notes": "fixture dry run",
        }

    monkeypatch.setattr("unlimited_skills.hub.post_json", fake_post_json)

    assert main(["hub", "sync", "--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["full_catalog_distribution_allowed"] is False
    assert payload["requires_registration"] is True
    assert not (uls_home / "hub" / "allowlist.v1.json").exists()


def test_hub_sync_caches_registered_allowlist(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    data = valid_allowlist()

    def fake_post_json(_url, _payload, **_kwargs):
        return {
            "schema_version": 1,
            "distribution_mode": "allowlist_only",
            "catalog_audit_verdict": "YES_WITH_ALLOWLIST",
            "full_catalog_distribution_allowed": False,
            "requires_registration": True,
            "free_active_client_instance_limit": 100,
            "allowlist": data,
            "allowlist_sha256": allowlist_sha256(data),
            "notes": "fixture sync",
        }

    monkeypatch.setattr("unlimited_skills.hub.post_json", fake_post_json)

    assert main(["hub", "sync", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is False
    assert payload["distribution_mode"] == "allowlist_only"
    assert payload["full_catalog_distribution_allowed"] is False
    assert (uls_home / "hub" / "allowlist.v1.json").is_file()
    assert json.loads((uls_home / "hub" / "allowlist.v1.json").read_text(encoding="utf-8"))["policy"]["requires_registration"] is True
