from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from unlimited_skills.cli import build_parser
from unlimited_skills.commands import fleet as fleet_commands
from unlimited_skills.fleet.claude_code import private_pack_release_id
from unlimited_skills.fleet.codex import (
    CODEX_ADAPTER_VERSION,
    CodexFleetAdapter,
    CodexFleetAdapterError,
    managed_codex_home,
    managed_codex_workspace,
    parse_codex_session_start_payload,
    record_codex_session_start,
)
from unlimited_skills.registration import RegistrationState


def registered_state() -> RegistrationState:
    return RegistrationState(
        install_id="uls_inst_codex",
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
                "team_id": "team_codex",
                "namespace": "team/codex",
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
) -> CodexFleetAdapter:
    return CodexFleetAdapter(
        registration=registered_state(),
        managed_root=tmp_path / "managed-codex",
        pack_client=client,
        user_skills_root=tmp_path / "user-skills",
    )


def session_payload(instance: CodexFleetAdapter) -> dict:
    return {
        "session_id": "private-codex-session-id",
        "transcript_path": "/private/transcript.jsonl",
        "cwd": str(instance.workspace),
        "permission_mode": "default",
        "hook_event_name": "SessionStart",
        "source": "startup",
        "model": "gpt-5.6-sol",
    }


def runtime_environment(instance: CodexFleetAdapter) -> dict[str, str]:
    return {
        "CODEX_HOME": str(instance.codex_home),
        "UNLIMITED_SKILLS_FLEET_MANAGED_ROOT": str(
            instance.managed_root
        ),
    }


def test_codex_bundle_requires_real_session_start_attestation(
    tmp_path: Path,
) -> None:
    client = PackClient(
        {
            "pack_a": ("1.0.0", archive("codex-a", "# A\n")),
            "pack_b": ("2.0.0", archive("codex-b", "# B\n")),
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

    assert (instance.skills_root / "codex-a" / "SKILL.md").is_file()
    assert (instance.skills_root / "codex-b" / "SKILL.md").is_file()
    assert instance.discover().runtime_generation.startswith(
        "codex:pending:"
    )
    with pytest.raises(
        CodexFleetAdapterError,
        match="runtime_attestation_pending",
    ):
        instance.attest_inventory(
            items,
            activation_nonces=nonces,
        )

    result = record_codex_session_start(
        instance.managed_root,
        session_payload(instance),
        environment=runtime_environment(instance),
        process_id=6101,
        parent_process_id=6100,
        observed_at="2026-07-28T12:10:00Z",
    )
    attestation = instance.attest_inventory(
        items,
        activation_nonces=nonces,
    )

    assert result["recorded"] is True
    assert attestation.runtime_generation.startswith(
        "codex-session:"
    )
    assert attestation.activation_nonces == nonces
    marker = (
        instance.state_root / "runtime-current.json"
    ).read_text(encoding="utf-8")
    assert "private-codex-session-id" not in marker
    assert "/private/transcript.jsonl" not in marker
    assert str(instance.workspace) not in marker


def test_codex_runtime_rejects_wrong_home_or_workspace(
    tmp_path: Path,
) -> None:
    client = PackClient({"pack": ("1.0.0", archive("codex"))})
    instance = adapter(tmp_path, client)
    desired = item(client, "pack", "nonce")
    installed = instance.install_revision(desired)
    instance.activate_revision(
        desired,
        installed,
        activation_nonce="nonce",
    )
    wrong_home = runtime_environment(instance)
    wrong_home["CODEX_HOME"] = str(tmp_path / "wrong-home")
    with pytest.raises(
        CodexFleetAdapterError,
        match="runtime_codex_home_mismatch",
    ):
        record_codex_session_start(
            instance.managed_root,
            session_payload(instance),
            environment=wrong_home,
        )
    wrong_workspace = session_payload(instance)
    wrong_workspace["cwd"] = str(tmp_path / "wrong-workspace")
    with pytest.raises(
        CodexFleetAdapterError,
        match="runtime_workspace_binding_mismatch",
    ):
        record_codex_session_start(
            instance.managed_root,
            wrong_workspace,
            environment=runtime_environment(instance),
        )


def test_codex_provisions_isolated_user_hook_and_workspace(
    tmp_path: Path,
) -> None:
    client = PackClient({"pack": ("1.0.0", archive("codex"))})
    instance = adapter(tmp_path, client)

    assert instance.codex_home == managed_codex_home(
        instance.managed_root
    )
    assert instance.workspace == managed_codex_workspace(
        instance.managed_root
    )
    hooks = json.loads(
        (instance.codex_home / "hooks.json").read_text(
            encoding="utf-8"
        )
    )
    session_start = hooks["hooks"]["SessionStart"]
    assert len(session_start) == 1
    assert session_start[0]["matcher"] == "startup|resume"
    command = session_start[0]["hooks"][0]["command"]
    assert "codex-runtime-start" in command
    assert str(instance.managed_root) in command
    assert "secret-token" not in command
    assert instance.workspace.is_dir()


def test_codex_rejects_collision_with_user_skill(
    tmp_path: Path,
) -> None:
    client = PackClient(
        {"pack": ("1.0.0", archive("shared-name"))}
    )
    user_skill = tmp_path / "user-skills" / "manual"
    user_skill.mkdir(parents=True)
    (user_skill / "SKILL.md").write_text(
        "---\nname: shared-name\ndescription: manual\n---\n",
        encoding="utf-8",
    )
    instance = adapter(tmp_path, client)
    desired = item(client, "pack", "nonce")
    installed = instance.install_revision(desired)

    with pytest.raises(
        CodexFleetAdapterError,
        match="unmanaged_skill_collision",
    ):
        instance.activate_revision(
            desired,
            installed,
            activation_nonce="nonce",
        )


def test_codex_payload_parser_is_bounded() -> None:
    payload = {
        "session_id": "session",
        "cwd": "/workspace",
        "hook_event_name": "SessionStart",
        "source": "startup",
    }
    assert parse_codex_session_start_payload(
        json.dumps(payload).encode("utf-8")
    ) == payload
    with pytest.raises(
        CodexFleetAdapterError,
        match="runtime_hook_input_invalid",
    ):
        parse_codex_session_start_payload(b"[]")
    with pytest.raises(
        CodexFleetAdapterError,
        match="runtime_hook_input_invalid",
    ):
        parse_codex_session_start_payload(b"x" * (64 * 1024 + 1))


def test_codex_adapter_version_is_receipt_safe_identifier() -> None:
    assert CODEX_ADAPTER_VERSION == "codex-fleet/1.0.0"


def test_cli_exposes_codex_and_openclaw_fleet_controls() -> None:
    parser = build_parser()
    codex_hook = parser.parse_args(
        [
            "fleet",
            "codex-runtime-start",
            "--managed-root",
            "managed",
            "--json",
        ]
    )
    assert (
        codex_hook.func.__name__
        == "cmd_fleet_codex_runtime_start"
    )
    openclaw_hook = parser.parse_args(
        [
            "fleet",
            "openclaw-runtime-start",
            "--managed-root",
            "managed",
            "--json",
        ]
    )
    assert (
        openclaw_hook.func.__name__
        == "cmd_fleet_openclaw_runtime_start"
    )
    openclaw_provision = parser.parse_args(
        [
            "fleet",
            "openclaw-provision",
            "--managed-root",
            "managed",
            "--agent-id",
            "coding",
            "--workspace",
            "/workspace",
        ]
    )
    assert (
        openclaw_provision.func.__name__
        == "cmd_fleet_openclaw_provision"
    )
    codex_launch = parser.parse_args(
        [
            "fleet",
            "codex-launch",
            "--managed-root",
            "managed",
            "--dry-run",
            "--json",
            "--",
            "exec",
            "--ephemeral",
        ]
    )
    assert codex_launch.func.__name__ == "cmd_fleet_codex_launch"
    run_once = parser.parse_args(
        [
            "fleet",
            "run-once",
            "--managed-root",
            "managed",
            "--public-keys",
            "keys.json",
            "--runtime-vendor",
            "openclaw",
            "--agent-id",
            "coding",
            "--workspace",
            "/workspace",
            "--openclaw-home",
            "/state",
        ]
    )
    assert run_once.runtime_vendor == "openclaw"
    assert run_once.agent_id == "coding"


def test_codex_launcher_binds_home_and_workspace_without_shell(
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
        lambda value: "C:\\verified\\codex.exe",
    )
    monkeypatch.setattr(
        fleet_commands.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append((command, kwargs))
            or SimpleNamespace(returncode=9)
        ),
    )
    managed_root = tmp_path / "managed-launch"
    args = SimpleNamespace(
        managed_root=str(managed_root),
        codex_executable="codex",
        codex_args=["--", "exec", "--ephemeral", "test"],
        dry_run=False,
        json=False,
        timeout=3.0,
    )

    assert fleet_commands.cmd_fleet_codex_launch(args) == 9
    assert calls[0][0] == [
        "C:\\verified\\codex.exe",
        "-C",
        str(managed_codex_workspace(managed_root)),
        "exec",
        "--ephemeral",
        "test",
    ]
    assert "shell" not in calls[0][1]
    assert calls[0][1]["check"] is False
    assert calls[0][1]["env"]["CODEX_HOME"] == str(
        managed_codex_home(managed_root)
    )
