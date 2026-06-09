from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import __version__
from .policy import (
    PolicyError,
    install_policy_payload,
    load_policy,
    policy_dir,
    policy_summary,
    remove_policy,
    verify_policy_payload,
    write_policy_audit,
)
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


def managed_policy_remove_check(*, home: Path | None = None) -> dict[str, Any]:
    state = load_managed_policy_state(home)
    installed = policy_summary(load_policy(home))
    installed_policy_id = str(installed.get("policy_id") or "")
    installed_policy_sha256 = str(installed.get("policy_sha256") or "")
    state_policy_id = str(state.get("policy_id") or "")
    state_policy_sha256 = str(state.get("policy_sha256") or "")

    if not installed.get("installed"):
        return {
            "schema_version": 1,
            "allowed": True,
            "reason": "no_installed_policy",
            "installed_policy": installed,
            "managed_state": state,
        }
    allowed = (
        bool(state.get("managed"))
        and state_policy_id
        and state_policy_sha256
        and state_policy_id == installed_policy_id
        and state_policy_sha256 == installed_policy_sha256
    )
    return {
        "schema_version": 1,
        "allowed": allowed,
        "reason": "managed_policy_match" if allowed else "installed_policy_not_managed",
        "installed_policy": installed,
        "managed_state": state,
    }


def _write_remove_refusal_audit(check: dict[str, Any], *, home: Path | None = None) -> None:
    installed = check.get("installed_policy") if isinstance(check.get("installed_policy"), dict) else {}
    state = check.get("managed_state") if isinstance(check.get("managed_state"), dict) else {}
    write_policy_audit(
        {
            "event_type": "managed_policy_remove_refused",
            "reason": check.get("reason") or "installed_policy_not_managed",
            "redacted": True,
            "installed_policy_id": installed.get("policy_id") or "",
            "managed_policy_id": state.get("policy_id") or "",
            "assignment_id": state.get("assignment_id") or "",
        },
        home=home,
    )


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
        installed: dict[str, Any] = {}
        if not dry_run:
            installed = install_policy_payload(policy, home=home, source=f"managed-sync:{assignment['assignment_id']}")
            path = str(installed.get("path") or "")
            changed = True
            installed_summary = policy_summary(load_policy(home))
            policy_id = str(installed_summary.get("policy_id") or "")
            policy_sha256 = str(installed_summary.get("policy_sha256") or "")
        else:
            policy_id = str((policy or {}).get("policy_id") or "")
            policy_sha256 = str(assignment.get("policy_verification", {}).get("policy_sha256") or installed.get("policy_sha256") or "")
        remove_check: dict[str, Any] | None = None
    elif action == "remove":
        remove_check = managed_policy_remove_check(home=home)
        policy_id = str(remove_check.get("installed_policy", {}).get("policy_id") or "")
        policy_sha256 = str(remove_check.get("installed_policy", {}).get("policy_sha256") or "")
        if remove_check["allowed"]:
            if not dry_run:
                removed = remove_policy(yes=True, home=home)
                path = str(removed.get("path") or "")
                changed = bool(removed.get("removed"))
        else:
            if not dry_run:
                _write_remove_refusal_audit(remove_check, home=home)
            changed = False
            path = ""
    else:
        path = str(policy_dir(home) / "enterprise-skill-lock-policy.json")
        policy_id = ""
        policy_sha256 = ""
        remove_check = None

    if action in {"install", "update"}:
        managed = True
    elif action == "remove":
        managed = False
    else:
        managed = bool(load_managed_policy_state(home).get("managed"))

    state_payload = {
        "schema_version": 1,
        "managed": managed,
        "last_sync_at": now_iso(),
        "server_url": resolved.server_url,
        "install_id": resolved.install_id,
        "action": action,
        "assignment_id": assignment["assignment_id"],
        "assigned_at": assignment["assigned_at"],
        "dry_run": dry_run,
        "changed": changed,
        "policy_id": policy_id,
        "policy_sha256": policy_sha256,
        "installed_by": "managed-sync" if managed else "",
        "signature_verification": assignment["signature_verification"],
        "path": path,
    }
    if action == "remove":
        state_payload["remove_allowed"] = bool(remove_check and remove_check.get("allowed"))
        state_payload["removal_refused"] = not state_payload["remove_allowed"]
        state_payload["refusal_reason"] = "" if state_payload["remove_allowed"] else str(remove_check.get("reason") or "installed_policy_not_managed")
        if state_payload["removal_refused"]:
            state_payload["message"] = "Registry requested managed policy removal, but the installed policy is not managed by registry sync."
    if not dry_run:
        save_managed_policy_state(state_payload, home=home)
    return {"schema_version": 1, "dry_run": dry_run, "changed": changed, "assignment": assignment, "managed_state": state_payload}
