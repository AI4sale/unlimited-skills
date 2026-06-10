from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.private_packs import write_private_pack_metadata
from unlimited_skills.billing_status import save_billing_status
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
    save_billing_status(
        {
            "schema_version": 1,
            "source": "cached",
            "plan": "business",
            "entitlement_source": "organization",
            "subscription_status": "past_due",
            "billing_mode": "sandbox_only",
            "denied_features": [{"feature": "private_team_packs", "denial_reason": "payment_failed"}],
            "denial_reason": "billing_past_due",
        },
        home=home,
    )
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
    assert payload["plan"]["registered"] is True
    assert payload["plan"]["privacy"]["tokens_included"] is False
    assert payload["billing"]["subscription_status"] == "past_due"
    assert payload["billing"]["denial_reason"] == "past_due"
    assert payload["billing"]["privacy"]["checkout_urls_included"] is False
    assert payload["billing"]["privacy"]["payment_card_data_included"] is False
    assert payload["catalog_browser"]["queries_included"] is False
    assert payload["catalog_browser"]["item_names_included"] is False
    assert payload["catalog_feedback"]["explicit_feedback_only"] is True
    assert payload["catalog_feedback"]["raw_feedback_included"] is False
    assert payload["private_packs"]["sha_mismatch_count"] == 1
    assert payload["privacy"]["skill_bodies_included"] is False
    assert payload["privacy"]["local_paths_included"] is False
    assert payload["privacy"]["catalog_feedback_included"] is False
    serialized = json.dumps(payload, sort_keys=True)
    assert "secret private skills" not in serialized
    assert "team_pack_secret" not in serialized
    assert "uls_support_token" not in serialized
    assert '"checkout_url":' not in serialized
    assert '"payment_link":' not in serialized
    assert "browser-qa-pack" not in serialized
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
