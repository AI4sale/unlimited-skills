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
    FleetAgentClient,
    FleetAgentIdentityStore,
    ReceiptSpool,
    load_fleet_public_keys,
    managed_claude_config_dir,
    parse_session_start_payload,
    record_claude_session_start,
)
from unlimited_skills.registration import load_registration


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
    adapter = ClaudeCodeFleetAdapter(
        registration=registration,
        managed_root=managed_root,
        timeout=args.timeout,
    )
    client = FleetAgentClient(
        registration=registration,
        runtime_vendor="claude-code",
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
            "claude-code-session-start-attestation-v1",
            "desired-state-v1",
            "drift-detection-v1",
            "immutable-revisions-v1",
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
        "runtime_vendor": "claude-code",
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
