from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from unlimited_skills.cli import main
from unlimited_skills import doctor as doctor_mod
from unlimited_skills.doctor import build_doctor_report, doctor_json, format_doctor_text


def write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\n\n# {name}\n", encoding="utf-8")


def test_doctor_works_with_empty_temp_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = home / ".unlimited-skills" / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    with patch.object(Path, "home", return_value=home):
        report = build_doctor_report(root)

    assert report["registration"]["registered"] is False
    assert report["registration"]["plan"] == "community-core"
    assert report["library"]["exists"] is False
    assert "license_token" not in json.dumps(report)
    assert "device_private_key" not in json.dumps(report)


def test_doctor_cli_json_is_valid_and_registration_free(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = home / ".unlimited-skills" / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    with patch.object(Path, "home", return_value=home):
        assert main(["--root", str(root), "doctor", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["registration"]["registered"] is False
    assert payload["registration"]["hosted_token"] == "missing"


def test_doctor_redacts_registration_token_and_device_key(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    uls_home = home / ".unlimited-skills"
    uls_home.mkdir(parents=True)
    (uls_home / "registration.json").write_text(
        json.dumps(
            {
                "install_id": "uls_inst_test",
                "server_url": "https://updates.example.test",
                "plan": "registered-community",
                "license_token": "tok_secret_value",
                "device_private_key": "private_key_secret_value",
                "device_public_key": "public",
                "key_thumbprint": "thumb",
                "telemetry": "off",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    with patch.object(Path, "home", return_value=home):
        output = doctor_json(build_doctor_report(uls_home / "library"))

    assert "tok_secret_value" not in output
    assert "private_key_secret_value" not in output
    assert '"hosted_token": "present"' in output


def test_doctor_warns_when_hermes_has_multiple_visible_skills(tmp_path: Path, monkeypatch) -> None:
    hermes_home = tmp_path / ".hermes"
    write_skill(hermes_home / "skills", "alpha")
    write_skill(hermes_home / "skills", "beta")
    write_skill(hermes_home / "skills", "unlimited-skills")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    with patch.object(Path, "home", return_value=tmp_path):
        report = build_doctor_report(tmp_path / ".unlimited-skills" / "library", agent="hermes")

    hermes = report["agents"]["hermes"]
    assert hermes["status"] == "warn"
    assert hermes["context_reduction_status"] == "risk"
    assert "Hermes may load visible skills into startup context" in " ".join(hermes["recommendations"])


def test_doctor_reports_hermes_router_only_context_reduction_ok(tmp_path: Path, monkeypatch) -> None:
    hermes_home = tmp_path / ".hermes"
    write_skill(hermes_home / "skills", "unlimited-skills")
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    with patch.object(Path, "home", return_value=tmp_path):
        report = build_doctor_report(tmp_path / ".unlimited-skills" / "library", agent="hermes")

    hermes = report["agents"]["hermes"]
    assert hermes["status"] == "ok"
    assert hermes["context_reduction_status"] == "ok"
    assert hermes["router_present"] is True


def test_doctor_reports_fallback_truth_instead_of_calling_multilingual_search_dead(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / ".unlimited-skills" / "library"
    root.mkdir(parents=True)
    (root / ".unlimited-skills-index.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        doctor_mod,
        "_runtime_deps_summary",
        lambda: {
            "server_extra_present": False,
            "vector_extra_present": False,
            "multilingual_ready": False,
        },
    )
    with patch.object(Path, "home", return_value=tmp_path):
        report = build_doctor_report(root)

    assert report["runtime_deps"]["native_language_search_ready"] is False
    assert report["runtime_deps"]["warm_daemon_ready"] is False
    rendered = format_doctor_text(report)
    assert "English-keyword fallback" in rendered
    assert "search is dead" not in rendered
    assert 'unlimited-skills[vector]' in rendered
