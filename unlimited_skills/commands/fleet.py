"""Enterprise fleet agent control-loop commands."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from unlimited_skills import __version__
from unlimited_skills.fleet import (
    ClaudeCodeFleetAdapter,
    CodexFleetAdapter,
    FleetAgentClient,
    FleetAgentIdentityStore,
    HermesFleetAdapter,
    OpenClawFleetAdapter,
    ReceiptSpool,
    load_fleet_public_keys,
    managed_claude_config_dir,
    managed_codex_home,
    managed_codex_workspace,
    parse_codex_session_start_payload,
    parse_hermes_session_start_payload,
    parse_openclaw_bootstrap_payload,
    parse_session_start_payload,
    record_claude_session_start,
    record_codex_session_start,
    record_hermes_session_start,
    record_openclaw_agent_bootstrap,
)
from unlimited_skills.registration import load_registration


FLEET_PAYLOAD_CAPABILITY = "fleet-payload-v2"
FLEET_CLIENT_VERSION_CAPABILITY = (
    f"client-version-{__version__}"
)


def _required_path(value: str, reason: str) -> Path:
    normalized = str(value or "").strip()
    if not normalized:
        raise RuntimeError(reason)
    return Path(normalized).expanduser()


def _emit(payload: dict, *, as_json: bool) -> int:
    if as_json:
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    for key, value in payload.items():
        print(f"{key}: {value}")
    return 0


def cmd_fleet_runtime_start(args: argparse.Namespace) -> int:
    managed_root = _required_path(
        args.managed_root
        or os.environ.get("UNLIMITED_SKILLS_FLEET_MANAGED_ROOT", ""),
        "fleet_managed_root_required",
    )
    raw = sys.stdin.buffer.read(64 * 1024 + 1)
    payload = parse_session_start_payload(raw)
    result = record_claude_session_start(managed_root, payload)
    return _emit(result, as_json=args.json)


def cmd_fleet_codex_runtime_start(args: argparse.Namespace) -> int:
    managed_root = _required_path(
        args.managed_root
        or os.environ.get("UNLIMITED_SKILLS_FLEET_MANAGED_ROOT", ""),
        "fleet_managed_root_required",
    )
    raw = sys.stdin.buffer.read(64 * 1024 + 1)
    payload = parse_codex_session_start_payload(raw)
    result = record_codex_session_start(managed_root, payload)
    if args.hook_output:
        return 0
    return _emit(result, as_json=args.json)


def cmd_fleet_openclaw_runtime_start(
    args: argparse.Namespace,
) -> int:
    managed_root = _required_path(
        args.managed_root
        or os.environ.get("UNLIMITED_SKILLS_FLEET_MANAGED_ROOT", ""),
        "fleet_managed_root_required",
    )
    raw = sys.stdin.buffer.read(64 * 1024 + 1)
    payload = parse_openclaw_bootstrap_payload(raw)
    result = record_openclaw_agent_bootstrap(
        managed_root,
        payload,
    )
    return _emit(result, as_json=args.json)


def cmd_fleet_hermes_runtime_start(args: argparse.Namespace) -> int:
    managed_root = _required_path(
        args.managed_root
        or os.environ.get("UNLIMITED_SKILLS_FLEET_MANAGED_ROOT", ""),
        "fleet_managed_root_required",
    )
    hermes_home = _required_path(
        args.hermes_home
        or os.environ.get(
            "UNLIMITED_SKILLS_FLEET_HERMES_HOME",
            "",
        )
        or os.environ.get("HERMES_HOME", ""),
        "hermes_home_required",
    )
    raw = sys.stdin.buffer.read(64 * 1024 + 1)
    payload = parse_hermes_session_start_payload(raw)
    result = record_hermes_session_start(
        managed_root,
        hermes_home,
        payload,
    )
    if args.hook_output:
        return 0
    return _emit(result, as_json=args.json)


def cmd_fleet_claude_launch(args: argparse.Namespace) -> int:
    """Launch Claude with the isolated Enterprise runtime configuration."""

    managed_root = _required_path(
        args.managed_root
        or os.environ.get("UNLIMITED_SKILLS_FLEET_MANAGED_ROOT", ""),
        "fleet_managed_root_required",
    )
    registration = load_registration()
    ClaudeCodeFleetAdapter(
        registration=registration,
        managed_root=managed_root,
        timeout=args.timeout,
    )
    requested = str(args.claude_executable or "claude").strip()
    executable = shutil.which(requested)
    if not executable:
        candidate = Path(requested).expanduser()
        if candidate.is_file():
            executable = str(candidate.resolve())
    if not executable:
        raise RuntimeError("claude_executable_not_found")
    environment = dict(os.environ)
    environment["CLAUDE_CONFIG_DIR"] = str(
        managed_claude_config_dir(managed_root)
    )
    environment["UNLIMITED_SKILLS_FLEET_MANAGED_ROOT"] = str(
        managed_root.expanduser().resolve()
    )
    claude_args = list(args.claude_args or [])
    if claude_args[:1] == ["--"]:
        claude_args = claude_args[1:]
    if args.dry_run:
        return _emit(
            {
                "schema_version": 1,
                "runtime_vendor": "claude-code",
                "configuration_ready": True,
                "executable_resolved": True,
                "managed_profile": True,
            },
            as_json=args.json,
        )
    completed = subprocess.run(
        [executable, *claude_args],
        env=environment,
        check=False,
    )
    return int(completed.returncode)


def cmd_fleet_codex_launch(args: argparse.Namespace) -> int:
    """Launch Codex with the isolated Enterprise home and workspace."""

    managed_root = _required_path(
        args.managed_root
        or os.environ.get("UNLIMITED_SKILLS_FLEET_MANAGED_ROOT", ""),
        "fleet_managed_root_required",
    )
    registration = load_registration()
    CodexFleetAdapter(
        registration=registration,
        managed_root=managed_root,
        timeout=args.timeout,
    )
    requested = str(args.codex_executable or "codex").strip()
    executable = shutil.which(requested)
    if not executable:
        candidate = Path(requested).expanduser()
        if candidate.is_file():
            executable = str(candidate.resolve())
    if not executable:
        raise RuntimeError("codex_executable_not_found")
    codex_args = list(args.codex_args or [])
    if codex_args[:1] == ["--"]:
        codex_args = codex_args[1:]
    if any(
        value in {"-C", "--cd"}
        or value.startswith("--cd=")
        for value in codex_args
    ):
        raise RuntimeError("codex_workspace_override_forbidden")
    environment = dict(os.environ)
    environment["CODEX_HOME"] = str(
        managed_codex_home(managed_root)
    )
    environment["UNLIMITED_SKILLS_FLEET_MANAGED_ROOT"] = str(
        managed_root.expanduser().resolve()
    )
    if args.dry_run:
        return _emit(
            {
                "schema_version": 1,
                "runtime_vendor": "codex",
                "configuration_ready": True,
                "executable_resolved": True,
                "managed_home": True,
                "managed_workspace": True,
                "hook_trust_required": True,
            },
            as_json=args.json,
        )
    completed = subprocess.run(
        [
            executable,
            "-C",
            str(managed_codex_workspace(managed_root)),
            *codex_args,
        ],
        env=environment,
        check=False,
    )
    return int(completed.returncode)


def cmd_fleet_hermes_launch(args: argparse.Namespace) -> int:
    """Launch Hermes with its Fleet plugin and managed skills tree."""

    managed_root = _required_path(
        args.managed_root
        or os.environ.get("UNLIMITED_SKILLS_FLEET_MANAGED_ROOT", ""),
        "fleet_managed_root_required",
    )
    hermes_home = _required_path(
        args.hermes_home
        or os.environ.get(
            "UNLIMITED_SKILLS_FLEET_HERMES_HOME",
            "",
        )
        or os.environ.get("HERMES_HOME", ""),
        "hermes_home_required",
    )
    registration = load_registration()
    adapter = HermesFleetAdapter(
        registration=registration,
        managed_root=managed_root,
        hermes_home=hermes_home,
        timeout=args.timeout,
    )
    executable = _resolve_executable(
        args.hermes_executable or "hermes",
        "hermes_executable_not_found",
    )
    hermes_args = list(args.hermes_args or [])
    if hermes_args[:1] == ["--"]:
        hermes_args = hermes_args[1:]
    environment = dict(os.environ)
    environment["HERMES_HOME"] = str(adapter.hermes_home)
    environment["UNLIMITED_SKILLS_FLEET_HERMES_HOME"] = str(
        adapter.hermes_home
    )
    environment["UNLIMITED_SKILLS_FLEET_MANAGED_ROOT"] = str(
        adapter.managed_root
    )
    if args.dry_run:
        return _emit(
            {
                "schema_version": 1,
                "runtime_vendor": "hermes",
                "configuration_ready": True,
                "executable_resolved": True,
                "managed_skills_tree": True,
                "runtime_plugin_provisioned": True,
            },
            as_json=args.json,
        )
    completed = subprocess.run(
        [executable, *hermes_args],
        env=environment,
        check=False,
    )
    return int(completed.returncode)


def _build_fleet_adapter(
    args: argparse.Namespace,
    *,
    registration,
    managed_root: Path,
):
    runtime_vendor = str(
        getattr(args, "runtime_vendor", "") or "claude-code"
    )
    if runtime_vendor == "claude-code":
        return ClaudeCodeFleetAdapter(
            registration=registration,
            managed_root=managed_root,
            timeout=args.timeout,
        )
    if runtime_vendor == "codex":
        user_skills_root = str(
            getattr(args, "codex_user_skills_root", "") or ""
        ).strip()
        return CodexFleetAdapter(
            registration=registration,
            managed_root=managed_root,
            user_skills_root=(
                Path(user_skills_root).expanduser()
                if user_skills_root
                else None
            ),
            timeout=args.timeout,
        )
    if runtime_vendor == "hermes":
        hermes_home = _required_path(
            getattr(args, "hermes_home", "")
            or os.environ.get(
                "UNLIMITED_SKILLS_FLEET_HERMES_HOME",
                "",
            )
            or os.environ.get("HERMES_HOME", ""),
            "hermes_home_required",
        )
        return HermesFleetAdapter(
            registration=registration,
            managed_root=managed_root,
            hermes_home=hermes_home,
            timeout=args.timeout,
        )
    if runtime_vendor == "openclaw":
        workspace = _required_path(
            getattr(args, "workspace", "")
            or os.environ.get(
                "UNLIMITED_SKILLS_FLEET_OPENCLAW_WORKSPACE",
                "",
            ),
            "openclaw_workspace_required",
        )
        openclaw_home = _required_path(
            getattr(args, "openclaw_home", "")
            or os.environ.get("OPENCLAW_STATE_DIR", "")
            or (Path.home() / ".openclaw"),
            "openclaw_home_required",
        )
        agent_id = str(
            getattr(args, "agent_id", "")
            or os.environ.get(
                "UNLIMITED_SKILLS_FLEET_OPENCLAW_AGENT_ID",
                "",
            )
        ).strip()
        if not agent_id:
            raise RuntimeError("openclaw_agent_id_required")
        return OpenClawFleetAdapter(
            registration=registration,
            managed_root=managed_root,
            workspace=workspace,
            agent_id=agent_id,
            openclaw_home=openclaw_home,
            timeout=args.timeout,
        )
    raise RuntimeError("fleet_runtime_vendor_unsupported")


def _resolve_executable(requested: str, reason: str) -> str:
    value = str(requested or "").strip()
    executable = shutil.which(value)
    if not executable:
        candidate = Path(value).expanduser()
        if candidate.is_file():
            executable = str(candidate.resolve())
    if not executable:
        raise RuntimeError(reason)
    return executable


def _openclaw_json(
    executable: str,
    arguments: list[str],
    *,
    environment: dict[str, str],
) -> dict | list:
    completed = subprocess.run(
        [executable, *arguments],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("openclaw_cli_failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("openclaw_cli_json_invalid") from exc
    if not isinstance(value, (dict, list)):
        raise RuntimeError("openclaw_cli_json_invalid")
    return value


def _hermes_plugins_json(
    executable: str,
    *,
    environment: dict[str, str],
) -> list[dict]:
    completed = subprocess.run(
        [executable, "plugins", "list", "--json"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("hermes_cli_failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("hermes_cli_json_invalid") from exc
    if not isinstance(value, list) or not all(
        isinstance(row, dict) for row in value
    ):
        raise RuntimeError("hermes_cli_json_invalid")
    return value


def cmd_fleet_hermes_provision(args: argparse.Namespace) -> int:
    """Provision and enable the Fleet lifecycle plugin for Hermes."""

    managed_root = _required_path(
        args.managed_root
        or os.environ.get("UNLIMITED_SKILLS_FLEET_MANAGED_ROOT", ""),
        "fleet_managed_root_required",
    )
    hermes_home = _required_path(
        args.hermes_home
        or os.environ.get(
            "UNLIMITED_SKILLS_FLEET_HERMES_HOME",
            "",
        )
        or os.environ.get("HERMES_HOME", ""),
        "hermes_home_required",
    )
    executable = _resolve_executable(
        args.hermes_executable or "hermes",
        "hermes_executable_not_found",
    )
    registration = load_registration()
    adapter = HermesFleetAdapter(
        registration=registration,
        managed_root=managed_root,
        hermes_home=hermes_home,
        timeout=args.timeout,
    )
    environment = dict(os.environ)
    environment["HERMES_HOME"] = str(adapter.hermes_home)
    enabled = subprocess.run(
        [executable, "plugins", "enable", "unlimited-skills-fleet"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if enabled.returncode != 0:
        raise RuntimeError("hermes_plugin_enable_failed")
    plugins = _hermes_plugins_json(
        executable,
        environment=environment,
    )
    match = next(
        (
            row
            for row in plugins
            if str(row.get("name") or "")
            == "unlimited-skills-fleet"
        ),
        None,
    )
    if match is None or str(match.get("status") or "") != "enabled":
        raise RuntimeError("hermes_plugin_not_enabled")
    return _emit(
        {
            "schema_version": 1,
            "runtime_vendor": "hermes",
            "adapter_version": adapter.adapter_version,
            "managed_skills_tree": True,
            "runtime_plugin_provisioned": True,
            "runtime_plugin_enabled": True,
        },
        as_json=args.json,
    )


def cmd_fleet_openclaw_provision(args: argparse.Namespace) -> int:
    """Bind and enable the Fleet hook for one configured OpenClaw agent."""

    managed_root = _required_path(
        args.managed_root
        or os.environ.get("UNLIMITED_SKILLS_FLEET_MANAGED_ROOT", ""),
        "fleet_managed_root_required",
    )
    workspace = _required_path(
        args.workspace
        or os.environ.get(
            "UNLIMITED_SKILLS_FLEET_OPENCLAW_WORKSPACE",
            "",
        ),
        "openclaw_workspace_required",
    ).resolve()
    openclaw_home = _required_path(
        args.openclaw_home
        or os.environ.get("OPENCLAW_STATE_DIR", "")
        or (Path.home() / ".openclaw"),
        "openclaw_home_required",
    ).resolve()
    agent_id = str(
        args.agent_id
        or os.environ.get(
            "UNLIMITED_SKILLS_FLEET_OPENCLAW_AGENT_ID",
            "",
        )
    ).strip()
    if not agent_id:
        raise RuntimeError("openclaw_agent_id_required")
    executable = _resolve_executable(
        args.openclaw_executable or "openclaw",
        "openclaw_executable_not_found",
    )
    environment = dict(os.environ)
    environment["OPENCLAW_STATE_DIR"] = str(openclaw_home)
    agents_value = _openclaw_json(
        executable,
        ["agents", "list", "--json"],
        environment=environment,
    )
    agents = (
        agents_value
        if isinstance(agents_value, list)
        else agents_value.get("agents", [])
    )
    match = next(
        (
            row
            for row in agents
            if isinstance(row, dict)
            and str(row.get("id") or row.get("agentId") or "")
            == agent_id
        ),
        None,
    )
    if match is None:
        raise RuntimeError("openclaw_agent_not_configured")
    configured_workspace = Path(
        str(match.get("workspace") or "")
    ).expanduser().resolve()
    if configured_workspace != workspace:
        raise RuntimeError("openclaw_workspace_mismatch")
    registration = load_registration()
    adapter = OpenClawFleetAdapter(
        registration=registration,
        managed_root=managed_root,
        workspace=workspace,
        agent_id=agent_id,
        openclaw_home=openclaw_home,
        timeout=args.timeout,
    )
    enabled = subprocess.run(
        [
            executable,
            "hooks",
            "enable",
            "unlimited-skills-fleet",
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if enabled.returncode != 0:
        raise RuntimeError("openclaw_hook_enable_failed")
    info = _openclaw_json(
        executable,
        [
            "hooks",
            "info",
            "unlimited-skills-fleet",
            "--json",
        ],
        environment=environment,
    )
    if (
        not isinstance(info, dict)
        or info.get("hookKey") != "unlimited-skills-fleet"
        or info.get("loadable") is not True
        or info.get("disabled") is True
    ):
        raise RuntimeError("openclaw_hook_not_loadable")
    return _emit(
        {
            "schema_version": 1,
            "runtime_vendor": "openclaw",
            "adapter_version": adapter.adapter_version,
            "agent_id": agent_id,
            "configured_agent_verified": True,
            "workspace_binding_verified": True,
            "hook_provisioned": True,
            "hook_enabled": True,
            "hook_loadable": True,
        },
        as_json=args.json,
    )


def cmd_fleet_run_once(args: argparse.Namespace) -> int:
    managed_root = _required_path(
        args.managed_root
        or os.environ.get("UNLIMITED_SKILLS_FLEET_MANAGED_ROOT", ""),
        "fleet_managed_root_required",
    )
    public_keys_path = _required_path(
        args.public_keys
        or os.environ.get("UNLIMITED_SKILLS_FLEET_PUBLIC_KEYS", ""),
        "fleet_public_keys_path_required",
    )
    registration = load_registration()
    adapter = _build_fleet_adapter(
        args,
        registration=registration,
        managed_root=managed_root,
    )
    runtime_vendor = str(
        getattr(args, "runtime_vendor", "") or "claude-code"
    )
    runtime_capability = {
        "claude-code": "claude-code-session-start-attestation-v1",
        "codex": "codex-session-start-attestation-v1",
        "hermes": "hermes-session-start-attestation-v1",
        "openclaw": "openclaw-agent-bootstrap-attestation-v1",
    }[runtime_vendor]
    client = FleetAgentClient(
        registration=registration,
        runtime_vendor=runtime_vendor,
        adapter=adapter,
        identity_store=FleetAgentIdentityStore(
            managed_root / "control" / "agent-identity.json"
        ),
        public_keys=load_fleet_public_keys(public_keys_path),
        reconcile_state_path=(
            managed_root / "control" / "reconcile-state.json"
        ),
        spool=ReceiptSpool(managed_root / "control" / "receipts"),
        client_version=__version__,
        reported_capabilities=(
            runtime_capability,
            FLEET_PAYLOAD_CAPABILITY,
            FLEET_CLIENT_VERSION_CAPABILITY,
            "desired-state-v1",
            "drift-detection-v1",
            "immutable-revisions-v1",
            "multi-pack-atomic-inventory-v1",
            "receipt-spool-v1",
            "rollback-v1",
            "runtime-attestation",
        ),
        organization_id=(
            args.organization_id
            or os.environ.get(
                "UNLIMITED_SKILLS_FLEET_ORGANIZATION_ID",
                "",
            )
        ),
        timeout=args.timeout,
        auto_activate=args.auto_activate,
    )
    result = client.run_once()
    reconcile = result.reconcile_result
    receipt_upload = result.receipt_upload
    payload = {
        "schema_version": 1,
        "runtime_vendor": runtime_vendor,
        "adapter_version": adapter.adapter_version,
        "agent_id": result.identity.agent_id,
        "local_instance_id": result.identity.local_instance_id,
        "desired_state_received": result.desired_state_received,
        "server_timestamp": result.server_timestamp,
        "reconcile": (
            {
                "rollout_id": reconcile.rollout_id,
                "desired_state_revision": (
                    reconcile.desired_state_revision
                ),
                "control_epoch": reconcile.control_epoch,
                "activation_pending": reconcile.activation_pending,
                "receipt_event_types": [
                    str(row["event_type"])
                    for row in reconcile.receipts
                ],
            }
            if reconcile is not None
            else None
        ),
        "receipt_upload": (
            {
                "batch_count": receipt_upload.batch_count,
                "accepted_count": receipt_upload.accepted_count,
                "duplicate_count": receipt_upload.duplicate_count,
                "pending_count": receipt_upload.pending_count,
                "outcome": receipt_upload.outcome,
            }
            if receipt_upload is not None
            else None
        ),
    }
    return _emit(payload, as_json=args.json)
