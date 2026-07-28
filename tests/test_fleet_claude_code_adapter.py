from __future__ import annotations

import base64
import io
import json
import os
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from unlimited_skills.fleet.claude_code import (
    CLAUDE_CODE_ADAPTER_VERSION,
    ClaudeCodeFleetAdapter,
    ClaudeCodeFleetAdapterError,
    _tree_digest,
    load_fleet_public_keys,
    managed_claude_config_dir,
    managed_inventory_digest,
    parse_session_start_payload,
    private_pack_release_id,
    record_claude_session_start,
)
from unlimited_skills.cli import build_parser
from unlimited_skills.commands import fleet as fleet_commands
from unlimited_skills.registration import RegistrationState


def registered_state(
    installation_id: str = "uls_inst_enterprise",
) -> RegistrationState:
    return RegistrationState(
        install_id=installation_id,
        server_url="https://registry.example.test",
        license_token="secret-token",
        device_private_key="secret-device-key",
    )


def pack_archive(
    skill_body: str = "# Enterprise Skill\n",
    *,
    unsafe_name: str = "",
    skill_name: str = "enterprise-skill",
    declared_name: str = "",
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        if unsafe_name:
            bundle.writestr(unsafe_name, skill_body)
        else:
            bundle.writestr(
                f"enterprise-pack/skills/{skill_name}/SKILL.md",
                (
                    "---\n"
                    f"name: {declared_name}\n"
                    "description: test\n"
                    "---\n"
                    f"{skill_body}"
                    if declared_name
                    else skill_body
                ),
            )
            bundle.writestr(
                f"enterprise-pack/skills/{skill_name}/reference.md",
                "source-backed reference\n",
            )
    return output.getvalue()


class StubPackClient:
    def __init__(
        self,
        *,
        pack_id: str = "pack_enterprise",
        version: str = "1.0.0",
        archive: bytes | None = None,
    ) -> None:
        self.pack_id = pack_id
        self.version = version
        self.archive = archive if archive is not None else pack_archive()
        self.downloads: list[dict[str, str]] = []

    @property
    def archive_digest(self) -> str:
        import hashlib

        return hashlib.sha256(self.archive).hexdigest()

    @property
    def release_id(self) -> str:
        return private_pack_release_id(
            self.pack_id,
            self.version,
            "sha256:" + self.archive_digest,
        )

    def signed_manifest(self, pack_id: str) -> dict:
        assert pack_id == self.pack_id
        return {
            "manifest": {
                "schema_version": 1,
                "manifest_type": "private-team-pack-manifest",
                "pack_id": self.pack_id,
                "team_id": "team_enterprise",
                "namespace": "team/enterprise",
                "name": "Enterprise Pack",
                "version": self.version,
                "visibility": "private-team",
                "sha256": self.archive_digest,
                "bytes": len(self.archive),
                "revoked": False,
                "contains_private_skill_bodies": False,
                "signature": {
                    "algorithm": "ed25519",
                    "key_id": "pack-key-v1",
                    "signature": "redacted-test-signature",
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
        release_id: str = "",
        expected_sha256: str = "",
    ) -> bytes:
        self.downloads.append(
            {
                "pack_id": pack_id,
                "release_id": release_id,
                "expected_sha256": expected_sha256,
            }
        )
        return self.archive


class MultiPackClient:
    def __init__(self, *clients: StubPackClient) -> None:
        self.clients = {client.pack_id: client for client in clients}

    def signed_manifest(self, pack_id: str) -> dict:
        return self.clients[pack_id].signed_manifest(pack_id)

    def download_archive(
        self,
        pack_id: str,
        *,
        release_id: str = "",
        expected_sha256: str = "",
    ) -> bytes:
        return self.clients[pack_id].download_archive(
            pack_id,
            release_id=release_id,
            expected_sha256=expected_sha256,
        )


def desired_item(
    client: StubPackClient,
    *,
    action: str = "activate",
    nonce: str = "nonce_enterprise_a",
) -> dict:
    return {
        "attempt_id": "attempt_enterprise",
        "pack_id": client.pack_id,
        "release_id": client.release_id,
        "version": client.version,
        "archive_sha256": "sha256:" + client.archive_digest,
        "activation_nonce": nonce,
        "manifest_ref": (
            f"registry:private-pack/{client.pack_id}/"
            f"{client.release_id}"
        ),
        "required": True,
        "action": action,
    }


def inventory_row(item: dict) -> dict:
    return {
        "action": str(item["action"]),
        "archive_sha256": str(item["archive_sha256"]),
        "pack_id": str(item["pack_id"]),
        "release_id": str(item["release_id"]),
        "required": bool(item["required"]),
    }


def session_payload(
    session_id: str,
    *,
    source: str = "startup",
) -> dict:
    return {
        "session_id": session_id,
        "transcript_path": "/private/transcript.jsonl",
        "cwd": "/private/worktree",
        "permission_mode": "default",
        "hook_event_name": "SessionStart",
        "source": source,
        "model": "claude-enterprise",
    }


def adapter(
    tmp_path: Path,
    client: StubPackClient,
    *,
    installation_id: str = "uls_inst_enterprise",
) -> ClaudeCodeFleetAdapter:
    return ClaudeCodeFleetAdapter(
        registration=registered_state(installation_id),
        managed_root=tmp_path / "managed-agent",
        pack_client=client,
    )


def runtime_environment(
    instance: ClaudeCodeFleetAdapter,
) -> dict[str, str]:
    return {
        "CLAUDE_CONFIG_DIR": str(
            managed_claude_config_dir(instance.managed_root)
        ),
        "UNLIMITED_SKILLS_FLEET_MANAGED_ROOT": str(
            instance.managed_root
        ),
    }


def test_installs_verified_revision_side_by_side_without_activation(
    tmp_path: Path,
) -> None:
    client = StubPackClient()
    instance = adapter(tmp_path, client)
    item = desired_item(client)

    installed = instance.install_revision(item)

    assert installed.install_committed is True
    assert installed.pack_id == client.pack_id
    assert installed.release_id == client.release_id
    assert installed.archive_sha256 == item["archive_sha256"]
    assert len(client.downloads) == 1
    assert client.downloads[0]["release_id"] == client.release_id
    assert (
        client.downloads[0]["expected_sha256"]
        == item["archive_sha256"]
    )
    assert not instance.skills_root.exists()
    assert instance.discover().runtime_generation == "claude-code:inactive"

    same = instance.install_revision(item)
    assert same == installed
    assert len(client.downloads) == 1


def test_installed_payload_cannot_be_rebased_by_tampering_local_metadata(
    tmp_path: Path,
) -> None:
    client = StubPackClient()
    instance = adapter(tmp_path, client)
    item = desired_item(client)
    installed = instance.install_revision(item)
    metadata_path = next(
        (instance.managed_root / "releases").rglob("installed.json")
    )
    payload = metadata_path.parent / "payload"
    skill = payload / "enterprise-skill" / "SKILL.md"
    os.chmod(skill, 0o666)
    skill.write_text("# attacker-controlled\n", encoding="utf-8")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["skills_tree_sha256"] = _tree_digest(payload)
    metadata_path.write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="installed_revision_tampered",
    ):
        instance.verify_revision(item, installed)


def test_rejects_manifest_release_race_before_download(
    tmp_path: Path,
) -> None:
    client = StubPackClient()
    instance = adapter(tmp_path, client)
    item = desired_item(client)
    item["release_id"] = "release_" + ("0" * 32)
    item["manifest_ref"] = (
        f"registry:private-pack/{client.pack_id}/"
        f"{item['release_id']}"
    )

    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="pack_manifest_desired_state_mismatch",
    ):
        instance.install_revision(item)

    assert client.downloads == []


def test_rejects_archive_hash_mismatch_and_path_traversal(
    tmp_path: Path,
) -> None:
    client = StubPackClient()
    item = desired_item(client)
    instance = adapter(tmp_path, client)
    client.archive = pack_archive("# changed after manifest\n")

    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="pack_manifest_desired_state_mismatch",
    ):
        instance.install_revision(item)

    unsafe = StubPackClient(archive=pack_archive(unsafe_name="../escape"))
    unsafe_instance = ClaudeCodeFleetAdapter(
        registration=registered_state("uls_inst_unsafe"),
        managed_root=tmp_path / "unsafe-agent",
        pack_client=unsafe,
    )
    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="pack_archive_path_invalid",
    ):
        unsafe_instance.install_revision(desired_item(unsafe))
    assert not (tmp_path / "escape").exists()

    reserved = StubPackClient(
        archive=pack_archive(unsafe_name="skills/con/SKILL.md")
    )
    reserved_instance = ClaudeCodeFleetAdapter(
        registration=registered_state("uls_inst_reserved"),
        managed_root=tmp_path / "reserved-agent",
        pack_client=reserved,
    )
    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="pack_archive_path_invalid",
    ):
        reserved_instance.install_revision(desired_item(reserved))


def test_activation_requires_new_real_session_start_attestation(
    tmp_path: Path,
) -> None:
    client = StubPackClient()
    instance = adapter(tmp_path, client)
    item = desired_item(client)
    installed = instance.install_revision(item)
    instance.activate_revision(
        item,
        installed,
        activation_nonce=item["activation_nonce"],
    )

    pending = instance.discover()
    assert pending.runtime_generation.startswith("claude-code:pending:")
    assert pending.active_revisions == {
        client.pack_id: client.release_id
    }
    assert pending.inventory_digest == managed_inventory_digest(
        [
            {
                "action": item["action"],
                "archive_sha256": item["archive_sha256"],
                "pack_id": item["pack_id"],
                "release_id": item["release_id"],
                "required": True,
            }
        ]
    )
    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="runtime_attestation_pending",
    ):
        instance.attest_runtime(
            item,
            activation_nonce=item["activation_nonce"],
        )

    result = record_claude_session_start(
        instance.managed_root,
        session_payload("claude-session-secret-value"),
        environment=runtime_environment(instance),
        process_id=4001,
        parent_process_id=4000,
        observed_at="2026-07-27T12:00:00Z",
    )
    assert result["recorded"] is True
    assert result["runtime_generation"].startswith("claude-session:")

    attestation = instance.attest_runtime(
        item,
        activation_nonce=item["activation_nonce"],
    )
    assert attestation.runtime_generation == result["runtime_generation"]
    assert (
        attestation.active_inventory_digest
        == pending.inventory_digest
    )
    stored = (
        instance.state_root / "runtime-current.json"
    ).read_text(encoding="utf-8")
    assert "claude-session-secret-value" not in stored
    assert "/private/transcript.jsonl" not in stored
    assert "/private/worktree" not in stored

    instance.activate_revision(
        item,
        installed,
        activation_nonce=item["activation_nonce"],
    )
    assert (
        instance.discover().runtime_generation
        == result["runtime_generation"]
    )


def test_compaction_hook_does_not_create_runtime_generation(
    tmp_path: Path,
) -> None:
    client = StubPackClient()
    instance = adapter(tmp_path, client)
    item = desired_item(client)
    installed = instance.install_revision(item)
    instance.activate_revision(
        item,
        installed,
        activation_nonce=item["activation_nonce"],
    )

    result = record_claude_session_start(
        instance.managed_root,
        session_payload("same-session", source="compact"),
        environment=runtime_environment(instance),
    )

    assert result == {
        "recorded": False,
        "reason": "runtime_source_not_new_generation",
        "source": "compact",
    }
    assert instance.discover().runtime_generation.startswith(
        "claude-code:pending:"
    )


def test_runtime_attestation_requires_exact_managed_claude_profile(
    tmp_path: Path,
) -> None:
    client = StubPackClient()
    instance = adapter(tmp_path, client)
    item = desired_item(client)
    installed = instance.install_revision(item)
    instance.activate_revision(
        item,
        installed,
        activation_nonce=item["activation_nonce"],
    )
    config_dir = managed_claude_config_dir(instance.managed_root)
    settings = json.loads(
        (config_dir / "settings.json").read_text(encoding="utf-8")
    )
    commands = [
        hook["command"]
        for entry in settings["hooks"]["SessionStart"]
        for hook in entry["hooks"]
    ]
    assert any(
        "fleet" in command and "runtime-start" in command
        for command in commands
    )

    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="runtime_config_dir_unproven",
    ):
        record_claude_session_start(
            instance.managed_root,
            session_payload("unmanaged-session"),
            environment={},
        )
    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="runtime_config_dir_mismatch",
    ):
        record_claude_session_start(
            instance.managed_root,
            session_payload("wrong-profile"),
            environment={
                "CLAUDE_CONFIG_DIR": str(
                    tmp_path / "different-profile"
                )
            },
        )
    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="runtime_managed_root_mismatch",
    ):
        record_claude_session_start(
            instance.managed_root,
            session_payload("wrong-root"),
            environment={
                "CLAUDE_CONFIG_DIR": str(config_dir),
                "UNLIMITED_SKILLS_FLEET_MANAGED_ROOT": str(
                    tmp_path / "different-root"
                ),
            },
        )


def test_rejects_symlink_substitution_below_managed_root(
    tmp_path: Path,
) -> None:
    client = StubPackClient()
    instance = adapter(tmp_path, client)
    external = tmp_path / "external-state"
    external.mkdir()
    shutil.rmtree(instance.state_root)
    try:
        os.symlink(
            external,
            instance.state_root,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("directory symlinks are unavailable on this host")

    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="managed_state_directory_invalid",
    ):
        instance.discover()


def test_independent_drift_changes_heartbeat_and_requires_recovery_session(
    tmp_path: Path,
) -> None:
    client = StubPackClient()
    instance = adapter(tmp_path, client)
    item = desired_item(client)
    installed = instance.install_revision(item)
    instance.activate_revision(
        item,
        installed,
        activation_nonce=item["activation_nonce"],
    )
    first = record_claude_session_start(
        instance.managed_root,
        session_payload("session-before-drift"),
        environment=runtime_environment(instance),
        parent_process_id=5100,
    )
    assert instance.detect_drift(item) is False

    skill = (
        instance.skills_root
        / "enterprise-skill"
        / "SKILL.md"
    )
    os.chmod(skill, 0o666)
    skill.write_text("# independently modified\n", encoding="utf-8")

    drifted = instance.discover()
    assert drifted.inventory_digest != managed_inventory_digest(
        [
            {
                "action": item["action"],
                "archive_sha256": item["archive_sha256"],
                "pack_id": item["pack_id"],
                "release_id": item["release_id"],
                "required": True,
            }
        ]
    )
    assert instance.detect_drift(item) is True
    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="runtime_attestation_invalid",
    ):
        instance.attest_runtime(
            item,
            activation_nonce=item["activation_nonce"],
        )

    instance.activate_revision(
        item,
        installed,
        activation_nonce=item["activation_nonce"],
    )
    assert instance.detect_drift(item) is False
    assert instance.discover().runtime_generation.startswith(
        "claude-code:pending:"
    )
    second = record_claude_session_start(
        instance.managed_root,
        session_payload("session-after-drift"),
        environment=runtime_environment(instance),
        parent_process_id=5200,
    )
    assert second["runtime_generation"] != first["runtime_generation"]
    assert (
        instance.attest_runtime(
            item,
            activation_nonce=item["activation_nonce"],
        ).runtime_generation
        == second["runtime_generation"]
    )


def test_higher_epoch_rollback_activates_immutable_older_release(
    tmp_path: Path,
) -> None:
    client = StubPackClient(version="1.0.0", archive=pack_archive("# A\n"))
    instance = adapter(tmp_path, client)
    item_a = desired_item(client, nonce="nonce_a")
    installed_a = instance.install_revision(item_a)
    instance.activate_revision(
        item_a,
        installed_a,
        activation_nonce=item_a["activation_nonce"],
    )
    runtime_a = record_claude_session_start(
        instance.managed_root,
        session_payload("session-a"),
        environment=runtime_environment(instance),
        parent_process_id=6100,
    )

    client.version = "2.0.0"
    client.archive = pack_archive("# B\n")
    item_b = desired_item(client, nonce="nonce_b")
    installed_b = instance.install_revision(item_b)
    instance.activate_revision(
        item_b,
        installed_b,
        activation_nonce=item_b["activation_nonce"],
    )
    runtime_b = record_claude_session_start(
        instance.managed_root,
        session_payload("session-b"),
        environment=runtime_environment(instance),
        parent_process_id=6200,
    )
    assert runtime_b["runtime_generation"] != runtime_a["runtime_generation"]

    rollback = dict(item_a)
    rollback.update(
        {
            "attempt_id": "attempt_rollback_higher_epoch",
            "activation_nonce": "nonce_rollback_higher_epoch",
            "action": "rollback",
        }
    )
    instance.rollback_revision(
        rollback,
        installed_a,
        activation_nonce=rollback["activation_nonce"],
    )
    assert instance.discover().runtime_generation.startswith(
        "claude-code:pending:"
    )
    with pytest.raises(ClaudeCodeFleetAdapterError):
        instance.attest_runtime(
            rollback,
            activation_nonce=rollback["activation_nonce"],
        )
    runtime_rollback = record_claude_session_start(
        instance.managed_root,
        session_payload("session-rollback"),
        environment=runtime_environment(instance),
        parent_process_id=6300,
    )
    attestation = instance.attest_runtime(
        rollback,
        activation_nonce=rollback["activation_nonce"],
    )
    assert attestation.release_id == item_a["release_id"]
    assert (
        attestation.runtime_generation
        == runtime_rollback["runtime_generation"]
    )
    assert len(
        list((instance.managed_root / "releases").rglob("installed.json"))
    ) == 2


def test_managed_root_is_bound_to_registration_installation(
    tmp_path: Path,
) -> None:
    client = StubPackClient()
    root = tmp_path / "managed-agent"
    ClaudeCodeFleetAdapter(
        registration=registered_state("uls_inst_one"),
        managed_root=root,
        pack_client=client,
    )

    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="managed_root_installation_mismatch",
    ):
        ClaudeCodeFleetAdapter(
            registration=registered_state("uls_inst_two"),
            managed_root=root,
            pack_client=client,
        )


def test_multi_pack_inventory_is_materialized_and_attested_atomically(
    tmp_path: Path,
) -> None:
    pack_a = StubPackClient(
        pack_id="pack_a",
        version="1.0.0",
        archive=pack_archive(
            "# Skill A\n",
            skill_name="enterprise-a",
        ),
    )
    pack_b = StubPackClient(
        pack_id="pack_b",
        version="2.0.0",
        archive=pack_archive(
            "# Skill B\n",
            skill_name="enterprise-b",
        ),
    )
    instance = ClaudeCodeFleetAdapter(
        registration=registered_state(),
        managed_root=tmp_path / "managed-bundle",
        pack_client=MultiPackClient(pack_a, pack_b),
    )
    item_a = desired_item(pack_a, nonce="nonce_a")
    item_b = desired_item(pack_b, nonce="nonce_b")
    installed = {
        "pack_a": instance.install_revision(item_a),
        "pack_b": instance.install_revision(item_b),
    }

    instance.activate_inventory(
        [item_a, item_b],
        installed,
        activation_nonces={
            "pack_a": "nonce_a",
            "pack_b": "nonce_b",
        },
    )

    assert (instance.skills_root / "enterprise-a" / "SKILL.md").is_file()
    assert (instance.skills_root / "enterprise-b" / "SKILL.md").is_file()
    discovered = instance.discover()
    assert discovered.active_revisions == {
        "pack_a": item_a["release_id"],
        "pack_b": item_b["release_id"],
    }
    expected_digest = managed_inventory_digest(
        [inventory_row(item_a), inventory_row(item_b)]
    )
    assert discovered.inventory_digest == expected_digest
    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="runtime_attestation_pending",
    ):
        instance.attest_inventory(
            [item_a, item_b],
            activation_nonces={
                "pack_a": "nonce_a",
                "pack_b": "nonce_b",
            },
        )

    runtime = record_claude_session_start(
        instance.managed_root,
        session_payload("session-bundle"),
        environment=runtime_environment(instance),
        parent_process_id=6400,
    )
    attestation = instance.attest_inventory(
        [item_a, item_b],
        activation_nonces={
            "pack_a": "nonce_a",
            "pack_b": "nonce_b",
        },
    )

    assert attestation.runtime_generation == runtime["runtime_generation"]
    assert attestation.activation_nonces == {
        "pack_a": "nonce_a",
        "pack_b": "nonce_b",
    }
    assert attestation.active_revisions == {
        "pack_a": item_a["release_id"],
        "pack_b": item_b["release_id"],
    }
    assert attestation.active_archive_sha256 == {
        "pack_a": item_a["archive_sha256"],
        "pack_b": item_b["archive_sha256"],
    }
    assert attestation.active_inventory_digest == expected_digest
    assert instance.detect_inventory_drift([item_a, item_b]) is False


def test_multi_pack_activation_rejects_skill_name_collisions(
    tmp_path: Path,
) -> None:
    pack_a = StubPackClient(
        pack_id="pack_a",
        archive=pack_archive("# A\n", skill_name="same-skill"),
    )
    pack_b = StubPackClient(
        pack_id="pack_b",
        archive=pack_archive("# B\n", skill_name="same-skill"),
    )
    instance = ClaudeCodeFleetAdapter(
        registration=registered_state(),
        managed_root=tmp_path / "managed-collision",
        pack_client=MultiPackClient(pack_a, pack_b),
    )
    item_a = desired_item(pack_a, nonce="nonce_a")
    item_b = desired_item(pack_b, nonce="nonce_b")
    installed = {
        "pack_a": instance.install_revision(item_a),
        "pack_b": instance.install_revision(item_b),
    }

    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="managed_skill_collision",
    ):
        instance.activate_inventory(
            [item_a, item_b],
            installed,
            activation_nonces={
                "pack_a": "nonce_a",
                "pack_b": "nonce_b",
            },
        )

    assert not instance.skills_root.exists()


def test_multi_pack_activation_rejects_declared_name_collisions(
    tmp_path: Path,
) -> None:
    pack_a = StubPackClient(
        pack_id="pack_a",
        archive=pack_archive(
            "# A\n",
            skill_name="folder-a",
            declared_name="shared-runtime-name",
        ),
    )
    pack_b = StubPackClient(
        pack_id="pack_b",
        archive=pack_archive(
            "# B\n",
            skill_name="folder-b",
            declared_name="shared-runtime-name",
        ),
    )
    instance = ClaudeCodeFleetAdapter(
        registration=registered_state(),
        managed_root=tmp_path / "managed-declared-collision",
        pack_client=MultiPackClient(pack_a, pack_b),
    )
    item_a = desired_item(pack_a, nonce="nonce_a")
    item_b = desired_item(pack_b, nonce="nonce_b")
    installed = {
        "pack_a": instance.install_revision(item_a),
        "pack_b": instance.install_revision(item_b),
    }

    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="managed_skill_collision",
    ):
        instance.activate_inventory(
            [item_a, item_b],
            installed,
            activation_nonces={
                "pack_a": "nonce_a",
                "pack_b": "nonce_b",
            },
        )


def test_loads_only_explicit_active_ed25519_fleet_keys(
    tmp_path: Path,
) -> None:
    active = bytes(range(32))
    retired = bytes(reversed(range(32)))
    keys_path = tmp_path / "fleet-public-keys.json"
    keys_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract_id": "unlimited-skills.fleet-wire",
                "contract_version": 1,
                "keys": [
                    {
                        "algorithm": "ed25519",
                        "role": "fleet-desired-state-signing",
                        "key_id": "fleet-active-v1",
                        "public_key": base64.urlsafe_b64encode(
                            active
                        ).decode("ascii").rstrip("="),
                        "status": "active",
                    },
                    {
                        "algorithm": "ed25519",
                        "role": "fleet-desired-state-signing",
                        "key_id": "fleet-retired-v0",
                        "public_key": base64.urlsafe_b64encode(
                            retired
                        ).decode("ascii").rstrip("="),
                        "status": "retired",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_fleet_public_keys(keys_path) == {
        "fleet-active-v1": active
    }


def test_hook_payload_parser_is_bounded_and_object_only() -> None:
    payload = session_payload("session-parser")
    assert parse_session_start_payload(
        json.dumps(payload).encode("utf-8")
    ) == payload
    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="runtime_hook_input_invalid",
    ):
        parse_session_start_payload(b"[]")
    with pytest.raises(
        ClaudeCodeFleetAdapterError,
        match="runtime_hook_input_invalid",
    ):
        parse_session_start_payload(b"x" * (64 * 1024 + 1))


def test_adapter_version_is_receipt_safe_identifier() -> None:
    assert CLAUDE_CODE_ADAPTER_VERSION == "claude-code-fleet/1.0.0"


def test_cli_exposes_explicit_enterprise_fleet_controls() -> None:
    parser = build_parser()
    runtime = parser.parse_args(
        [
            "fleet",
            "runtime-start",
            "--managed-root",
            "managed",
            "--json",
        ]
    )
    assert runtime.func.__name__ == "cmd_fleet_runtime_start"
    launch = parser.parse_args(
        [
            "fleet",
            "claude-launch",
            "--managed-root",
            "managed",
            "--dry-run",
            "--json",
            "--",
            "--agent",
            "enterprise",
        ]
    )
    assert launch.func.__name__ == "cmd_fleet_claude_launch"
    assert launch.claude_args == ["--", "--agent", "enterprise"]
    run_once = parser.parse_args(
        [
            "fleet",
            "run-once",
            "--managed-root",
            "managed",
            "--public-keys",
            "fleet-keys.json",
            "--auto-activate",
            "--json",
        ]
    )
    assert run_once.func.__name__ == "cmd_fleet_run_once"
    assert run_once.auto_activate is True


def test_claude_launcher_uses_exact_managed_profile_without_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(
        fleet_commands,
        "load_registration",
        lambda: registered_state(),
    )
    monkeypatch.setattr(
        fleet_commands.shutil,
        "which",
        lambda value: "/verified/bin/claude",
    )
    monkeypatch.setattr(
        fleet_commands.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append((command, kwargs))
            or SimpleNamespace(returncode=7)
        ),
    )
    managed_root = tmp_path / "managed-launch"
    args = SimpleNamespace(
        managed_root=str(managed_root),
        claude_executable="claude",
        claude_args=["--", "--agent", "enterprise"],
        dry_run=False,
        json=False,
        timeout=3.0,
    )

    assert fleet_commands.cmd_fleet_claude_launch(args) == 7
    assert calls[0][0] == [
        "/verified/bin/claude",
        "--agent",
        "enterprise",
    ]
    assert "shell" not in calls[0][1]
    assert calls[0][1]["check"] is False
    assert calls[0][1]["env"]["CLAUDE_CONFIG_DIR"] == str(
        managed_claude_config_dir(managed_root)
    )
    assert calls[0][1]["env"][
        "UNLIMITED_SKILLS_FLEET_MANAGED_ROOT"
    ] == str(managed_root.resolve())
