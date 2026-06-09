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
from unlimited_skills.hub import create_hub_token, load_hub_config, revoke_hub_token
from unlimited_skills.hub_server import create_app
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity


def write_skill(root: Path, collection: str, name: str, description: str) -> None:
    skill = root / "registry" / collection / "skills" / name / "SKILL.md"
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
                        "local_requirements": {"python_packages": ["playwright"], "binaries": ["docker"]},
                        "hub_behavior": "distribute_body_with_local_install_plan",
                    },
                    {
                        "skill_id": "linux-only",
                        "name": "linux-only",
                        "collection": "test-pack",
                        "sha256": "c" * 64,
                        "skill_kind": "platform",
                        "local_requirements": {"platforms": ["linux"]},
                        "hub_behavior": "metadata_only",
                    },
                    {
                        "skill_id": "secret-skill",
                        "name": "secret-skill",
                        "collection": "test-pack",
                        "sha256": "d" * 64,
                        "skill_kind": "secret_dependent",
                        "local_requirements": {"env_vars": ["N8N_API_KEY"]},
                        "secrets_policy": {"requires_secrets": True, "secret_names": ["N8N_API_KEY"]},
                        "hub_behavior": "metadata_only",
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


def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, with_token: bool = True) -> TestClient:
    root = tmp_path / "library"
    home = tmp_path / "home" / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    write_skill(root, "test-pack", "pure-skill", "security review")
    write_skill(root, "test-pack", "tool-skill", "playwright diagnostics")
    write_skill(root, "test-pack", "blocked-skill", "blocked content")
    allowlist = tmp_path / "hub-allowlist.v1.json"
    write_allowlist(allowlist)
    client = TestClient(create_app(root=root, allowlist_path=allowlist))
    if with_token:
        token = create_hub_token("pytest", home=home)["raw_token"]
        client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_hub_mvp_health_and_status_are_allowlist_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    health = client.get("/health").json()
    status = client.get("/v1/hub/status").json()

    assert health["ok"] is True
    assert health["distribution_mode"] == "allowlist_only"
    assert health["hosted_query_forwarding"] is False
    assert health["hub_executes_skills"] is False
    assert status["catalog_audit_verdict"] == "YES_WITH_ALLOWLIST"
    assert status["full_catalog_distribution_allowed"] is False
    assert status["active_client_limit"] == 100
    assert status["skills_total"] == 4
    assert status["allowlisted_skills"] == 1
    assert status["local_install_plan_skills"] == 3


def test_search_returns_only_allowlisted_and_local_install_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    payload = client.post("/v1/skills/search", json={"schema_version": 1, "query": "security playwright blocked", "limit": 10}).json()
    names = {item["name"] for item in payload["results"]}

    assert "pure-skill" in names
    assert "tool-skill" in names
    assert "blocked-skill" not in names

    hyphen_payload = client.post("/v1/skills/search", json={"schema_version": 1, "query": "pure skill", "limit": 10}).json()
    assert "pure-skill" in {item["name"] for item in hyphen_payload["results"]}


def test_resolve_returns_body_for_pure_text_but_metadata_only_for_local_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    payload = client.post("/v1/skills/resolve", json={"schema_version": 1, "query": "security playwright", "context_budget": {"max_skills": 2, "max_chars": 12000}}).json()
    by_name = {item["name"]: item for item in payload["selected"]}

    assert "# pure-skill" in by_name["pure-skill"]["body"]
    assert by_name["pure-skill"]["requires_local_install"] is False
    assert by_name["tool-skill"]["body"] == ""
    assert by_name["tool-skill"]["requires_local_install"] is True
    assert "python_package:playwright" in by_name["tool-skill"]["missing_capabilities"]
    assert "binary:docker" in by_name["tool-skill"]["missing_capabilities"]


def test_resolve_compares_client_capabilities_without_env_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    common_capabilities = {
        "schema_version": 1,
        "agent": "codex",
        "os": "windows",
        "arch": "x86_64",
        "available_tools": ["git"],
        "installed_packages": {"python": [], "npm": []},
        "env_vars_present": ["N8N_API_KEY"],
    }
    tool_payload = client.post(
        "/v1/skills/resolve",
        json={
            "schema_version": 1,
            "query": "playwright docker",
            "context_budget": {"max_skills": 1, "max_chars": 12000},
            "client_capabilities": common_capabilities,
        },
    ).json()
    linux_payload = client.post(
        "/v1/skills/resolve",
        json={
            "schema_version": 1,
            "query": "linux-only",
            "context_budget": {"max_skills": 1, "max_chars": 12000},
            "client_capabilities": common_capabilities,
        },
    ).json()
    secret_payload = client.post(
        "/v1/skills/resolve",
        json={
            "schema_version": 1,
            "query": "secret-skill",
            "context_budget": {"max_skills": 1, "max_chars": 12000},
            "client_capabilities": common_capabilities,
        },
    ).json()
    by_name = {item["name"]: item for item in tool_payload["selected"] + linux_payload["selected"] + secret_payload["selected"]}

    assert "python_package:playwright" in by_name["tool-skill"]["missing_capabilities"]
    assert "binary:docker" in by_name["tool-skill"]["missing_capabilities"]
    assert "platform:linux" in by_name["linux-only"]["missing_capabilities"]
    assert "env_var:N8N_API_KEY" in by_name["secret-skill"]["matched_capabilities"]
    assert "secret-value" not in json.dumps([tool_payload, linux_payload, secret_payload])


def test_hub_manifest_endpoint_is_token_protected_and_returns_install_plan_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home" / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    client = make_client(tmp_path, monkeypatch, with_token=False)
    raw_token = create_hub_token("manifest", home=home)["raw_token"]

    missing = client.get("/v1/skills/tool-skill/manifest")
    allowed = client.get("/v1/skills/tool-skill/manifest", headers={"Authorization": f"Bearer {raw_token}"})

    assert missing.status_code == 401
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["manifest"]["skill_kind"] == "tool"
    assert payload["manifest"]["execution"]["hub_executes"] is False
    assert payload["install_plan"]["install_plan_available"] is True
    assert "body" not in payload["install_plan"]


def test_get_skill_rejects_blocked_or_unallowlisted_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    allowed = client.get("/v1/skills/pure-skill")
    blocked = client.get("/v1/skills/blocked-skill")

    assert allowed.status_code == 200
    assert "# pure-skill" in allowed.json()["skill"]["body"]
    assert blocked.status_code == 404


def test_client_registration_enforces_100_active_client_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    for idx in range(100):
        response = client.post("/v1/clients/register", json={"schema_version": 1, "token": f"tok_{idx}", "capabilities": {"schema_version": 1, "client_id": f"uls_client_{idx}", "agent": "codex", "os": "linux", "arch": "x86_64", "available_tools": [], "installed_packages": {"python": [], "npm": []}, "env_vars_present": []}})
        assert response.status_code == 200
    overflow = client.post("/v1/clients/register", json={"schema_version": 1, "token": "tok_overflow"})

    assert overflow.status_code == 403
    assert overflow.json()["error"]["code"] == "client_limit_reached"


def test_client_registry_persists_across_hub_restart_and_deactivation_frees_quota(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home" / ".unlimited-skills"
    root = tmp_path / "library"
    allowlist = tmp_path / "hub-allowlist.v1.json"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    write_skill(root, "test-pack", "pure-skill", "security review")
    write_allowlist(allowlist)
    raw_token = create_hub_token("persistent", home=home)["raw_token"]

    client = TestClient(create_app(root=root, allowlist_path=allowlist))
    headers = {"Authorization": f"Bearer {raw_token}"}
    registered = client.post(
        "/v1/clients/register",
        headers=headers,
        json={"schema_version": 1, "display_name": "Codex Desktop", "capabilities": {"schema_version": 1, "client_id": "uls_client_persist", "agent": "codex", "os": "windows", "arch": "x86_64"}},
    )
    assert registered.status_code == 200
    clients_path = home / "hub" / "clients.json"
    clients_payload = json.loads(clients_path.read_text(encoding="utf-8"))
    assert clients_payload["clients"][0]["client_id"] == "uls_client_persist"
    assert "raw_token" not in json.dumps(clients_payload)

    restarted = TestClient(create_app(root=root, allowlist_path=allowlist))
    listed = restarted.get("/v1/clients", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["clients"][0]["client_id"] == "uls_client_persist"

    deactivated = restarted.post("/v1/clients/uls_client_persist/deactivate", headers=headers)
    assert deactivated.status_code == 200
    assert deactivated.json()["active_client_count"] == 0


def test_hub_metrics_and_audit_log_are_token_protected_and_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home" / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    client = make_client(tmp_path, monkeypatch, with_token=False)
    raw_token = create_hub_token("metrics", home=home)["raw_token"]
    headers = {"Authorization": f"Bearer {raw_token}"}

    denied = client.get("/v1/hub/metrics")
    assert denied.status_code == 401

    search = client.post("/v1/skills/search", headers=headers, json={"schema_version": 1, "query": "secret customer query", "limit": 5})
    metrics = client.get("/v1/hub/metrics", headers=headers)

    assert search.status_code == 200
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload["requests_total"] >= 2
    assert payload["clients"]["limit"] == 100
    audit_text = (home / "hub" / "logs" / "audit.jsonl").read_text(encoding="utf-8")
    assert "skills_search" in audit_text
    assert "secret customer query" not in audit_text
    assert raw_token not in audit_text


def test_protected_endpoints_reject_missing_wrong_and_revoked_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home" / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    client = make_client(tmp_path, monkeypatch, with_token=False)
    raw_token = create_hub_token("auth-test", home=home)["raw_token"]
    token_id = load_hub_config(home)["tokens"][0]["token_id"]

    missing = client.get("/v1/hub/status")
    wrong = client.get("/v1/hub/status", headers={"Authorization": "Bearer wrong-token"})
    valid = client.get("/v1/hub/status", headers={"Authorization": f"Bearer {raw_token}"})
    revoke_hub_token(token_id, home=home)
    revoked = client.get("/v1/hub/status", headers={"Authorization": f"Bearer {raw_token}"})

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "hub_token_required"
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "invalid_hub_token"
    assert valid.status_code == 200
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "hub_token_revoked"


def test_protected_endpoints_accept_x_uls_hub_token_header(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home" / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home))
    client = make_client(tmp_path, monkeypatch, with_token=False)
    raw_token = create_hub_token("compat", home=home)["raw_token"]

    response = client.get("/v1/hub/status", headers={"X-ULS-Hub-Token": raw_token})

    assert response.status_code == 200


def test_health_remains_unauthenticated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch, with_token=False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_local_hub_search_and_resolve_do_not_call_hosted_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    def fail_network(*_args, **_kwargs):
        raise AssertionError("Local Skill Hub search/resolve must not call hosted services.")

    monkeypatch.setattr("urllib.request.urlopen", fail_network)

    search = client.post("/v1/skills/search", json={"schema_version": 1, "query": "security", "limit": 5})
    resolve = client.post("/v1/skills/resolve", json={"schema_version": 1, "query": "security"})

    assert search.status_code == 200
    assert resolve.status_code == 200


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
    create_hub_token("server", home=home / ".unlimited-skills")
    calls: list[dict[str, object]] = []

    def fake_run(app: str, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    assert main(["--root", str(root), "hub", "serve", "--allowlist", str(allowlist), "--host", "127.0.0.1", "--port", "8766"]) == 0

    assert calls[0]["app"] == "unlimited_skills.hub_server:create_app"
    assert calls[0]["factory"] is True
    assert calls[0]["host"] == "127.0.0.1"


def test_hub_serve_refuses_lan_without_allow_lan_or_active_token(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    allowlist = tmp_path / "hub-allowlist.v1.json"
    write_allowlist(allowlist)
    save_registration(registered_state(), home=home / ".unlimited-skills")
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    assert main(["--root", str(root), "hub", "serve", "--allowlist", str(allowlist), "--host", "0.0.0.0"]) == 2
    assert "Refusing to bind Local Skill Hub" in capsys.readouterr().err

    assert main(["--root", str(root), "hub", "serve", "--allowlist", str(allowlist), "--host", "0.0.0.0", "--allow-lan"]) == 2
    assert "Refusing to bind Local Skill Hub" in capsys.readouterr().err


def test_hub_serve_allows_lan_with_allow_lan_and_active_token(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    allowlist = tmp_path / "hub-allowlist.v1.json"
    write_allowlist(allowlist)
    save_registration(registered_state(), home=home / ".unlimited-skills")
    create_hub_token("lan", home=home / ".unlimited-skills")
    calls: list[dict[str, object]] = []

    def fake_run(app: str, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    assert main(["--root", str(root), "hub", "serve", "--allowlist", str(allowlist), "--host", "0.0.0.0", "--allow-lan"]) == 0

    assert calls[0]["host"] == "0.0.0.0"
