from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.private_packs import write_private_pack_metadata
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity
from unlimited_skills.support_bundle import assert_support_bundle_safe, build_support_bundle_manifest


def test_support_bundle_private_pack_summary_is_redacted(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / ".unlimited-skills"
    root = home / "library"
    target = root / "registry" / "private" / "team_pack_secret"
    target.mkdir(parents=True)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    state = with_install_identity(RegistrationState(install_id="uls_inst_support", server_url="http://127.0.0.1:8765", license_token="uls_support_token"))
    save_registration(state, home=home)
    write_private_pack_metadata(
        root,
        {
            "schema_version": 1,
            "items": {
                "team_pack_secret": {
                    "team_id": "team_secret",
                    "name": "secret private skills",
                    "version": "1.0.0",
                    "sha256": "b" * 64,
                    "target": "registry/private/team_pack_secret",
                    "source": "private-team-pack",
                    "last_error_code": "sha_mismatch",
                }
            },
        },
    )

    payload = build_support_bundle_manifest(root)

    assert payload["private_packs"]["installed_count"] == 1
    assert payload["private_packs"]["sha_mismatch_count"] == 1
    assert payload["privacy"]["skill_bodies_included"] is False
    assert payload["privacy"]["local_paths_included"] is False
    serialized = json.dumps(payload, sort_keys=True)
    assert "secret private skills" not in serialized
    assert "team_pack_secret" not in serialized
    assert "uls_support_token" not in serialized
    assert "SKILL.md" not in serialized
    assert_support_bundle_safe(payload)


def test_support_bundle_can_include_hashed_private_pack_refs(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / ".unlimited-skills"
    root = home / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(with_install_identity(RegistrationState(install_id="uls_inst_support", server_url="http://127.0.0.1:8765", license_token="uls_support_token")), home=home)
    write_private_pack_metadata(root, {"schema_version": 1, "items": {"team_pack_secret": {"target": "", "source": "private-team-pack"}}})

    payload = build_support_bundle_manifest(root, include_private_pack_refs=True)

    assert payload["private_packs"]["pack_refs"] == ["pack:e5376a07f257"]
    assert "team_pack_secret" not in json.dumps(payload, sort_keys=True)
    assert_support_bundle_safe(payload)
