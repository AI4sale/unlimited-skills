from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from unlimited_skills.cli import main
from unlimited_skills.hub import create_hub_token
from unlimited_skills.hub_allowlist import allowlist_sha256
from unlimited_skills.registration import RegistrationState, base64_urlsafe_encode, save_registration, with_install_identity
from unlimited_skills.signatures import (
    key_record_allows,
    sign_manifest_for_tests,
    trusted_manifest_key_records,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "hub" / "allowlist-fixture.v1.json"


def valid_allowlist() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def write_allowlist(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def registered_state() -> RegistrationState:
    return with_install_identity(
        RegistrationState(
            install_id="uls_inst_hub_allowlist",
            server_url="https://updates.example.test",
            plan="registered-community",
            license_token="tok_secret_hub_allowlist",
        )
    )


def signed_manifest_env(payload: dict) -> tuple[dict, dict[str, str]]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return sign_manifest_for_tests(payload, private_key, key_id="hub-test-key"), {
        "UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS": f"hub-test-key:{base64_urlsafe_encode(public_key)}"
    }


def test_hub_init_creates_layout_and_config_dirs(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "init", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "initialized"
    assert (uls_home / "hub" / "hub.json").is_file()
    assert (uls_home / "hub" / "clients.json").is_file()
    assert (uls_home / "hub" / "logs").is_dir()
    assert payload["allowlist"]["present"] is False


def test_hub_init_allowlist_fixture_validates_and_caches(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "init", "--allowlist", str(FIXTURE), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    cached = uls_home / "hub" / "allowlist.v1.json"
    meta = uls_home / "hub" / "allowlist.meta.json"
    assert cached.is_file()
    assert meta.is_file()
    assert payload["allowlist"]["distribution_mode"] == "allowlist_only"
    assert payload["allowlist"]["full_catalog_distribution_allowed"] is False
    assert payload["allowlist"]["requires_registration"] is True
    assert payload["allowlist"]["free_active_client_instance_limit"] == 100

    assert main(["hub", "status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["allowlist"]["present"] is True
    assert status["allowlist"]["full_catalog_distribution_allowed"] is False


def test_invalid_allowlist_is_rejected(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    invalid = valid_allowlist()
    invalid["schema_version"] = 2
    path = write_allowlist(tmp_path / "invalid.json", invalid)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "init", "--allowlist", str(path)]) == 2

    assert "schema_version must be 1" in capsys.readouterr().err


def test_allowlist_with_full_catalog_distribution_is_rejected(tmp_path: Path, monkeypatch, capsys) -> None:
    data = valid_allowlist()
    data["policy"]["full_catalog_distribution_allowed"] = True
    path = write_allowlist(tmp_path / "full-catalog.json", data)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["hub", "init", "--allowlist", str(path)]) == 2

    assert "full_catalog_distribution_allowed must be false" in capsys.readouterr().err


def test_allowlist_with_blocked_skill_is_rejected(tmp_path: Path, monkeypatch, capsys) -> None:
    data = valid_allowlist()
    data["allowlist"].append(
        {
            "skill_id": "blocked-fixture",
            "name": "blocked-fixture",
            "collection": "fixture-pack",
            "sha256": "c" * 64,
            "primary_category": "HUB_READY_PURE_TEXT",
            "hub_behavior": "distribute_body",
        }
    )
    path = write_allowlist(tmp_path / "blocked.json", data)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["hub", "init", "--allowlist", str(path)]) == 2

    assert "includes excluded skill fixture-pack/blocked-fixture" in capsys.readouterr().err


def test_allowlist_with_embedded_skill_body_is_rejected(tmp_path: Path, monkeypatch, capsys) -> None:
    data = valid_allowlist()
    data["allowlist"][0]["body"] = "---\nname: private\n---\n\nPRIVATE_BODY_SENTINEL"
    path = write_allowlist(tmp_path / "body.json", data)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["hub", "init", "--allowlist", str(path)]) == 2

    assert "must not embed a skill body" in capsys.readouterr().err


def test_hub_serve_uses_cached_allowlist_when_explicit_path_absent(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    root = tmp_path / "library"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    assert main(["hub", "init", "--allowlist", str(FIXTURE), "--json"]) == 0
    capsys.readouterr()
    create_hub_token("server", home=uls_home)
    calls: list[dict[str, object]] = []

    def fake_run(app: str, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    assert main(["--root", str(root), "hub", "serve", "--host", "127.0.0.1"]) == 0

    assert calls[0]["app"] == "unlimited_skills.hub_server:create_app"
    assert calls[0]["factory"] is True
    assert calls[0]["host"] == "127.0.0.1"
    assert str(uls_home / "hub" / "allowlist.v1.json") == __import__("os").environ["UNLIMITED_SKILLS_HUB_ALLOWLIST"]


def test_hub_serve_fails_when_no_cached_allowlist_and_no_explicit_path(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "serve", "--host", "127.0.0.1"]) == 2

    assert "No hub allowlist is configured" in capsys.readouterr().err


def test_unregistered_hub_sync_fails_friendly_and_local_commands_still_work(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    root = tmp_path / "library"
    skill = root / "local" / "skills" / "local-only" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("---\nname: local-only\ndescription: Local only\n---\n\n# Local only\n", encoding="utf-8")
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))

    assert main(["hub", "sync"]) == 2
    assert "Registration is required for Local Skill Hub allowlist sync. The MIT local core still works offline." in capsys.readouterr().err

    assert main(["--root", str(root), "search", "local only", "--mode", "lexical", "--no-native-sync"]) == 0
    assert "local-only [local]" in capsys.readouterr().out


def test_hub_sync_dry_run_writes_nothing(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    data = valid_allowlist()
    signed_response, env = signed_manifest_env(
        {
            "schema_version": 1,
            "distribution_mode": "allowlist_only",
            "catalog_audit_verdict": "YES_WITH_ALLOWLIST",
            "full_catalog_distribution_allowed": False,
            "requires_registration": True,
            "free_active_client_instance_limit": 100,
            "allowlist": data,
            "allowlist_sha256": allowlist_sha256(data),
            "notes": "fixture dry run",
        }
    )
    monkeypatch.setenv("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", env["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"])

    def fake_post_json(url, payload, **kwargs):
        assert url == "https://updates.example.test/v1/hub/allowlist"
        assert payload["current_allowlist_sha256"] == ""
        return signed_response

    monkeypatch.setattr("unlimited_skills.hub.post_json", fake_post_json)

    assert main(["hub", "sync", "--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["full_catalog_distribution_allowed"] is False
    assert payload["requires_registration"] is True
    assert not (uls_home / "hub" / "allowlist.v1.json").exists()


def test_hub_sync_caches_registered_allowlist(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    data = valid_allowlist()
    signed_response, env = signed_manifest_env(
        {
            "schema_version": 1,
            "distribution_mode": "allowlist_only",
            "catalog_audit_verdict": "YES_WITH_ALLOWLIST",
            "full_catalog_distribution_allowed": False,
            "requires_registration": True,
            "free_active_client_instance_limit": 100,
            "allowlist": data,
            "allowlist_sha256": allowlist_sha256(data),
            "notes": "fixture sync",
        }
    )
    monkeypatch.setenv("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", env["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"])

    def fake_post_json(_url, _payload, **_kwargs):
        return signed_response

    monkeypatch.setattr("unlimited_skills.hub.post_json", fake_post_json)

    assert main(["hub", "sync", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is False
    assert payload["distribution_mode"] == "allowlist_only"
    assert payload["full_catalog_distribution_allowed"] is False
    assert (uls_home / "hub" / "allowlist.v1.json").is_file()
    assert json.loads((uls_home / "hub" / "allowlist.v1.json").read_text(encoding="utf-8"))["policy"]["requires_registration"] is True


def test_hub_sync_rejects_unsigned_remote_allowlist_manifest(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    data = valid_allowlist()

    def fake_post_json(_url, _payload, **_kwargs):
        return {
            "schema_version": 1,
            "distribution_mode": "allowlist_only",
            "catalog_audit_verdict": "YES_WITH_ALLOWLIST",
            "full_catalog_distribution_allowed": False,
            "requires_registration": True,
            "free_active_client_instance_limit": 100,
            "allowlist": data,
            "allowlist_sha256": allowlist_sha256(data),
        }

    monkeypatch.setattr("unlimited_skills.hub.post_json", fake_post_json)

    assert main(["hub", "sync"]) == 2
    assert "must include manifest_signature" in capsys.readouterr().err


def test_hub_sync_verifies_signed_allowlist_manifest(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    save_registration(registered_state(), home=uls_home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    data = valid_allowlist()
    signed_response, env = signed_manifest_env(
        {
            "schema_version": 1,
            "distribution_mode": "allowlist_only",
            "catalog_audit_verdict": "YES_WITH_ALLOWLIST",
            "full_catalog_distribution_allowed": False,
            "requires_registration": True,
            "free_active_client_instance_limit": 100,
            "allowlist": data,
            "allowlist_sha256": allowlist_sha256(data),
            "notes": "signed fixture sync",
        }
    )
    monkeypatch.setenv("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", env["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"])

    def fake_post_json(_url, _payload, **_kwargs):
        return signed_response

    monkeypatch.setattr("unlimited_skills.hub.post_json", fake_post_json)

    assert main(["hub", "sync", "--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["signature_verification"]["verified"] is True
    assert payload["signature_verification"]["key_id"] == "hub-test-key"


def test_trust_cli_lists_key_ids_and_verifies_manifest_file(tmp_path: Path, monkeypatch, capsys) -> None:
    signed_response, env = signed_manifest_env({"schema_version": 1, "updates": []})
    manifest_path = tmp_path / "signed-manifest.json"
    manifest_path.write_text(json.dumps(signed_response), encoding="utf-8")
    monkeypatch.setenv(
        "UNLIMITED_SKILLS_HOME",
        str(tmp_path / ".unlimited-skills"),
    )
    monkeypatch.setenv("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", env["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"])

    assert main(["trust", "status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert "hub-test-key" in status["trusted_manifest_key_ids"]
    assert status["private_keys_present"] is False

    assert main(["trust", "keys", "--json"]) == 0
    keys = json.loads(capsys.readouterr().out)
    key_ids = {item["key_id"] for item in keys["keys"]}
    assert "hub-test-key" in key_ids
    assert env["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"].split(":", 1)[1] not in json.dumps(keys)

    assert main(["trust", "verify", str(manifest_path), "--json"]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["signature_verification"]["verified"] is True
    assert verified["signature_verification"]["key_id"] == "hub-test-key"


def test_trust_cli_import_scope_origin_and_revoke(tmp_path: Path, monkeypatch, capsys) -> None:
    uls_home = tmp_path / ".unlimited-skills"
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(uls_home))
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    trust_manifest = {
        "schema_version": 1,
        "keys": [
            {
                "key_id": "local-registry-key",
                "algorithm": "ed25519",
                "public_key": base64_urlsafe_encode(public_key),
                "status": "active",
                "scopes": ["catalog-updates"],
                "registry_origins": ["https://updates.example.test"],
            }
        ],
    }
    trust_path = tmp_path / "manifest-public-keys.v1.json"
    trust_path.write_text(json.dumps(trust_manifest), encoding="utf-8")
    signed = sign_manifest_for_tests({"schema_version": 1, "updates": []}, private_key, key_id="local-registry-key")
    signed_path = tmp_path / "catalog-updates.v1.json"
    signed_path.write_text(json.dumps(signed), encoding="utf-8")

    assert main(["trust", "import", str(trust_path), "--json"]) == 0
    imported = json.loads(capsys.readouterr().out)
    assert imported["imported_count"] == 1

    assert main(["trust", "verify", str(signed_path), "--scope", "catalog-updates", "--registry-url", "https://updates.example.test/v1/catalog", "--json"]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["signature_verification"]["key_id"] == "local-registry-key"

    assert main(["trust", "verify", str(signed_path), "--scope", "team-sync-manifest", "--registry-url", "https://updates.example.test", "--json"]) == 2
    assert "not allowed for this scope or registry" in capsys.readouterr().err

    assert main(["trust", "revoke", "local-registry-key", "--reason", "test", "--json"]) == 0
    revoked = json.loads(capsys.readouterr().out)
    assert revoked["status"] == "revoked"

    assert main(["trust", "verify", str(signed_path), "--scope", "catalog-updates", "--registry-url", "https://updates.example.test", "--json"]) == 2
    assert "revoked" in capsys.readouterr().err


def test_manifest_trust_pin_enforces_fingerprint_role_expiry_and_collision(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(
        "UNLIMITED_SKILLS_HOME",
        str(tmp_path / ".unlimited-skills"),
    )
    monkeypatch.delenv(
        "UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS",
        raising=False,
    )
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    public_key_b64 = base64_urlsafe_encode(public_key)
    fingerprint = "sha256:" + hashlib.sha256(public_key).hexdigest()
    trust_manifest = {
        "schema_version": 1,
        "keys": [
            {
                "key_id": "private-pack-key-fixture",
                "algorithm": "ed25519",
                "public_key": public_key_b64,
                "sha256_fingerprint": fingerprint,
                "role": "private-team-pack-manifest",
                "status": "active",
                "scopes": ["private-team-pack"],
                "registry_origins": [
                    "https://unlimited.example.test"
                ],
                "not_after": "2099-01-01T00:00:00Z",
            }
        ],
    }
    trust_path = tmp_path / "private-pack-trust.json"
    trust_path.write_text(
        json.dumps(trust_manifest),
        encoding="utf-8",
    )
    signed = sign_manifest_for_tests(
        {
            "schema_version": 1,
            "manifest_type": "private-team-pack-manifest",
        },
        private_key,
        key_id="private-pack-key-fixture",
    )
    signed_path = tmp_path / "private-pack-manifest.json"
    signed_path.write_text(json.dumps(signed), encoding="utf-8")

    assert main(["trust", "import", str(trust_path), "--json"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "trust",
                "verify",
                str(signed_path),
                "--scope",
                "private-team-pack",
                "--registry-url",
                "https://unlimited.example.test/v1/fleet",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()

    expired = json.loads(json.dumps(trust_manifest))
    expired["keys"][0]["key_id"] = "expired-private-pack-key"
    expired["keys"][0]["not_after"] = "2000-01-01T00:00:00Z"
    expired_path = tmp_path / "expired-trust.json"
    expired_path.write_text(json.dumps(expired), encoding="utf-8")
    expired_signed = sign_manifest_for_tests(
        {"schema_version": 1},
        private_key,
        key_id="expired-private-pack-key",
    )
    expired_signed_path = tmp_path / "expired-signed.json"
    expired_signed_path.write_text(
        json.dumps(expired_signed),
        encoding="utf-8",
    )
    assert main(["trust", "import", str(expired_path), "--json"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "trust",
                "verify",
                str(expired_signed_path),
                "--scope",
                "private-team-pack",
                "--registry-url",
                "https://unlimited.example.test",
                "--json",
            ]
        )
        == 2
    )
    assert "not allowed" in capsys.readouterr().err

    wrong_role = json.loads(json.dumps(trust_manifest))
    wrong_role["keys"][0]["key_id"] = "wrong-role-key"
    wrong_role["keys"][0]["role"] = "fleet-desired-state-signing"
    wrong_role_path = tmp_path / "wrong-role-trust.json"
    wrong_role_path.write_text(
        json.dumps(wrong_role),
        encoding="utf-8",
    )
    wrong_role_signed = sign_manifest_for_tests(
        {"schema_version": 1},
        private_key,
        key_id="wrong-role-key",
    )
    wrong_role_signed_path = tmp_path / "wrong-role-signed.json"
    wrong_role_signed_path.write_text(
        json.dumps(wrong_role_signed),
        encoding="utf-8",
    )
    assert (
        main(["trust", "import", str(wrong_role_path), "--json"])
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "trust",
                "verify",
                str(wrong_role_signed_path),
                "--scope",
                "private-team-pack",
                "--registry-url",
                "https://unlimited.example.test",
                "--json",
            ]
        )
        == 2
    )
    assert "not allowed" in capsys.readouterr().err

    collision_key = Ed25519PrivateKey.generate().public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    collision = json.loads(json.dumps(trust_manifest))
    collision["keys"][0]["public_key"] = base64_urlsafe_encode(
        collision_key
    )
    collision["keys"][0]["sha256_fingerprint"] = (
        "sha256:" + hashlib.sha256(collision_key).hexdigest()
    )
    collision_path = tmp_path / "collision-trust.json"
    collision_path.write_text(
        json.dumps(collision),
        encoding="utf-8",
    )
    assert (
        main(["trust", "import", str(collision_path), "--json"])
        == 2
    )
    assert "different public material" in capsys.readouterr().err

    bad_fingerprint = json.loads(json.dumps(trust_manifest))
    bad_fingerprint["keys"][0]["key_id"] = "bad-fingerprint-key"
    bad_fingerprint["keys"][0]["sha256_fingerprint"] = (
        "sha256:" + ("0" * 64)
    )
    bad_fingerprint_path = tmp_path / "bad-fingerprint-trust.json"
    bad_fingerprint_path.write_text(
        json.dumps(bad_fingerprint),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "trust",
                "import",
                str(bad_fingerprint_path),
                "--json",
            ]
        )
        == 2
    )
    assert "fingerprint is invalid" in capsys.readouterr().err


def test_private_pack_pin_merges_with_same_bundled_public_key(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(
        "UNLIMITED_SKILLS_HOME",
        str(tmp_path / ".unlimited-skills"),
    )
    trust_path = tmp_path / "private-pack-pin.json"
    trust_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "keys": [
                    {
                        "key_id": "registry-prod-2026-06-25",
                        "algorithm": "ed25519",
                        "public_key": (
                            "qoKlymz97CLckL4zIdjI2BjYxYPvvaLY"
                            "BKcV153BNE4"
                        ),
                        "sha256_fingerprint": (
                            "sha256:"
                            "3a515e23afa65d365857650796c459c1"
                            "9500bac707ea1afd5d09ecc5f2a57d3e"
                        ),
                        "role": "private-team-pack-manifest",
                        "status": "active",
                        "scopes": ["private-team-pack"],
                        "registry_origins": [
                            "https://unlimited.ai4.sale"
                        ],
                        "not_after": "2027-06-25T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(["trust", "import", str(trust_path), "--json"]) == 0
    capsys.readouterr()
    record = next(
        item
        for item in trusted_manifest_key_records(
            include_public=True
        )
        if item["key_id"] == "registry-prod-2026-06-25"
    )

    assert "catalog-updates" in record["scopes"]
    assert "private-team-pack" in record["scopes"]
    assert record["role"] == "private-team-pack-manifest"
    assert record["not_after"] == "2027-06-25T00:00:00Z"
    assert key_record_allows(
        record,
        scope="private-team-pack",
        registry_url="https://unlimited.ai4.sale/v1/fleet",
    )
    assert key_record_allows(
        record,
        scope="catalog-updates",
        registry_url="https://unlimited.ai4.sale/v1/catalog",
    )
