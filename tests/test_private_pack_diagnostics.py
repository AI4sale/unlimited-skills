from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.private_pack_diagnostics import (
    assert_private_pack_diagnostics_safe,
    private_pack_local_summary,
    private_pack_setup_summary,
)
from unlimited_skills.private_packs import write_private_pack_metadata
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity


def save_registered(home: Path) -> None:
    state = with_install_identity(RegistrationState(install_id="uls_inst_private_diag", server_url="http://127.0.0.1:8765", license_token="uls_private_token"))
    save_registration(state, home=home)


def write_private_metadata(root: Path) -> None:
    target = root / "registry" / "private" / "team_pack_alpha"
    target.mkdir(parents=True)
    write_private_pack_metadata(
        root,
        {
            "schema_version": 1,
            "items": {
                "team_pack_alpha": {
                    "team_id": "team_alpha",
                    "name": "alpha private skills",
                    "version": "1.0.0",
                    "latest_version": "1.1.0",
                    "sha256": "a" * 64,
                    "target": "registry/private/team_pack_alpha",
                    "source": "private-team-pack",
                    "revoked": True,
                    "last_error_code": "failed_signature",
                }
            },
        },
    )


def test_private_pack_local_summary_counts_status_without_names_or_bodies(tmp_path: Path) -> None:
    root = tmp_path / "library"
    write_private_metadata(root)

    payload = private_pack_local_summary(root)

    assert payload["installed_count"] == 1
    assert payload["revoked_count"] == 1
    assert payload["stale_count"] == 1
    assert payload["failed_signature_count"] == 1
    assert payload["skill_names_included"] is False
    assert payload["skill_bodies_included"] is False
    assert payload["pack_refs"] == []
    serialized = json.dumps(payload, sort_keys=True)
    assert "alpha private skills" not in serialized
    assert "team_pack_alpha" not in serialized
    assert "SKILL.md" not in serialized
    assert_private_pack_diagnostics_safe(payload)


def test_private_pack_setup_summary_reports_registration_and_trust(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / ".unlimited-skills"
    root = home / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    monkeypatch.setattr("unlimited_skills.private_pack_diagnostics.trusted_manifest_key_records", lambda: [])
    save_registered(home)
    write_private_metadata(root)

    payload = private_pack_setup_summary(root)

    assert payload["status"] == "warn"
    assert payload["checks"]["registered"] is True
    assert payload["checks"]["trust_key"] == "missing"
    assert "failed_signature" in payload["checks"]["last_error_codes"]
    assert_private_pack_diagnostics_safe(payload)
