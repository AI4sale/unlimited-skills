from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.cli import main
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity
from unlimited_skills.setup_wizard import build_setup_report


def test_setup_private_packs_warns_without_registration(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))

    payload = build_setup_report(home / "library", private_packs=True)

    assert payload["sections"]["private_packs"]["status"] == "warn"
    assert payload["sections"]["private_packs"]["checks"]["registered"] is False
    assert payload["privacy"]["skill_bodies_included"] is False


def test_setup_cli_outputs_private_pack_checks(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / ".unlimited-skills"
    root = home / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    state = with_install_identity(RegistrationState(install_id="uls_inst_setup", server_url="http://127.0.0.1:8765", license_token="uls_setup_token"))
    save_registration(state, home=home)

    assert main(["--root", str(root), "setup", "--private-packs", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["setup"]["private_packs"] is True
    assert payload["sections"]["private_packs"]["checks"]["registered"] is True
    assert "uls_setup_token" not in json.dumps(payload)
