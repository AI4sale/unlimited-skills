from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from unlimited_skills.cli import main
from unlimited_skills.hub import create_hub_token
from unlimited_skills.hub_entitlements import (
    apply_entitlements,
    build_heartbeat_payload,
    entitlement_summary,
    has_forbidden_heartbeat_fields,
    save_entitlements,
)
from unlimited_skills.hub_server import create_app
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity


def registered_state(server_url: str = "https://updates.example.test") -> RegistrationState:
    return with_install_identity(
        RegistrationState(
            install_id="uls_inst_entitlement",
            server_url=server_url,
            plan="registered-community",
            license_token="tok_secret_entitlement",
            features_enabled=("local_skill_hub",),
        )
    )


def write_skill(root: Path, name: str = "pure-skill") -> None:
    skill = root / "registry" / "test-pack" / "skills" / name / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(f"---\nname: {name}\ndescription: Security review\n---\n\n# {name}\n", encoding="utf-8")


def write_allowlist(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_audit": {"verdict": "YES_WITH_ALLOWLIST", "total_skills_scanned": 1},
                "policy": {
                    "default_distribution_mode": "allowlist_only",
                    "full_catalog_distribution_allowed": False,
                    "requires_registration": True,
                    "free_active_client_instance_limit": 100,
                    "hub_executes_skills": False,
                    "hosted_registry_receives_search_queries_by_default": False,
                },
                "allowlist": [
                    {
                        "skill_id": "pure-skill",
                        "name": "pure-skill",
                        "collection": "test-pack",
                        "sha256": "a" * 64,
                        "source": "registered",
                        "primary_category": "HUB_READY_PURE_TEXT",
                        "hub_behavior": "distribute_body",
                        "risk_level": "none",
                    }
                ],
                "local_install_plan_candidates": [],
                "excluded": {"blocked": [], "local_only": [], "needs_human_review": [], "retrieval_only": []},
                "counts": {"allowlist_total": 1},
            }
        ),
        encoding="utf-8",
    )


def test_heartbeat_dry_run_sends_nothing_and_excludes_forbidden_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    home = tmp_path / "home" / ".unlimited-skills"
    save_registration(registered_state(), home=home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))

    def fail_post_json(*_args, **_kwargs):
        raise AssertionError("dry-run heartbeat must not call hosted service")

    monkeypatch.setattr("unlimited_skills.hub_entitlements.post_json", fail_post_json)

    assert main(["hub", "heartbeat", "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["dry_run"] is True
    assert payload["request"]["install_id"] == "uls_inst_entitlement"
    assert has_forbidden_heartbeat_fields(payload["request"]) == []
    assert "secret customer query" not in serialized
    assert "pure-skill" not in serialized
    assert "tok_secret_entitlement" not in serialized
    assert "device_private_key" not in serialized


def test_fake_entitlement_refresh_updates_max_clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    home = tmp_path / "home" / ".unlimited-skills"
    save_registration(registered_state(), home=home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    calls: list[dict] = []

    def fake_post_json(url, payload, **_kwargs):
        calls.append({"url": url, "payload": payload})
        return {
            "schema_version": 1,
            "plan": "business",
            "features_enabled": ["local_skill_hub", "signed_manifests", "team_sync_enabled"],
            "limits": {"max_hub_clients": 250},
            "policy": {
                "hub_distribution_mode": "allowlist_only",
                "signed_manifests_required": True,
                "hosted_query_forwarding_allowed": False,
                "team_sync_enabled": True,
            },
            "grace": {"offline_grace_until": "2026-06-16T00:00:00Z"},
        }

    monkeypatch.setattr("unlimited_skills.hub_entitlements.post_json", fake_post_json)

    assert main(["hub", "license", "refresh", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert calls[0]["url"].endswith("/v1/hub/entitlements")
    assert has_forbidden_heartbeat_fields(calls[0]["payload"]) == []
    assert payload["entitlement"]["plan"] == "business"
    assert payload["entitlement"]["limits"]["max_hub_clients"] == 250
    assert entitlement_summary(home=home)["limits"]["max_hub_clients"] == 250


def test_plan_downgrade_blocks_new_clients_without_deleting_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home" / ".unlimited-skills"
    root = tmp_path / "library"
    allowlist = tmp_path / "allowlist.json"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    write_skill(root)
    write_allowlist(allowlist)
    raw_token = create_hub_token("quota", home=home)["raw_token"]
    client = TestClient(create_app(root=root, allowlist_path=allowlist))
    headers = {"Authorization": f"Bearer {raw_token}"}

    for idx in range(2):
        response = client.post("/v1/clients/register", headers=headers, json={"schema_version": 1, "capabilities": {"schema_version": 1, "client_id": f"uls_client_{idx}", "agent": "codex"}})
        assert response.status_code == 200

    apply_entitlements(
        {
            "schema_version": 1,
            "source": "refreshed",
            "plan": "downgraded",
            "features_enabled": ["local_skill_hub"],
            "limits": {"max_hub_clients": 1},
            "policy": {"hub_distribution_mode": "allowlist_only", "signed_manifests_required": True, "hosted_query_forwarding_allowed": False},
            "last_heartbeat_at": "2026-06-09T00:00:00Z",
            "offline_grace_until": "2026-06-16T00:00:00Z",
        },
        home=home,
    )

    overflow = client.post("/v1/clients/register", headers=headers, json={"schema_version": 1, "capabilities": {"schema_version": 1, "client_id": "uls_client_new", "agent": "codex"}})
    listed = client.get("/v1/clients", headers=headers)

    assert overflow.status_code == 403
    assert overflow.json()["error"]["code"] == "client_limit_reached"
    assert len(listed.json()["clients"]) == 2


def test_offline_grace_status_is_reported(tmp_path: Path) -> None:
    home = tmp_path / ".unlimited-skills"
    save_entitlements(
        {
            "schema_version": 1,
            "source": "cached",
            "plan": "registered-community",
            "features_enabled": ["local_skill_hub"],
            "limits": {"max_hub_clients": 100},
            "policy": {"hub_distribution_mode": "allowlist_only", "signed_manifests_required": True, "hosted_query_forwarding_allowed": False},
            "last_heartbeat_at": "2026-06-09T00:00:00Z",
            "offline_grace_until": "2999-01-01T00:00:00Z",
        },
        home=home,
    )
    assert entitlement_summary(home=home)["offline_grace_status"] == "active"

    save_entitlements(
        {
            "schema_version": 1,
            "source": "cached",
            "plan": "registered-community",
            "features_enabled": ["local_skill_hub"],
            "limits": {"max_hub_clients": 100},
            "policy": {"hub_distribution_mode": "allowlist_only", "signed_manifests_required": True, "hosted_query_forwarding_allowed": False},
            "last_heartbeat_at": "2026-06-01T00:00:00Z",
            "offline_grace_until": "2000-01-01T00:00:00Z",
        },
        home=home,
    )
    assert entitlement_summary(home=home)["offline_grace_status"] == "expired"


def test_unregistered_heartbeat_fails_but_local_search_remains_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    home = tmp_path / "home" / ".unlimited-skills"
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    monkeypatch.setenv("UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC", "1")
    write_skill(root)

    assert main(["hub", "heartbeat", "--dry-run"]) == 2
    assert "Registration is required" in capsys.readouterr().err

    assert main(["--root", str(root), "search", "pure skill", "--mode", "lexical", "--no-native-sync", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["name"] == "pure-skill"


def test_heartbeat_payload_builder_rejects_forbidden_fields() -> None:
    assert has_forbidden_heartbeat_fields({"query": "secret customer query"}) == ["query"]
    payload = build_heartbeat_payload(registered_state(), active_client_count=3)
    assert has_forbidden_heartbeat_fields(payload) == []
