from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.cli import main
from unlimited_skills.hub_entitlements import save_entitlements
from unlimited_skills.plan_status import explain_feature, normalize_denial_reason
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(
            install_id="uls_inst_plan",
            server_url="https://plans.example.test",
            plan="registered-community",
            license_token="tok_plan_secret",
            features_enabled=("local_skill_hub",),
        )
    )


def test_plan_status_is_cached_and_network_free(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    save_entitlements(
        {
            "schema_version": 1,
            "source": "cached",
            "plan": "business",
            "status": "active",
            "features_enabled": ["local_skill_hub", "private_team_packs", "team_sync"],
            "limits": {"max_hub_clients": 100, "max_private_packs": 25, "release_channels": ["stable", "alpha"]},
            "policy": {"hub_distribution_mode": "allowlist_only", "hosted_query_forwarding_allowed": False, "team_sync_enabled": True},
            "last_heartbeat_at": "2026-06-09T00:00:00Z",
            "offline_grace_until": "2999-01-01T00:00:00Z",
        },
        home=home,
    )

    def fail_network(*_args, **_kwargs):
        raise AssertionError("plan status must not contact the hosted service")

    monkeypatch.setattr("unlimited_skills.hub_entitlements.post_json", fail_network)
    assert main(["plan", "status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["plan"] == "business"
    assert payload["limits"]["max_private_packs"] == 25
    assert payload["privacy"]["tokens_included"] is False
    assert "tok_plan_secret" not in json.dumps(payload, sort_keys=True)


def test_plan_refresh_requires_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["plan", "refresh", "--json"]) == 2

    err = capsys.readouterr().err
    assert "Denial reason: unregistered" in err


def test_plan_refresh_accepts_registry_entitlement_payload(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    calls = []

    def fake_post_json(url, payload, **_kwargs):
        calls.append({"url": url, "payload": payload})
        return {
            "schema_version": 1,
            "plan": "enterprise",
            "status": "active",
            "features_enabled": ["local_skill_hub", "private_team_packs", "team_sync", "enterprise_policy_sync"],
            "active_client_limit": 1000,
            "max_private_packs": 250,
            "private_pack_namespaces": ["*"],
            "release_channels": ["stable", "enterprise"],
        }

    monkeypatch.setattr("unlimited_skills.hub_entitlements.post_json", fake_post_json)

    assert main(["plan", "refresh", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert calls[0]["url"].endswith("/v1/hub/entitlements")
    assert payload["plan_status"]["plan"] == "enterprise"
    assert payload["plan_status"]["limits"]["max_hub_clients"] == 1000
    assert payload["plan_status"]["limits"]["max_private_packs"] == 250
    assert "tok_plan_secret" not in json.dumps(payload, sort_keys=True)


def test_plan_explain_and_doctor_denial_vocabulary(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))

    assert normalize_denial_reason("no_private_pack_entitlement") == "no_entitlement"
    assert explain_feature("private_team_packs", home=home)["denial_reason"] == "unregistered"

    assert main(["plan", "explain", "unknown-feature", "--json"]) == 0
    unknown = json.loads(capsys.readouterr().out)
    assert unknown["denial_reason"] == "unknown_feature"

    assert main(["plan", "doctor", "--json"]) == 0
    doctor = json.loads(capsys.readouterr().out)
    assert "unregistered" in doctor["denial_vocabulary"]
    assert doctor["checks"]["registration"]["denial_reason"] == "unregistered"


def test_plan_explain_uses_billing_lifecycle_denial_reasons(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    save_entitlements(
        {
            "schema_version": 1,
            "source": "cached",
            "plan": "business",
            "status": "past_due",
            "features_enabled": ["local_skill_hub", "private_team_packs"],
            "limits": {"max_hub_clients": 100, "max_private_packs": 25},
            "policy": {"hub_distribution_mode": "allowlist_only", "hosted_query_forwarding_allowed": False},
            "offline_grace_until": "2999-01-01T00:00:00Z",
        },
        home=home,
    )

    payload = explain_feature("private_team_packs", home=home)

    assert payload["allowed"] is False
    assert payload["denial_reason"] == "past_due"
