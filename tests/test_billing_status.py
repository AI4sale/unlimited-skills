from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills.billing_status import BillingStatusError, save_billing_status, validate_billing_response
from unlimited_skills.cli import main
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(
            install_id="uls_inst_billing",
            server_url="https://billing.example.test",
            plan="registered-community",
            license_token="tok_billing_secret",
            features_enabled=("local_skill_hub",),
        )
    )


def test_billing_status_is_cached_and_network_free(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    save_billing_status(
        {
            "schema_version": 1,
            "source": "cached",
            "plan": "business",
            "entitlement_source": "organization",
            "subscription_status": "active",
            "billing_mode": "sandbox_only",
            "features_allowed": ["private_team_packs", "team_sync"],
            "last_refreshed_at": "2026-06-09T00:00:00Z",
        },
        home=home,
    )

    def fail_network(*_args, **_kwargs):
        raise AssertionError("billing status must not contact the hosted service")

    monkeypatch.setattr("unlimited_skills.billing_status.post_json", fail_network)
    assert main(["billing", "status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["plan"] == "business"
    assert payload["subscription_status"] == "active"
    assert payload["billing_mode"] == "sandbox_only"
    assert payload["privacy"]["tokens_included"] is False
    assert payload["privacy"]["checkout_urls_included"] is False
    assert payload["privacy"]["payment_card_data_included"] is False
    assert "tok_billing_secret" not in json.dumps(payload, sort_keys=True)


def test_billing_refresh_requires_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["billing", "refresh", "--json"]) == 2

    err = capsys.readouterr().err
    assert "Denial reason: unregistered" in err


def test_billing_refresh_accepts_registry_lifecycle_payload(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    calls = []

    def fake_post_json(url, payload, **_kwargs):
        calls.append({"url": url, "payload": payload})
        return {
            "schema_version": 1,
            "plan": "business",
            "entitlement_source": "organization",
            "subscription_status": "past_due",
            "billing_mode": "sandbox_only",
            "features_enabled": ["local_skill_hub"],
            "denied_features": [{"feature": "private_team_packs", "denial_reason": "billing_past_due"}],
            "denial_reason": "payment_failed",
        }

    monkeypatch.setattr("unlimited_skills.billing_status.post_json", fake_post_json)

    assert main(["billing", "refresh", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert calls[0]["url"].endswith("/v1/hub/billing-status")
    assert calls[0]["payload"]["include_sensitive"] is False
    assert payload["billing_status"]["subscription_status"] == "past_due"
    assert payload["billing_status"]["denial_reason"] == "past_due"
    assert payload["billing_status"]["features_denied"] == [{"denial_reason": "past_due", "feature": "private_team_packs"}]
    assert "tok_billing_secret" not in json.dumps(payload, sort_keys=True)


def test_billing_doctor_reports_sandbox_only_and_safe_denials(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    save_registration(registered_state(), home=home)
    save_billing_status(
        {
            "schema_version": 1,
            "source": "cached",
            "plan": "business",
            "subscription_status": "expired",
            "billing_mode": "sandbox_only",
        },
        home=home,
    )

    assert main(["billing", "doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is False
    assert payload["checks"]["checkout"]["available"] is False
    assert payload["checks"]["checkout"]["live_provider_enabled"] is False
    assert payload["checks"]["subscription_status"]["denial_reason"] == "expired"


def test_billing_response_rejects_checkout_and_payment_data() -> None:
    with pytest.raises(BillingStatusError, match="forbidden billing diagnostic fields"):
        validate_billing_response(
            {
                "schema_version": 1,
                "plan": "business",
                "subscription_status": "active",
                "checkout_url": "https://payments.example.test/session",
            }
        )
