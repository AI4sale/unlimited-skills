from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from unlimited_skills.cli import build_parser
from unlimited_skills.fleet.claude_code import private_pack_release_id
from unlimited_skills.fleet.hermes import (
    HERMES_ADAPTER_VERSION,
    HermesFleetAdapter,
    HermesFleetAdapterError,
    parse_hermes_session_start_payload,
    record_hermes_session_start,
)
from unlimited_skills.registration import RegistrationState


def registered_state() -> RegistrationState:
    return RegistrationState(
        install_id="uls_inst_hermes",
        server_url="https://registry.example.test",
        license_token="secret-token",
        device_private_key="secret-device-key",
    )


def archive(skill_name: str, body: str = "# Skill\n") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(
            f"pack/skills/{skill_name}/SKILL.md",
            (
                f"---\nname: {skill_name}\n"
                "description: test\n---\n"
                f"{body}"
            ),
        )
    return output.getvalue()


class PackClient:
    def __init__(self, packs: dict[str, tuple[str, bytes]]) -> None:
        self.packs = packs

    def release_id(self, pack_id: str) -> str:
        version, value = self.packs[pack_id]
        digest = "sha256:" + hashlib.sha256(value).hexdigest()
        return private_pack_release_id(pack_id, version, digest)

    def signed_manifest(
        self,
        pack_id: str,
        *,
        request_context: dict | None = None,
    ) -> dict:
        del request_context
        version, value = self.packs[pack_id]
        digest = hashlib.sha256(value).hexdigest()
        return {
            "manifest": {
                "schema_version": 1,
                "manifest_type": "private-team-pack-manifest",
                "pack_id": pack_id,
                "team_id": "team_hermes",
                "namespace": "team/hermes",
                "name": pack_id,
                "version": version,
                "visibility": "private-team",
                "sha256": digest,
                "bytes": len(value),
                "revoked": False,
                "contains_private_skill_bodies": False,
                "signature": {
                    "algorithm": "ed25519",
                    "key_id": "pack-key-v1",
                    "signature": "test",
                },
            },
            "verification": {
                "verified": True,
                "key_id": "pack-key-v1",
            },
        }

    def download_archive(
        self,
        pack_id: str,
        *,
        release_id: str,
        expected_sha256: str,
        request_context: dict | None = None,
    ) -> bytes:
        del request_context
        value = self.packs[pack_id][1]
        assert release_id == self.release_id(pack_id)
        assert expected_sha256 == (
            "sha256:" + hashlib.sha256(value).hexdigest()
        )
        return value


def item(client: PackClient, pack_id: str, nonce: str) -> dict:
    version, value = client.packs[pack_id]
    release_id = client.release_id(pack_id)
    return {
        "attempt_id": f"attempt_{pack_id}",
        "pack_id": pack_id,
        "release_id": release_id,
        "version": version,
        "archive_sha256": (
            "sha256:" + hashlib.sha256(value).hexdigest()
        ),
        "activation_nonce": nonce,
        "manifest_ref": (
            f"registry:private-pack/{pack_id}/{release_id}"
        ),
        "required": True,
        "action": "activate",
    }


def adapter(
    tmp_path: Path,
    client: PackClient,
) -> HermesFleetAdapter:
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    return HermesFleetAdapter(
        registration=registered_state(),
        managed_root=tmp_path / "managed-hermes",
        hermes_home=hermes_home,
        pack_client=client,
        python_executable=Path("/verified/python"),
    )


def session_payload() -> dict:
    return {
        "hook_event_name": "on_session_start",
        "session_id": "private-hermes-session-id",
        "cwd": "/private/workspace",
        "extra": {
            "platform": "cli",
            "model": "private-model-name",
        },
    }


def test_hermes_bundle_requires_real_session_start_attestation(
    tmp_path: Path,
) -> None:
    client = PackClient(
        {
            "pack_a": ("1.0.0", archive("hermes-a", "# A\n")),
            "pack_b": ("2.0.0", archive("hermes-b", "# B\n")),
        }
    )
    instance = adapter(tmp_path, client)
    items = [
        item(client, "pack_a", "nonce_a"),
        item(client, "pack_b", "nonce_b"),
    ]
    installed = {
        value["pack_id"]: instance.install_revision(value)
        for value in items
    }
    nonces = {"pack_a": "nonce_a", "pack_b": "nonce_b"}

    instance.activate_inventory(
        items,
        installed,
        activation_nonces=nonces,
    )

    assert (
        instance.skills_root / "hermes-a" / "SKILL.md"
    ).is_file()
    assert (
        instance.skills_root / "hermes-b" / "SKILL.md"
    ).is_file()
    assert instance.discover().runtime_generation.startswith(
        "hermes:pending:"
    )
    with pytest.raises(
        HermesFleetAdapterError,
        match="runtime_attestation_pending",
    ):
        instance.attest_inventory(
            items,
            activation_nonces=nonces,
        )

    result = record_hermes_session_start(
        instance.managed_root,
        instance.hermes_home,
        session_payload(),
        process_id=7101,
        parent_process_id=7100,
        observed_at="2026-07-28T18:30:00Z",
    )
    attestation = instance.attest_inventory(
        items,
        activation_nonces=nonces,
    )

    assert result["recorded"] is True
    assert attestation.runtime_generation.startswith(
        "hermes-session:"
    )
    assert attestation.activation_nonces == nonces
    marker = (
        instance.state_root / "runtime-current.json"
    ).read_text(encoding="utf-8")
    assert "private-hermes-session-id" not in marker
    assert "/private/workspace" not in marker
    assert "private-model-name" not in marker
    assert str(instance.hermes_home) not in marker


def test_hermes_provisions_enabled_plugin_without_replacing_user_skills(
    tmp_path: Path,
) -> None:
    client = PackClient({"pack": ("1.0.0", archive("team-skill"))})
    hermes_home = tmp_path / "hermes-home"
    manual = hermes_home / "skills" / "manual"
    manual.mkdir(parents=True)
    (manual / "SKILL.md").write_text(
        "---\nname: personal-skill\ndescription: personal\n---\n",
        encoding="utf-8",
    )
    instance = HermesFleetAdapter(
        registration=registered_state(),
        managed_root=tmp_path / "managed-hermes",
        hermes_home=hermes_home,
        pack_client=client,
        python_executable=Path("/verified/python"),
    )

    plugin_root = (
        hermes_home / "plugins" / "unlimited-skills-fleet"
    )
    assert (plugin_root / "plugin.yaml").is_file()
    plugin = (plugin_root / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "on_session_start" in plugin
    assert "hermes-runtime-start" in plugin
    assert repr(str(instance.managed_root)) in plugin
    assert "secret-token" not in plugin
    assert manual.is_dir()

    desired = item(client, "pack", "nonce")
    installed = instance.install_revision(desired)
    instance.activate_revision(
        desired,
        installed,
        activation_nonce="nonce",
    )

    assert manual.is_dir()
    assert (
        instance.skills_root / "team-skill" / "SKILL.md"
    ).is_file()


def test_hermes_rejects_wrong_home_event_and_skill_collision(
    tmp_path: Path,
) -> None:
    client = PackClient({"pack": ("1.0.0", archive("shared-name"))})
    instance = adapter(tmp_path, client)
    desired = item(client, "pack", "nonce")
    installed = instance.install_revision(desired)
    manual = instance.hermes_home / "skills" / "manual"
    manual.mkdir(parents=True)
    (manual / "SKILL.md").write_text(
        "---\nname: shared-name\ndescription: manual\n---\n",
        encoding="utf-8",
    )

    with pytest.raises(
        HermesFleetAdapterError,
        match="unmanaged_skill_collision",
    ):
        instance.activate_revision(
            desired,
            installed,
            activation_nonce="nonce",
        )

    payload = session_payload()
    payload["hook_event_name"] = "pre_llm_call"
    with pytest.raises(
        HermesFleetAdapterError,
        match="runtime_hook_event_invalid",
    ):
        record_hermes_session_start(
            instance.managed_root,
            instance.hermes_home,
            payload,
        )
    with pytest.raises(
        HermesFleetAdapterError,
        match="runtime_hermes_home_mismatch",
    ):
        record_hermes_session_start(
            instance.managed_root,
            tmp_path / "wrong-home",
            session_payload(),
        )


def test_hermes_payload_parser_is_bounded() -> None:
    payload = session_payload()
    assert parse_hermes_session_start_payload(
        json.dumps(payload).encode("utf-8")
    ) == payload
    with pytest.raises(
        HermesFleetAdapterError,
        match="runtime_hook_input_invalid",
    ):
        parse_hermes_session_start_payload(b"[]")
    with pytest.raises(
        HermesFleetAdapterError,
        match="runtime_hook_input_invalid",
    ):
        parse_hermes_session_start_payload(
            b"x" * (64 * 1024 + 1)
        )


def test_cli_exposes_hermes_fleet_controls() -> None:
    parser = build_parser()
    hook = parser.parse_args(
        [
            "fleet",
            "hermes-runtime-start",
            "--managed-root",
            "managed",
            "--hermes-home",
            "home",
            "--hook-output",
        ]
    )
    assert hook.func.__name__ == "cmd_fleet_hermes_runtime_start"
    assert hook.hook_output is True
    provision = parser.parse_args(
        [
            "fleet",
            "hermes-provision",
            "--managed-root",
            "managed",
            "--hermes-home",
            "home",
        ]
    )
    assert provision.func.__name__ == "cmd_fleet_hermes_provision"
    launch = parser.parse_args(
        [
            "fleet",
            "hermes-launch",
            "--managed-root",
            "managed",
            "--hermes-home",
            "home",
            "--dry-run",
            "--json",
            "--",
            "-z",
            "hello",
        ]
    )
    assert launch.func.__name__ == "cmd_fleet_hermes_launch"
    run_once = parser.parse_args(
        [
            "fleet",
            "run-once",
            "--managed-root",
            "managed",
            "--public-keys",
            "keys.json",
            "--runtime-vendor",
            "hermes",
            "--hermes-home",
            "home",
        ]
    )
    assert run_once.runtime_vendor == "hermes"
    assert run_once.hermes_home == "home"


def test_hermes_adapter_version_is_receipt_safe_identifier() -> None:
    assert HERMES_ADAPTER_VERSION == "hermes-fleet/1.0.0"
