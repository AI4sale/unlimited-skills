from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import __version__
from .doctor import build_doctor_report
from .hub import active_hub_token_count, cached_allowlist_summary, load_hub_config, load_remote_config
from .policy import load_policy, policy_summary
from .policy_sync import managed_policy_status
from .registration import DEFAULT_SERVICE_URL, RegistrationError, load_registration, redacted_status, redact_sensitive_text, unlimited_skills_home
from .service_diagnostics import load_service_config, local_status as service_local_status, local_trust_status


SETUP_MODES = {"overview", "local-only", "registered", "hub", "enterprise"}


def _step(name: str, status: str, message: str, *, next_commands: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "next_commands": next_commands or [],
    }


def _library_status(root: Path, *, dry_run: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = root.expanduser()
    local_skills = root / "local" / "skills"
    existed = root.exists()
    if not dry_run:
        local_skills.mkdir(parents=True, exist_ok=True)
    status = {
        "root": str(root),
        "exists": root.exists() or existed,
        "local_skills_exists": local_skills.exists() or (not dry_run),
        "index_present": (root / ".unlimited-skills-index.json").is_file(),
        "created": bool(not dry_run and not existed),
    }
    steps = [
        _step(
            "local_library",
            "ok" if status["exists"] or status["created"] else "needs_action",
            "Local library root is ready." if status["exists"] or status["created"] else "Local library root is missing.",
            next_commands=[f"unlimited-skills --root {root} reindex --no-native-sync"],
        ),
        _step(
            "local_search",
            "ok" if status["index_present"] else "needs_action",
            "Lexical index is present." if status["index_present"] else "Lexical index is missing or not yet built.",
            next_commands=[f"unlimited-skills --root {root} search \"your task\" --mode hybrid --limit 8 --no-native-sync"],
        ),
    ]
    return status, steps


def _registration_status(home: Path | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        state = load_registration(home)
        status = redacted_status(state)
    except RegistrationError:
        status = {
            "registered": False,
            "install_id": "",
            "server_url": DEFAULT_SERVICE_URL,
            "plan": "community-core",
            "license_token": False,
            "device_key": "",
            "telemetry": "off",
            "proof_required": True,
        }
    registered = bool(status.get("registered"))
    steps = [
        _step(
            "registration",
            "ok" if registered else "blocked",
            "Registered hosted features are available." if registered else "Registration is required for hosted catalog, updates, team sync, and managed policy sync. The MIT local core remains available without registration.",
            next_commands=[
                "unlimited-skills service test-registration --dry-run --agent codex",
                "unlimited-skills register --agent codex",
            ],
        )
    ]
    return status, steps


def _service_status(home: Path | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        status = service_local_status(refresh=False, home=home)
    except Exception as exc:  # noqa: BLE001 - setup should report a next action, not crash on local config issues.
        status = {"ok": False, "error": redact_sensitive_text(str(exc)), "service_url": DEFAULT_SERVICE_URL}
    registration = status.get("registration") if isinstance(status.get("registration"), dict) else {}
    trust = status.get("trust") if isinstance(status.get("trust"), dict) else {}
    service_config = load_service_config(home)
    steps = [
        _step(
            "service_config",
            "ok" if service_config else "needs_action",
            "Hosted service URL is configured." if service_config else "Hosted service URL uses default configuration until explicitly configured.",
            next_commands=["unlimited-skills service configure https://unlimited.ai4.sale"],
        ),
        _step(
            "trust",
            "ok" if int(trust.get("compatible_key_count") or 0) > 0 else "needs_action",
            "Compatible trusted manifest keys are available." if int(trust.get("compatible_key_count") or 0) > 0 else "Trusted manifest keys are missing or not compatible with the configured service.",
            next_commands=["unlimited-skills trust status", "unlimited-skills service verify-trust"],
        ),
        _step(
            "device_proof",
            "ok" if registration.get("device_key") == "present" or registration.get("device_key") else "needs_action",
            "Device proof key is present." if registration.get("device_key") == "present" or registration.get("device_key") else "Device proof key is missing until registration creates local device identity.",
            next_commands=["unlimited-skills service test-proof"],
        ),
    ]
    return status, steps


def _hub_status(home: Path | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = load_hub_config(home)
    remote = load_remote_config(home)
    allowlist = cached_allowlist_summary(home)
    token_count = active_hub_token_count(home)
    status = {
        "hub_id": config.get("hub_id"),
        "distribution_mode": config.get("distribution_mode"),
        "active_client_limit": config.get("active_client_limit"),
        "active_token_count": token_count,
        "allowlist": allowlist,
        "remote": remote,
    }
    steps = [
        _step(
            "hub_allowlist",
            "ok" if allowlist.get("configured") else "needs_action",
            "Cached Local Skill Hub allowlist is configured." if allowlist.get("configured") else "Local Skill Hub allowlist is not configured.",
            next_commands=["unlimited-skills hub init --allowlist <allowlist.v1.json>", "unlimited-skills hub sync --dry-run --json"],
        ),
        _step(
            "hub_token",
            "ok" if token_count > 0 else "needs_action",
            "At least one active hub client token exists." if token_count > 0 else "No active hub client token exists.",
            next_commands=["unlimited-skills hub token create --label default --json"],
        ),
        _step(
            "remote_config",
            "ok" if remote.get("configured") else "needs_action",
            "Remote hub client is configured." if remote.get("configured") else "Remote hub client is not configured.",
            next_commands=["unlimited-skills remote configure --url http://127.0.0.1:8766 --token-env ULS_HUB_TOKEN"],
        ),
    ]
    return status, steps


def _enterprise_status(home: Path | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    policy = policy_summary(load_policy(home))
    managed = managed_policy_status(home=home)
    installed = bool(policy.get("installed"))
    status = {
        "policy": policy,
        "managed_policy": managed,
    }
    steps = [
        _step(
            "enterprise_policy",
            "ok" if installed else "optional",
            "Enterprise Skill Lock policy is installed." if installed else "Enterprise Skill Lock is not installed. Community Core behavior is unchanged.",
            next_commands=["unlimited-skills policy status", "unlimited-skills policy explain"],
        ),
        _step(
            "managed_policy_sync",
            "ok" if managed.get("managed_state", {}).get("managed") else "optional",
            "Managed Enterprise policy sync state is present." if managed.get("managed_state", {}).get("managed") else "Managed Enterprise policy sync is not active.",
            next_commands=["unlimited-skills policy managed-status --json", "unlimited-skills policy sync --dry-run --json"],
        ),
    ]
    return status, steps


def build_setup_report(root: Path, *, mode: str = "overview", dry_run: bool = False, agent: str = "all") -> dict[str, Any]:
    if mode not in SETUP_MODES:
        raise ValueError(f"Unsupported setup mode: {mode}")
    root = root.expanduser()
    home = unlimited_skills_home()
    components: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []

    library_write_allowed = mode == "local-only" and not dry_run
    library, library_steps = _library_status(root, dry_run=not library_write_allowed)
    components["library"] = library
    steps.extend(library_steps)

    if mode in {"overview", "registered", "hub"}:
        registration, registration_steps = _registration_status(home)
        service, service_steps = _service_status(home)
        components["registration"] = registration
        components["service"] = service
        steps.extend(registration_steps)
        steps.extend(service_steps)

    if mode in {"overview", "hub"}:
        hub, hub_steps = _hub_status(home)
        components["hub"] = hub
        steps.extend(hub_steps)

    if mode in {"overview", "enterprise"}:
        enterprise, enterprise_steps = _enterprise_status(home)
        components["enterprise"] = enterprise
        steps.extend(enterprise_steps)

    if mode == "overview":
        components["doctor"] = build_doctor_report(root, agent=agent)

    blocked = [step for step in steps if step["status"] == "blocked"]
    needs_action = [step for step in steps if step["status"] == "needs_action"]
    next_commands: list[str] = []
    for step in steps:
        for command in step["next_commands"]:
            if command not in next_commands:
                next_commands.append(command)
    payload = {
        "schema_version": 1,
        "client": {"name": "unlimited-skills", "version": __version__},
        "mode": mode,
        "dry_run": dry_run,
        "writes_performed": bool(library_write_allowed and library.get("created")),
        "hosted_calls_performed": False,
        "destructive_changes": False,
        "root": str(root),
        "summary": {
            "status": "blocked" if blocked else ("needs_action" if needs_action else "ok"),
            "blocked_count": len(blocked),
            "needs_action_count": len(needs_action),
        },
        "components": components,
        "steps": steps,
        "next_commands": next_commands,
        "privacy": {
            "tokens_redacted": True,
            "private_keys_redacted": True,
            "hosted_calls_performed": False,
            "telemetry_collected": False,
        },
    }
    return payload


def format_setup_text(payload: dict[str, Any]) -> str:
    lines = [
        "Unlimited Skills setup",
        f"Mode: {payload['mode']}",
        f"Status: {payload['summary']['status']}",
        f"Root: {payload['root']}",
        "Hosted calls: none",
        "Destructive changes: no",
        "",
        "Steps:",
    ]
    for step in payload["steps"]:
        lines.append(f"- {step['name']}: {step['status']} - {step['message']}")
    if payload["next_commands"]:
        lines.extend(["", "Next commands:"])
        lines.extend(f"- {command}" for command in payload["next_commands"])
    return "\n".join(lines)
