from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
try:
    from fastapi.testclient import TestClient
except RuntimeError as exc:
    pytest.skip(str(exc), allow_module_level=True)

from unlimited_skills.cli import main
from unlimited_skills.hub_server import create_app
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity


def write_skill(root: Path, collection: str, name: str, description: str) -> None:
    skill = root / collection / "skills" / name / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\nUse this skill for {description}.\n", encoding="utf-8")


def write_allowlist(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_audit": {"verdict": "YES_WITH_ALLOWLIST", "total_skills_scanned": 315},
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
                        "requires_local_install_plan": False,
                        "risk_level": "none",
                    }
                ],
                "local_install_plan_candidates": [
                    {
                        "skill_id": "tool-skill",
                        "name": "tool-skill",
                        "collection": "test-pack",
                        "sha256": "b" * 64,
                        "hub_behavior": "distribute_body_with_local_install_plan",
                    }
                ],
                "excluded": {
                    "blocked": [{"skill_id": "blocked-skill", "name": "blocked-skill", "collection": "test-pack"}],
                    "local_only": [],
                    "needs_human_review": [],
                    "retrieval_only": [],
                },
                "counts": {"allowlist_total": 1, "requires_local_install_plan": 1, "blocked": 1},
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(
            install_id="uls_inst_hub_mvp",
            server_url="https://updates.example.test",
            plan="registered-community",
            license_token="tok_secret_hub_mvp",
        )
    )


def make_client(tmp_path: Path) -> TestClient:
    root = tmp_path / "library"
    write_skill(root, "test-pack", "pure-skill", "security review")
    write_skill(root, "test-pack", "tool-skill", "playwright diagnostics")
    write_skill(root, "test-pack", "blocked-skill", "blocked content")
    allowlist = tmp_path / "hub-allowlist.v1.json"
    write_allowlist(allowlist)
    return TestClient(create_app(root=root, allowlist_path=allowlist))


def test_hub_mvp_health_and_status_are_allowlist_only(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    health = client.get("/health").json()
    status = client.get("/v1/hub/status").json()

    assert health["ok"] is True
    assert health["distribution_mode"] == "allowlist_only"
    assert health["hosted_query_forwarding"] is False
    assert health["hub_executes_skills"] is False
    assert status["catalog_audit_verdict"] == "YES_WITH_ALLOWLIST"
    assert status["full_catalog_distribution_allowed"] is False
    assert status["active_client_limit"] == 100
    assert status["skills_total"] == 2
    assert status["allowlisted_skills"] == 1


def test_search_returns_only_allowlisted_and_local_install_candidates(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    payload = client.post("/v1/skills/search", json={"schema_version": 1, "query": "security playwright blocked", "limit": 10}).json()
    names = {item["name"] for item in payload["results"]}

    assert "pure-skill" in names
    assert "tool-skill" in names
    assert "blocked-skill" not in names


def test_resolve_returns_body_for_pure_text_but_metadata_only_for_local_install(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    payload = client.post("/v1/skills/resolve", json={"schema_version": 1, "query": "security playwright", "context_budget": {"max_skills": 2, "max_chars": 12000}}).json()
    by_name = {item["name"]: item for item in payload["selected"]}

    assert "# pure-skill" in by_name["pure-skill"]["body"]
    assert by_name["pure-skill"]["requires_local_install"] is False
    assert by_name["tool-skill"]["body"] == ""
    assert by_name["tool-skill"]["requires_local_install"] is True
    assert "client_capability_checks" in by_name["tool-skill"]["missing_capabilities"]


def test_get_skill_rejects_blocked_or_unallowlisted_skill(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    allowed = client.get("/v1/skills/pure-skill")
    blocked = client.get("/v1/skills/blocked-skill")

    assert allowed.status_code == 200
    assert "# pure-skill" in allowed.json()["skill"]["body"]
    assert blocked.status_code == 404


def test_client_registration_enforces_100_active_client_limit(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    for idx in range(100):
        response = client.post("/v1/clients/register", json={"schema_version": 1, "token": f"tok_{idx}", "capabilities": {"schema_version": 1, "client_id": f"uls_client_{idx}", "agent": "codex", "os": "linux", "arch": "x86_64", "available_tools": [], "installed_packages": {"python": [], "npm": []}, "env_vars_present": []}})
        assert response.status_code == 200
    overflow = client.post("/v1/clients/register", json={"schema_version": 1, "token": "tok_overflow"})

    assert overflow.status_code == 403
    assert overflow.json()["detail"]["code"] == "client_limit_reached"


def test_hub_serve_registered_requires_allowlist_file(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    save_registration(registered_state(), home=home / ".unlimited-skills")
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    assert main(["--root", str(tmp_path / "library"), "hub", "serve", "--allowlist", str(tmp_path / "missing.json")]) == 2

    assert "Local Skill Hub allowlist is required" in capsys.readouterr().err


def test_hub_serve_registered_runs_uvicorn_factory_with_allowlist(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    allowlist = tmp_path / "hub-allowlist.v1.json"
    write_allowlist(allowlist)
    save_registration(registered_state(), home=home / ".unlimited-skills")
    calls: list[dict[str, object]] = []

    def fake_run(app: str, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    assert main(["--root", str(root), "hub", "serve", "--allowlist", str(allowlist), "--host", "127.0.0.1", "--port", "8766"]) == 0

    assert calls[0]["app"] == "unlimited_skills.hub_server:create_app"
    assert calls[0]["factory"] is True
    assert calls[0]["host"] == "127.0.0.1"
