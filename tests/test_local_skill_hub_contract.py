from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from unlimited_skills.cli import main
from unlimited_skills.hub import load_hub_config
from unlimited_skills.registration import RegistrationState, save_registration, with_install_identity


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(
            install_id="uls_inst_hub",
            server_url="https://updates.example.test",
            plan="registered-community",
            license_token="tok_secret_hub",
        )
    )


def test_existing_serve_does_not_require_registration(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    calls: list[dict[str, object]] = []

    def fake_run(app: str, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    assert main(["--root", str(root), "serve", "--host", "127.0.0.1", "--port", "8765"]) == 0

    assert calls[0]["app"] == "unlimited_skills.server:app"
    assert calls[0]["host"] == "127.0.0.1"


def test_hub_serve_requires_registration_and_fails_friendly(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    assert main(["hub", "serve"]) == 2

    error = capsys.readouterr().err
    assert "Registration is required for Local Skill Hub" in error
    assert "unlimited-skills serve" in error
    assert "unlimited-skills register" in error


def test_hub_status_json_is_valid_and_redacts_tokens(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    save_registration(registered_state(), home=home / ".unlimited-skills")
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))

    assert main(["hub", "status", "--json"]) == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["registered"] is True
    assert payload["active_client_limit"] == 100
    assert payload["full_catalog_distribution_allowed"] is False
    assert payload["hosted_query_forwarding"] is False
    assert payload["catalog_audit_verdict"] == "YES_WITH_ALLOWLIST"
    assert payload["registration"]["token_present"] is True
    assert "tok_secret_hub" not in output
    assert "device_private_key" not in output


def test_remote_configure_writes_config_and_redacts_token(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    uls_home = home / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["remote", "configure", "--url", "http://127.0.0.1:8766", "--token", "remote_secret_token"]) == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    config = json.loads((uls_home / "remote.json").read_text(encoding="utf-8"))
    assert payload["url"] == "http://127.0.0.1:8766"
    assert payload["token_present"] is True
    assert config["token_present"] is True
    assert "remote_secret_token" not in output
    assert config["token_storage"] == "file"
    assert config["token"] == "remote_secret_token"


def test_hub_token_create_stores_hash_and_prints_raw_token_once(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    uls_home = home / ".unlimited-skills"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "token", "create", "--label", "laptop", "--json"]) == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    raw_token = payload["token"]
    config_text = (uls_home / "hub.json").read_text(encoding="utf-8")
    config = json.loads(config_text)

    assert raw_token.startswith("uls_hub_")
    assert raw_token not in config_text
    assert config["tokens"][0]["token_hash"].startswith("sha256:")
    assert config["tokens"][0]["label"] == "laptop"

    assert main(["hub", "token", "list", "--json"]) == 0
    list_output = capsys.readouterr().out
    assert raw_token not in list_output
    listed = json.loads(list_output)
    assert listed["tokens"][0]["token_id"] == payload["token_id"]
    assert "token_hash" not in json.dumps(listed)


def test_hub_token_revoke_does_not_print_raw_token(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    uls_home = home / ".unlimited-skills"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "token", "create", "--label", "old", "--json"]) == 0
    created = json.loads(capsys.readouterr().out)
    raw_token = created["token"]

    assert main(["hub", "token", "revoke", created["token_id"], "--json"]) == 0

    output = capsys.readouterr().out
    config = load_hub_config(uls_home)
    assert raw_token not in output
    assert config["tokens"][0]["revoked"] is True


def test_runtime_error_output_redacts_hub_and_registration_secrets(monkeypatch, capsys) -> None:
    def leak(_args) -> int:
        raise RuntimeError(
            "Authorization: Bearer auth_secret X-ULS-Hub-Token: hub_secret "
            "license_token=license_secret device_private_key=device_secret team_token=team_secret member_token=member_secret"
        )

    monkeypatch.setattr("unlimited_skills.cli.cmd_hub_status", leak)
    assert main(["hub", "status"]) == 2

    output = capsys.readouterr().err
    assert "[redacted]" in output
    for secret in ("auth_secret", "hub_secret", "license_secret", "device_secret", "team_secret", "member_secret"):
        assert secret not in output


def test_hub_schema_examples_are_valid_json() -> None:
    paths = list((ROOT / "schemas").glob("hub-*.schema.json"))
    paths.extend((ROOT / "examples" / "hub").glob("*.json"))
    paths.append(ROOT / "schemas" / "client-capabilities.schema.json")
    paths.append(ROOT / "schemas" / "skill-runtime-manifest.schema.json")
    for path in paths:
        json.loads(path.read_text(encoding="utf-8"))


def test_public_core_boundary_lists_serve_free_and_hub_registered() -> None:
    text = read("docs/public-core-boundary.md")
    assert "`serve`" in text
    assert "`hub serve`" in text
    assert "`remote search`" in text
    assert "serve` is the free local daemon and remains unregistered" in text
    assert "`hub serve` is a separate registration-required product command" in text


def test_docs_are_allowlist_only_and_do_not_claim_full_catalog_distribution() -> None:
    docs = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in (ROOT / "docs").glob("*.md"))
    assert "YES_WITH_ALLOWLIST" in docs
    assert "allowlist-only" in docs.lower()
    forbidden = [
        "full catalog distribution is enabled",
        "full catalog distribution allowed",
        "distribute full catalog",
    ]
    lowered = docs.lower()
    for phrase in forbidden:
        assert phrase not in lowered


def test_examples_do_not_include_private_skill_bodies() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in (ROOT / "examples" / "hub").glob("*.json"))
    assert "PRIVATE_BODY_SENTINEL" not in combined
    assert "PRIVATE_REGISTRY_PATH_SENTINEL" not in combined
    assert "LOCAL_USER_PATH_SENTINEL" not in combined


def test_docs_and_examples_keep_registered_free_hub_limit_at_100() -> None:
    combined = "\n".join(
        [
            read("docs/local-skill-hub.md"),
            read("docs/local-skill-hub-editions.md"),
            read("examples/hub/status.example.json"),
            read("examples/hub/error-client-limit-reached.example.json"),
        ]
    )
    assert "100 active client" in combined
    assert '"active_client_limit": 100' in combined


def test_docs_do_not_claim_hub_executes_skills() -> None:
    docs = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in (ROOT / "docs").glob("*.md")).lower()
    assert "hub does not execute skills" in docs
    forbidden = ["hub executes skills", "hub runs skill scripts", "hub runs downloaded scripts"]
    for phrase in forbidden:
        assert phrase not in docs
