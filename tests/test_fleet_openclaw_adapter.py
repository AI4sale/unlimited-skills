from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from unlimited_skills.commands import fleet as fleet_commands
from unlimited_skills.fleet.claude_code import (
    _tree_digest,
    managed_inventory_digest,
    private_pack_release_id,
)
from unlimited_skills.fleet.openclaw import (
    OPENCLAW_ADAPTER_VERSION,
    OpenClawFleetAdapter,
    OpenClawFleetAdapterError,
    parse_openclaw_bootstrap_payload,
    record_openclaw_agent_bootstrap,
)
from unlimited_skills.registration import RegistrationState


def registered_state() -> RegistrationState:
    return RegistrationState(
        install_id="uls_inst_openclaw",
        server_url="https://registry.example.test",
        license_token="secret-token",
        device_private_key="secret-device-key",
    )


def pack_archive(skill_name: str, body: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(
            f"pack/skills/{skill_name}/SKILL.md",
            f"---\nname: {skill_name}\ndescription: test\n---\n{body}",
        )
    return output.getvalue()


class PackClient:
    def __init__(self, packs: dict[str, tuple[str, bytes]]) -> None:
        self.packs = packs

    def release_id(self, pack_id: str) -> str:
        version, archive = self.packs[pack_id]
        digest = hashlib.sha256(archive).hexdigest()
        return private_pack_release_id(
            pack_id,
            version,
            "sha256:" + digest,
        )

    def signed_manifest(
        self,
        pack_id: str,
        *,
        request_context: dict | None = None,
    ) -> dict:
        del request_context
        version, archive = self.packs[pack_id]
        digest = hashlib.sha256(archive).hexdigest()
        return {
            "manifest": {
                "schema_version": 1,
                "manifest_type": "private-team-pack-manifest",
                "pack_id": pack_id,
                "team_id": "team_openclaw",
                "namespace": "team/openclaw",
                "name": pack_id,
                "version": version,
                "visibility": "private-team",
                "sha256": digest,
                "bytes": len(archive),
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
        archive = self.packs[pack_id][1]
        assert release_id == self.release_id(pack_id)
        assert expected_sha256 == (
            "sha256:" + hashlib.sha256(archive).hexdigest()
        )
        return archive


def desired_item(
    client: PackClient,
    pack_id: str,
    nonce: str,
) -> dict:
    version, archive = client.packs[pack_id]
    digest = "sha256:" + hashlib.sha256(archive).hexdigest()
    release_id = client.release_id(pack_id)
    return {
        "attempt_id": f"attempt_{pack_id}",
        "pack_id": pack_id,
        "release_id": release_id,
        "version": version,
        "archive_sha256": digest,
        "activation_nonce": nonce,
        "manifest_ref": (
            f"registry:private-pack/{pack_id}/{release_id}"
        ),
        "required": True,
        "action": "activate",
    }


def inventory_row(item: dict) -> dict:
    return {
        "action": item["action"],
        "archive_sha256": item["archive_sha256"],
        "pack_id": item["pack_id"],
        "release_id": item["release_id"],
        "required": item["required"],
    }


def adapter(
    tmp_path: Path,
    client: PackClient,
    *,
    agent_id: str = "coding",
) -> OpenClawFleetAdapter:
    workspace = tmp_path / f"workspace-{agent_id}"
    workspace.mkdir()
    return OpenClawFleetAdapter(
        registration=registered_state(),
        managed_root=tmp_path / "fleet" / agent_id,
        workspace=workspace,
        agent_id=agent_id,
        openclaw_home=tmp_path / ".openclaw",
        pack_client=client,
        python_executable=Path("/verified/python"),
    )


def bootstrap_payload(
    instance: OpenClawFleetAdapter,
    *,
    agent_id: str = "coding",
    workspace: str | None = None,
) -> dict:
    return {
        "hook_event_name": "agent:bootstrap",
        "agent_id": agent_id,
        "workspace_dir": (
            workspace
            if workspace is not None
            else str(instance.workspace)
        ),
        "session_key": "private-openclaw-session-key",
    }


def test_openclaw_bundle_requires_real_agent_bootstrap_attestation(
    tmp_path: Path,
) -> None:
    client = PackClient(
        {
            "pack_a": ("1.0.0", pack_archive("skill-a", "# A\n")),
            "pack_b": ("2.0.0", pack_archive("skill-b", "# B\n")),
        }
    )
    instance = adapter(tmp_path, client)
    item_a = desired_item(client, "pack_a", "nonce_a")
    item_b = desired_item(client, "pack_b", "nonce_b")
    items = [item_a, item_b]
    installed = {
        item["pack_id"]: instance.install_revision(item)
        for item in items
    }
    nonces = {"pack_a": "nonce_a", "pack_b": "nonce_b"}

    instance.activate_inventory(
        items,
        installed,
        activation_nonces=nonces,
    )

    assert (
        instance.skills_root / "skill-a" / "SKILL.md"
    ).is_file()
    assert (
        instance.skills_root / "skill-b" / "SKILL.md"
    ).is_file()
    assert instance.discover().runtime_generation.startswith(
        "openclaw:pending:"
    )
    with pytest.raises(
        OpenClawFleetAdapterError,
        match="runtime_attestation_pending",
    ):
        instance.attest_inventory(
            items,
            activation_nonces=nonces,
        )

    result = record_openclaw_agent_bootstrap(
        instance.managed_root,
        bootstrap_payload(instance),
        process_id=5101,
        parent_process_id=5100,
        observed_at="2026-07-28T12:00:00Z",
    )
    attestation = instance.attest_inventory(
        items,
        activation_nonces=nonces,
    )

    assert result["recorded"] is True
    assert attestation.runtime_generation.startswith(
        "openclaw-bootstrap:"
    )
    assert attestation.activation_nonces == nonces
    assert attestation.active_revisions == {
        item["pack_id"]: item["release_id"] for item in items
    }
    assert attestation.active_inventory_digest == (
        managed_inventory_digest(
            [inventory_row(item) for item in items]
        )
    )
    marker = (
        instance.state_root / "runtime-current.json"
    ).read_text(encoding="utf-8")
    assert "private-openclaw-session-key" not in marker
    assert str(instance.workspace) not in marker


def test_openclaw_runtime_binding_rejects_other_agent_or_workspace(
    tmp_path: Path,
) -> None:
    client = PackClient(
        {"pack_a": ("1.0.0", pack_archive("skill-a", "# A\n"))}
    )
    instance = adapter(tmp_path, client)
    item = desired_item(client, "pack_a", "nonce_a")
    installed = instance.install_revision(item)
    instance.activate_revision(
        item,
        installed,
        activation_nonce="nonce_a",
    )

    with pytest.raises(
        OpenClawFleetAdapterError,
        match="runtime_agent_binding_mismatch",
    ):
        record_openclaw_agent_bootstrap(
            instance.managed_root,
            bootstrap_payload(instance, agent_id="main"),
        )
    with pytest.raises(
        OpenClawFleetAdapterError,
        match="runtime_workspace_binding_mismatch",
    ):
        record_openclaw_agent_bootstrap(
            instance.managed_root,
            bootstrap_payload(
                instance,
                workspace=str(tmp_path / "other-workspace"),
            ),
        )


def test_openclaw_installed_payload_is_bound_to_retained_archive(
    tmp_path: Path,
) -> None:
    client = PackClient(
        {"pack_a": ("1.0.0", pack_archive("skill-a", "# A\n"))}
    )
    instance = adapter(tmp_path, client)
    desired = desired_item(client, "pack_a", "nonce_a")
    installed = instance.install_revision(desired)
    metadata_path = next(
        (instance.managed_root / "releases").rglob("installed.json")
    )
    payload = metadata_path.parent / "payload"
    skill = payload / "skill-a" / "SKILL.md"
    os.chmod(skill, 0o666)
    skill.write_text(
        "---\nname: skill-a\ndescription: test\n---\n# changed\n",
        encoding="utf-8",
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["skills_tree_sha256"] = _tree_digest(payload)
    metadata_path.write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    with pytest.raises(
        OpenClawFleetAdapterError,
        match="installed_revision_tampered",
    ):
        instance.verify_revision(desired, installed)


def test_openclaw_rejects_collision_with_unmanaged_workspace_skill(
    tmp_path: Path,
) -> None:
    client = PackClient(
        {
            "pack_a": (
                "1.0.0",
                pack_archive("existing-skill", "# managed\n"),
            )
        }
    )
    instance = adapter(tmp_path, client)
    unmanaged = instance.workspace / "skills" / "manual"
    unmanaged.mkdir(parents=True)
    (unmanaged / "SKILL.md").write_text(
        "---\nname: existing-skill\n---\n# manual\n",
        encoding="utf-8",
    )
    item = desired_item(client, "pack_a", "nonce_a")
    installed = instance.install_revision(item)

    with pytest.raises(
        OpenClawFleetAdapterError,
        match="unmanaged_skill_collision",
    ):
        instance.activate_revision(
            item,
            installed,
            activation_nonce="nonce_a",
        )

    assert not instance.skills_root.exists()


def test_openclaw_hook_is_provisioned_for_each_agent_target(
    tmp_path: Path,
) -> None:
    client = PackClient(
        {"pack_a": ("1.0.0", pack_archive("skill-a", "# A\n"))}
    )
    coding = adapter(tmp_path, client, agent_id="coding")
    main = adapter(tmp_path, client, agent_id="main")
    target_path = (
        tmp_path / ".openclaw" / "fleet" / "targets.json"
    )
    targets = json.loads(target_path.read_text(encoding="utf-8"))

    assert set(targets["targets"]) == {"coding", "main"}
    assert targets["targets"]["coding"]["managed_root"] == str(
        coding.managed_root
    )
    assert targets["targets"]["main"]["workspace"] == str(
        main.workspace
    )
    if os.name != "nt":
        assert (target_path.stat().st_mode & 0o777) == 0o600
    hook_root = (
        tmp_path
        / ".openclaw"
        / "hooks"
        / "unlimited-skills-fleet"
    )
    assert (hook_root / "HOOK.md").is_file()
    handler = (hook_root / "handler.js").read_text(
        encoding="utf-8"
    )
    assert "agent:bootstrap" in (
        hook_root / "HOOK.md"
    ).read_text(encoding="utf-8")
    assert "spawnSync" in handler
    assert "...process.env" not in handler
    assert "license_token" not in handler
    node = shutil.which("node")
    if node:
        checked = subprocess.run(
            [node, "--check", str(hook_root / "handler.js")],
            check=False,
            capture_output=True,
            text=True,
        )
        assert checked.returncode == 0, checked.stderr


def test_openclaw_payload_parser_is_bounded() -> None:
    payload = {
        "hook_event_name": "agent:bootstrap",
        "agent_id": "main",
        "workspace_dir": "/workspace",
        "session_key": "session",
    }
    assert parse_openclaw_bootstrap_payload(
        json.dumps(payload).encode("utf-8")
    ) == payload
    with pytest.raises(
        OpenClawFleetAdapterError,
        match="runtime_hook_input_invalid",
    ):
        parse_openclaw_bootstrap_payload(b"[]")
    with pytest.raises(
        OpenClawFleetAdapterError,
        match="runtime_hook_input_invalid",
    ):
        parse_openclaw_bootstrap_payload(b"x" * (64 * 1024 + 1))


def test_openclaw_adapter_version_is_receipt_safe_identifier() -> None:
    assert OPENCLAW_ADAPTER_VERSION == "openclaw-fleet/1.0.0"


def test_openclaw_provision_verifies_configured_agent_and_enables_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace-coding"
    workspace.mkdir()
    calls: list[list[str]] = []
    responses = [
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": "coding",
                        "workspace": str(workspace),
                    }
                ]
            ),
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "hookKey": "unlimited-skills-fleet",
                    "loadable": True,
                    "disabled": False,
                }
            ),
            stderr="",
        ),
    ]
    monkeypatch.setattr(
        fleet_commands,
        "load_registration",
        lambda: registered_state(),
    )
    monkeypatch.setattr(
        fleet_commands.shutil,
        "which",
        lambda value: "/verified/openclaw",
    )
    monkeypatch.setattr(
        fleet_commands.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append(command) or responses.pop(0)
        ),
    )
    args = SimpleNamespace(
        managed_root=str(tmp_path / "fleet" / "coding"),
        agent_id="coding",
        workspace=str(workspace),
        openclaw_home=str(tmp_path / ".openclaw"),
        openclaw_executable="openclaw",
        timeout=3.0,
        json=True,
    )

    assert fleet_commands.cmd_fleet_openclaw_provision(args) == 0
    assert calls == [
        ["/verified/openclaw", "agents", "list", "--json"],
        [
            "/verified/openclaw",
            "hooks",
            "enable",
            "unlimited-skills-fleet",
        ],
        [
            "/verified/openclaw",
            "hooks",
            "info",
            "unlimited-skills-fleet",
            "--json",
        ],
    ]
