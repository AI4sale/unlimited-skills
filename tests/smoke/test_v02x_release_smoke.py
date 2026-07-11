from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from unlimited_skills import cli
from unlimited_skills.adapters import validate_pack_ref
from unlimited_skills.cli import main
from unlimited_skills.doctor import build_doctor_report
from unlimited_skills.registration import redact_sensitive_text
from unlimited_skills.self_update import SelfUpdateError, validate_git_ref


PRODUCTION_HOST_MARKERS = ("unlimited.ai4.sale", "api.github.com", "github.com")


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    home = tmp_path / "home"
    root = tmp_path / "library"
    uls_home = home / ".unlimited-skills"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    monkeypatch.setenv("UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC", "1")
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))
    with patch.object(Path, "home", return_value=home):
        yield {"home": home, "root": root, "uls_home": uls_home}


@pytest.fixture(autouse=True)
def block_production_network(monkeypatch: pytest.MonkeyPatch):
    def blocked_urlopen(request, *args, **kwargs):
        url = getattr(request, "full_url", str(request))
        if any(marker in url for marker in PRODUCTION_HOST_MARKERS):
            raise AssertionError(f"Smoke tests must not call production network: {url}")
        raise urllib.error.URLError("network disabled by v0.2.x smoke suite")

    monkeypatch.setattr("urllib.request.urlopen", blocked_urlopen)


def run_cli(args: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


def write_skill(root: Path, rel: str, name: str, description: str = "Smoke skill") -> Path:
    path = root / rel / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\nUse this skill for {description}.\n",
        encoding="utf-8",
    )
    return path


def write_smoke_library(root: Path) -> None:
    write_skill(root, "registry/ecc/skills/security-review", "security-review", "auth and secrets review")
    write_skill(root, "registry/superpowers/skills/security-review-copy", "security-review", "duplicate registry skill")
    write_skill(root, "registry/superpowers/skills/execution-plan", "execution-plan", "execute implementation plans")
    write_skill(root, "local/codex/skills/local-debug", "local-debug", "local codex diagnostics")
    write_skill(root, "local/hermes/skills/hermes-debug", "hermes-debug", "local hermes diagnostics")


def test_community_core_cli_commands_are_registration_free(isolated_env: dict[str, Path]) -> None:
    root = isolated_env["root"]
    write_smoke_library(root)

    assert run_cli(["--root", str(root), "reindex", "--json", "--no-native-sync"])[0] == 0
    code, out, _err = run_cli(["--root", str(root), "list", "--json", "--no-native-sync"])
    assert code == 0
    listed = json.loads(out)
    assert listed["total"] >= 4
    assert "registry" not in json.dumps(listed).lower() or listed["collections"]

    code, out, _err = run_cli(["--root", str(root), "search", "auth secrets", "--mode", "lexical", "--json", "--no-native-sync"])
    assert code == 0
    assert any(item["name"] == "security-review" for item in json.loads(out))

    assert run_cli(["--root", str(root), "where", "security-review", "--no-native-sync"])[0] == 0
    code, out, _err = run_cli(["--root", str(root), "view", "security-review", "--no-native-sync"])
    assert code == 0
    assert "# security-review" in out

    calls: list[dict[str, object]] = []

    def fake_run(app: str, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
        assert run_cli(["--root", str(root), "serve", "--host", "127.0.0.1", "--port", "8765"])[0] == 0
    finally:
        monkeypatch.undo()
    assert calls[0]["app"] == "unlimited_skills.server:app"


def test_registration_gated_commands_fail_friendly_and_local_core_still_works(isolated_env: dict[str, Path]) -> None:
    root = isolated_env["root"]
    write_smoke_library(root)
    gated = [
        ["updates", "check"],
        ["updates", "apply"],
        ["catalog", "list"],
        ["community", "list"],
        ["team", "sync"],
        ["hub", "serve"],
    ]
    for command in gated:
        code, _out, err = run_cli(["--root", str(root), *command])
        assert code == 2, command
        lowered = err.lower()
        assert "registration" in lowered or "registered" in lowered, command
        assert "mit" in lowered or "local core" in lowered or "unlimited-skills serve" in lowered, command

    assert run_cli(["--root", str(root), "search", "diagnostics", "--mode", "lexical", "--no-native-sync"])[0] == 0


def test_registry_local_layout_dedupe_and_doctor_hermes_risk(isolated_env: dict[str, Path]) -> None:
    root = isolated_env["root"]
    home = isolated_env["home"]
    write_smoke_library(root)

    code, out, _err = run_cli(["--root", str(root), "list", "--json", "--no-native-sync"])
    assert code == 0
    payload = json.loads(out)
    assert payload["collections"]["ecc"] == 1
    assert payload["collections"]["superpowers"] == 1
    assert payload["collections"]["local"] == 2
    assert [item["name"] for item in payload["skills"]].count("security-review") == 1

    hermes_skills = home / ".hermes" / "skills"
    write_skill(hermes_skills, "alpha", "alpha")
    write_skill(hermes_skills, "beta", "beta")
    write_skill(hermes_skills, "unlimited-skills", "unlimited-skills")
    with patch.object(Path, "home", return_value=home):
        report = build_doctor_report(root, agent="hermes")
    assert report["agents"]["hermes"]["context_reduction_status"] == "risk"

    for item in hermes_skills.iterdir():
        if item.name != "unlimited-skills":
            for child in item.rglob("*"):
                if child.is_file():
                    child.unlink()
            item.rmdir()
    with patch.object(Path, "home", return_value=home):
        report = build_doctor_report(root, agent="hermes")
    assert report["agents"]["hermes"]["context_reduction_status"] == "ok"


def test_vector_sidecar_fast_path_uses_sidecar_without_chroma(isolated_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    root = isolated_env["root"]
    root.mkdir(parents=True)
    skill_path = write_skill(root, "registry/ecc/skills/security-review", "security-review", "Review auth and secrets.")
    generation = cli.library_generation_hash(root)
    sidecar = {
        "schema_version": 2,
        "collection": cli.CHROMA_COLLECTION,
        "model": "smoke-model",
        "count": 1,
        "embedding_dimensions": 2,
        "library_generation_hash": generation,
        "complete": True,
        "records": [
            {
                "name": "security-review",
                "description": "Review auth and secrets.",
                "collection": "ecc",
                "path": str(skill_path),
                "embedding": [1.0, 0.0],
            }
        ],
    }
    (root / cli.VECTOR_SIDECAR_NAME).write_text(json.dumps(sidecar), encoding="utf-8")
    (root / cli.VECTOR_META_NAME).write_text(
        json.dumps({key: sidecar[key] for key in ("schema_version", "collection", "model", "count", "embedding_dimensions", "library_generation_hash", "complete")}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "embed_texts", lambda texts, model: [[0.99, 0.01]])
    monkeypatch.setattr(cli, "chroma_client", lambda _root: (_ for _ in ()).throw(AssertionError("Chroma should not load")))

    hits = cli.vector_search(root, "auth secrets", 1, "smoke-model")
    assert [hit.name for hit in hits] == ["security-review"]


def test_local_skill_hub_allowlist_runtime_or_pending(isolated_env: dict[str, Path]) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from unlimited_skills.hub import create_hub_token
    from unlimited_skills.hub_server import create_app

    root = isolated_env["root"]
    home = isolated_env["uls_home"]
    write_skill(root, "registry/test-pack/skills/pure-skill", "pure-skill", "security review")
    write_skill(root, "registry/test-pack/skills/tool-skill", "tool-skill", "playwright diagnostics")
    write_skill(root, "registry/test-pack/skills/blocked-skill", "blocked-skill", "blocked")
    allowlist = isolated_env["home"] / "hub-allowlist.v1.json"
    allowlist.write_text(
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
                        "primary_category": "HUB_READY_PURE_TEXT",
                        "hub_behavior": "distribute_body",
                    }
                ],
                "local_install_plan_candidates": [
                    {"skill_id": "tool-skill", "name": "tool-skill", "collection": "test-pack", "sha256": "b" * 64, "hub_behavior": "distribute_body_with_local_install_plan"}
                ],
                "excluded": {"blocked": [{"skill_id": "blocked-skill", "name": "blocked-skill", "collection": "test-pack"}], "local_only": [], "needs_human_review": []},
                "counts": {"allowlist_total": 1, "requires_local_install_plan": 1, "blocked": 1},
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(root=root, allowlist_path=allowlist))
    raw_token = create_hub_token("allowlist-smoke", home=home)["raw_token"]
    client.headers.update({"Authorization": f"Bearer {raw_token}"})

    status = client.get("/v1/hub/status").json()
    assert status["distribution_mode"] == "allowlist_only"
    assert status["full_catalog_distribution_allowed"] is False
    assert status["hosted_query_forwarding"] is False

    resolved = client.post("/v1/skills/resolve", json={"schema_version": 1, "query": "security playwright", "context_budget": {"max_skills": 2, "max_chars": 12000}}).json()
    by_name = {item["name"]: item for item in resolved["selected"]}
    assert "# pure-skill" in by_name["pure-skill"]["body"]
    assert by_name["tool-skill"]["body"] == ""
    assert by_name["tool-skill"]["requires_local_install"] is True
    assert client.get("/v1/skills/blocked-skill").status_code == 404


def test_hub_token_enforcement_or_pending(isolated_env: dict[str, Path]) -> None:
    import unlimited_skills.hub as hub

    if not all(hasattr(hub, name) for name in ("create_hub_token", "load_hub_config", "revoke_hub_token", "verify_hub_token")):
        pytest.skip("Hub token enforcement is missing on this branch; required for v0.2.1-alpha RC.")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from unlimited_skills.hub_server import create_app

    root = isolated_env["root"]
    home = isolated_env["uls_home"]
    write_skill(root, "registry/test-pack/skills/pure-skill", "pure-skill", "security review")
    allowlist = isolated_env["home"] / "hub-token-allowlist.json"
    allowlist.write_text(
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
                "allowlist": [{"skill_id": "pure-skill", "name": "pure-skill", "collection": "test-pack", "sha256": "a" * 64, "primary_category": "HUB_READY_PURE_TEXT", "hub_behavior": "distribute_body"}],
                "counts": {"allowlist_total": 1},
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(root=root, allowlist_path=allowlist))
    token_result = hub.create_hub_token("smoke", home=home)
    raw_token = token_result["raw_token"]
    token_id = hub.load_hub_config(home)["tokens"][0]["token_id"]

    missing = client.get("/v1/hub/status")
    wrong = client.get("/v1/hub/status", headers={"Authorization": "Bearer wrong-token"})
    valid = client.get("/v1/hub/status", headers={"Authorization": f"Bearer {raw_token}"})
    hub.revoke_hub_token(token_id, home=home)
    revoked = client.get("/v1/hub/status", headers={"Authorization": f"Bearer {raw_token}"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert valid.status_code == 200
    assert revoked.status_code == 401
    assert raw_token not in json.dumps(hub.list_hub_tokens(home)) if hasattr(hub, "list_hub_tokens") else True


def test_remote_client_runtime_or_pending(isolated_env: dict[str, Path]) -> None:
    try:
        import unlimited_skills.remote_client  # noqa: F401
    except ImportError:
        pytest.skip("Remote hub client runtime is missing on this branch; required for v0.2.1-alpha RC.")

    class FakeResponse:
        def __init__(self, payload: dict):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    token = "uls_hub_smoke_secret"

    def fake_urlopen(request, timeout=10):
        assert request.get_header("Authorization") == f"Bearer {token}"
        if request.full_url.endswith("/v1/hub/status"):
            return FakeResponse({"schema_version": 1, "hub_id": "uls_hub_smoke", "distribution_mode": "allowlist_only"})
        if request.full_url.endswith("/v1/skills/search"):
            return FakeResponse({"schema_version": 1, "results": [{"name": "remote-smoke", "collection": "registry", "confidence": 0.9, "skill_kind": "pure_text", "hub_behavior": "distribute_body", "requires_local_install": False}]})
        if request.full_url.endswith("/v1/skills/resolve"):
            return FakeResponse({"schema_version": 1, "selected": [{"name": "remote-smoke", "collection": "registry", "confidence": 0.9, "skill_kind": "pure_text", "hub_behavior": "distribute_body", "requires_local_install": False, "missing_capabilities": [], "warnings": [], "body": "REMOTE_SMOKE_BODY"}]})
        if request.full_url.endswith("/v1/skills/remote-smoke"):
            return FakeResponse({"schema_version": 1, "skill": {"name": "remote-smoke", "collection": "registry", "body": "REMOTE_SMOKE_VIEW", "warnings": []}})
        raise AssertionError(f"unexpected remote request: {request.full_url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        assert run_cli(["remote", "configure", "--url", "http://127.0.0.1:8766", "--token", token, "--fallback", "local_allowed"])[0] == 0
        assert token not in run_cli(["remote", "status"])[1]
        assert "remote-smoke" in run_cli(["remote", "search", "smoke"])[1]
        assert "REMOTE_SMOKE_BODY" in run_cli(["remote", "resolve", "smoke"])[1]
        assert "REMOTE_SMOKE_VIEW" in run_cli(["remote", "view", "remote-smoke"])[1]

    root = isolated_env["root"]
    write_skill(root, "local/skills/local-fallback", "local-fallback", "fallback diagnostics")
    assert run_cli(["remote", "configure", "--url", "http://127.0.0.1:9", "--token", token, "--fallback", "local_allowed"])[0] == 0
    code, out, _err = run_cli(["--root", str(root), "remote", "search", "fallback diagnostics"])
    assert code == 0
    assert "Remote hub unavailable; using local fallback." in out
    assert "local-fallback" in out

    assert run_cli(["remote", "configure", "--url", "http://127.0.0.1:9", "--token", token, "--fallback", "hub_required"])[0] == 0
    code, _out, err = run_cli(["--root", str(root), "remote", "search", "fallback diagnostics"])
    assert code == 2
    assert "Remote hub is required by policy but unavailable." in err
    assert token not in err


def test_hub_allowlist_bootstrap_or_pending(isolated_env: dict[str, Path]) -> None:
    try:
        import unlimited_skills.hub_allowlist  # noqa: F401
    except ImportError:
        pytest.skip("Hub allowlist bootstrap is missing on this branch; required for v0.2.1-alpha RC.")

    from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity

    home = isolated_env["uls_home"]
    allowlist = isolated_env["home"] / "allowlist.v1.json"
    allowlist.write_text(
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
                "allowlist": [{"skill_id": "fixture-skill", "name": "fixture-skill", "collection": "fixture-pack", "sha256": "a" * 64, "primary_category": "HUB_READY_PURE_TEXT", "hub_behavior": "distribute_body"}],
                "excluded": {"blocked": [], "local_only": [], "needs_human_review": []},
                "counts": {"allowlist_total": 1},
            }
        ),
        encoding="utf-8",
    )
    code, out, _err = run_cli(["hub", "init", "--allowlist", str(allowlist), "--json"])
    assert code == 0
    assert json.loads(out)["allowlist"]["full_catalog_distribution_allowed"] is False

    save_registration(
        with_install_identity(RegistrationState(install_id="uls_inst_smoke", server_url="https://updates.example.test", plan="registered-community", license_token="tok_smoke")),
        home=home,
    )
    calls: list[dict[str, object]] = []

    def fake_run(app: str, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs, "allowlist": os.environ.get("UNLIMITED_SKILLS_HUB_ALLOWLIST", "")})

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))
        assert run_cli(["hub", "serve", "--host", "127.0.0.1"])[0] == 0
    finally:
        monkeypatch.undo()
    assert calls[0]["allowlist"].endswith("allowlist.v1.json")


def test_redaction_for_tokens_headers_and_device_keys() -> None:
    leaked = (
        "Authorization: Bearer secret-token-123 "
        "X-ULS-Hub-Token: hub-secret-123 "
        "license_token=license-secret-123 "
        "device_private_key=device-secret-123 "
        "team_token=team-secret-123 member_token=member-secret-123"
    )
    redacted = redact_sensitive_text(leaked)
    assert "[redacted]" in redacted
    for secret in ("secret-token-123", "hub-secret-123", "license-secret-123", "device-secret-123", "team-secret-123", "member-secret-123"):
        assert secret not in redacted


def test_docs_security_claims_are_consistent() -> None:
    root = Path(__file__).resolve().parents[2]
    docs = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in [root / "SECURITY.md", root / "README.md", *list((root / "docs").glob("*.md"))]).lower()
    assert "v0.3.7-alpha" in (root / "SECURITY.md").read_text(encoding="utf-8", errors="replace")
    assert "sha256" in docs
    assert "hosted remote manifests must include valid signed manifest envelopes" in docs
    assert "serve` is the free local daemon and remains unregistered" in docs
    assert "`hub serve` is a separate registration-required product command" in docs
    assert "allowlist-only" in docs
    assert "full catalog distribution is disabled" in docs
    forbidden = ["signed archives are verified", "full catalog distribution is enabled"]
    for phrase in forbidden:
        assert phrase not in docs


def test_self_update_and_pack_ref_validation() -> None:
    for ref in ("v0.2.0-alpha", "release/0.2.x", "feature+test"):
        assert validate_git_ref(ref) == ref
        assert validate_pack_ref(ref) == ref
    for bad in ("--upload-pack=sh", "../bad", "bad.lock", "with spaces", "semi;colon"):
        with pytest.raises((SelfUpdateError, RuntimeError)):
            validate_git_ref(bad)
        with pytest.raises(RuntimeError):
            validate_pack_ref(bad)


def test_no_production_hosted_calls_are_required_by_default(isolated_env: dict[str, Path]) -> None:
    root = isolated_env["root"]
    write_smoke_library(root)
    assert run_cli(["--root", str(root), "reindex", "--no-native-sync"])[0] == 0
    assert run_cli(["--root", str(root), "search", "auth", "--mode", "lexical", "--no-native-sync"])[0] == 0
