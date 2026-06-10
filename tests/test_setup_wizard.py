from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from unlimited_skills.cli import main
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity
from unlimited_skills.setup_wizard import build_setup_report, format_setup_text


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(
            install_id="uls_inst_setup_test",
            server_url="https://updates.example.test",
            plan="registered-community",
            license_token="uls_secret_setup_token",
            telemetry="off",
            features_enabled=("hosted_catalog", "hub"),
        )
    )


def block_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("setup wizard must not contact hosted services")


def test_local_only_dry_run_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))

    with patch("urllib.request.urlopen", block_network):
        payload = build_setup_report(root, mode="local-only", dry_run=True)

    assert payload["mode"] == "local-only"
    assert payload["dry_run"] is True
    assert payload["writes_performed"] is False
    assert payload["hosted_calls_performed"] is False
    assert payload["destructive_changes"] is False
    assert not root.exists()
    assert "registration" not in payload["components"]
    assert any("reindex" in command for command in payload["next_commands"])


def test_local_only_creates_missing_local_skills_without_deleting_existing_files(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    existing = root / "local" / "skills" / "custom" / "SKILL.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("---\nname: custom\n---\n\nKeep me.\n", encoding="utf-8")
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))

    payload = build_setup_report(root, mode="local-only", dry_run=False)

    assert payload["writes_performed"] is False
    assert existing.read_text(encoding="utf-8").endswith("Keep me.\n")
    assert (root / "local" / "skills").is_dir()


def test_local_only_creates_library_on_first_run(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))

    payload = build_setup_report(root, mode="local-only", dry_run=False)

    assert payload["writes_performed"] is True
    assert (root / "local" / "skills").is_dir()


def test_registered_setup_is_local_only_and_redacted(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    state = registered_state()
    save_registration(state, home=home)

    with patch("urllib.request.urlopen", block_network):
        payload = build_setup_report(root, mode="registered", dry_run=True)

    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["components"]["registration"]["registered"] is True
    assert payload["components"]["registration"]["license_token"] == "present"
    assert payload["components"]["service"]["snapshot_version"] == 2
    assert payload["components"]["service"]["network"]["performed"] is False
    assert payload["components"]["service"]["registration"]["hosted_credential"] == "present"
    assert payload["hosted_calls_performed"] is False
    assert payload["writes_performed"] is False
    assert not root.exists()
    assert "uls_secret_setup_token" not in serialized
    assert state.device_private_key not in serialized
    assert "service test-registration --dry-run" in serialized


def test_hub_setup_reports_allowlist_token_and_remote_next_commands(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))

    payload = build_setup_report(root, mode="hub", dry_run=True)
    text = format_setup_text(payload)

    assert payload["mode"] == "hub"
    assert payload["components"]["hub"]["active_token_count"] == 0
    assert "unlimited-skills hub init --allowlist <allowlist.v1.json>" in payload["next_commands"]
    assert "unlimited-skills hub token create --label default --json" in payload["next_commands"]
    assert "remote configure" in text


def test_enterprise_setup_reports_policy_status_without_installing_policy(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))

    payload = build_setup_report(root, mode="enterprise", dry_run=True)

    assert payload["mode"] == "enterprise"
    assert payload["components"]["enterprise"]["policy"]["installed"] is False
    assert not (home / "policy" / "policy.json").exists()
    assert "unlimited-skills policy explain" in payload["next_commands"]


def test_setup_cli_json_and_doctor_modes(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    monkeypatch.setenv("UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC", "1")

    assert main(["--root", str(root), "setup", "--local-only", "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "local-only"
    assert payload["dry_run"] is True
    assert not root.exists()

    assert main(["--root", str(root), "setup", "doctor", "--json"]) == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["mode"] == "overview"
    assert doctor_payload["components"]["doctor"]["version"] == payload["client"]["version"]
    assert doctor_payload["writes_performed"] is False
    assert not root.exists()


def test_setup_cli_text_output_is_redacted(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    state = registered_state()
    save_registration(state, home=home)

    assert main(["--root", str(root), "setup", "--registered", "--dry-run"]) == 0
    output = capsys.readouterr().out

    assert "Unlimited Skills setup" in output
    assert "Hosted calls: none" in output
    assert "uls_secret_setup_token" not in output
    assert state.device_private_key not in output
