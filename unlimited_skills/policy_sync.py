from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import __version__
from .policy import PolicyError, install_policy_payload, load_policy, policy_dir, policy_summary, remove_policy, verify_policy_payload
from .registration import RegistrationError, RegistrationState, load_registration, post_json, unlimited_skills_home, write_private_json
from .signatures import ManifestSignatureError, verify_manifest_signature


MANAGED_POLICY_STATE = "managed-policy-state.json"


class PolicySyncError(RuntimeError):
    """Raised when managed Enterprise Skill Lock policy sync cannot complete."""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def managed_policy_state_path(home: Path | None = None) -> Path:
    return policy_dir(home) / MANAGED_POLICY_STATE


def load_managed_policy_state(home: Path | None = None) -> dict[str, Any]:
    path = managed_policy_state_path(home)
    if not path.is_file():
        return {"schema_version": 1, "managed": False, "last_sync_at": "", "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicySyncError("Cannot read managed policy sync state.") from exc
    if not isinstance(payload, dict):
        raise PolicySyncError("Managed policy sync state must be a JSON object.")
    payload.setdefault("schema_version", 1)
    payload.setdefault("managed", False)
    payload.setdefault("path", str(path))
    return payload


def save_managed_policy_state(payload: dict[str, Any], *, home: Path | None = None) -> Path:
    payload = dict(payload)
    payload["schema_version"] = 1
    return write_private_json(managed_policy_state_path(home), payload)


def managed_policy_status(*, home: Path | None = None) -> dict[str, Any]:
    state = load_managed_policy_state(home)
    installed = policy_summary(load_policy(home))
    return {"schema_version": 1, "managed_state": state, "installed_policy": installed}


def ensure_registered(state: RegistrationState | None = None, *, home: Path | None = None) -> RegistrationState:
    resolved = state or load_registration(home)
    if not resolved.registered:
        raise PolicySyncError("Managed policy sync requires registration. Local policy status/verify/install/remove still work offline.")
    return resolved


def parse_assignment(response: dict[str, Any], *, state: RegistrationState) -> dict[str, Any]:
    try:
        signature_verification = verify_manifest_signature(
            response,
            purpose="Enterprise Skill Lock policy assignment",
            required=True,
            scope="enterprise-policy",
            registry_url=state.server_url,
        )
    except ManifestSignatureError as exc:
        raise PolicySyncError(str(exc)) from exc
    action = str(response.get("action") or "none").lower()
    if action not in {"none", "install", "update", "remove"}:
        raise PolicySyncError("Policy sync action must be none, install, update, or remove.")
    policy = response.get("policy")
    if action in {"install", "update"}:
        if not isinstance(policy, dict):
            raise PolicySyncError("Policy sync install/update response must include a policy object.")
        try:
            verification = verify_policy_payload(policy)
        except PolicyError as exc:
            raise PolicySyncError(str(exc)) from exc
    else:
        verification = {"valid": False, "reason": "no_policy_payload"}
        policy = None
    return {
        "schema_version": 1,
        "action": action,
        "assignment_id": str(response.get("assignment_id") or ""),
        "assigned_at": str(response.get("assigned_at") or ""),
        "policy": policy,
        "policy_verification": verification,
        "signature_verification": signature_verification,
    }


def fetch_policy_assignment(state: RegistrationState, *, home: Path | None = None, timeout: float = 30.0) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "install_id": state.install_id,
        "client": {"name": "unlimited-skills", "version": __version__},
        "current_policy": policy_summary(load_policy(home)),
    }
    try:
        response = post_json(
            f"{state.server_url.rstrip('/')}/v1/policy/sync",
            payload,
            token=state.license_token,
            proof_state=state,
            timeout=timeout,
            retry_safe=True,
        )
    except RegistrationError as exc:
        raise PolicySyncError(str(exc)) from exc
    return parse_assignment(response, state=state)


def sync_managed_policy(
    *,
    root: Path | None = None,
    home: Path | None = None,
    state: RegistrationState | None = None,
    dry_run: bool = False,
    timeout: float = 30.0,
) -> dict[str, Any]:
    _ = root
    resolved = ensure_registered(state, home=home)
    assignment = fetch_policy_assignment(resolved, home=home, timeout=timeout)
    action = assignment["action"]
    changed = False
    path = ""
    if action in {"install", "update"}:
        policy = assignment["policy"]
        if not isinstance(policy, dict):
            raise PolicySyncError("Policy assignment did not include policy payload.")
        if not dry_run:
            installed = install_policy_payload(policy, home=home, source=f"managed-sync:{assignment['assignment_id']}")
            path = str(installed.get("path") or "")
            changed = True
    elif action == "remove":
        if not dry_run:
            removed = remove_policy(yes=True, home=home)
            path = str(removed.get("path") or "")
            changed = bool(removed.get("removed"))
    else:
        path = str(policy_dir(home) / "enterprise-skill-lock-policy.json")

    state_payload = {
        "schema_version": 1,
        "managed": action in {"install", "update"},
        "last_sync_at": now_iso(),
        "server_url": resolved.server_url,
        "install_id": resolved.install_id,
        "action": action,
        "assignment_id": assignment["assignment_id"],
        "assigned_at": assignment["assigned_at"],
        "dry_run": dry_run,
        "changed": changed,
        "policy_id": str((assignment.get("policy") or {}).get("policy_id") or ""),
        "signature_verification": assignment["signature_verification"],
        "path": path,
    }
    if not dry_run:
        save_managed_policy_state(state_payload, home=home)
    return {"schema_version": 1, "dry_run": dry_run, "changed": changed, "assignment": assignment, "managed_state": state_payload}
