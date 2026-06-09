from __future__ import annotations

import urllib.parse
from pathlib import Path
from typing import Any

from .policy import PolicyError, load_policy, normalize_origin, write_policy_audit
from .registration import redact_sensitive_text


class PolicyViolation(PolicyError):
    """Raised when Enterprise Skill Lock blocks an action."""


def active_policy(home: Path | None = None) -> dict[str, Any]:
    policy = load_policy(home)
    return policy if policy.get("locked") else {}


def _violation(action: str, reason: str, remediation: str, details: dict[str, Any] | None = None, *, home: Path | None = None) -> None:
    policy = active_policy(home)
    if not policy:
        return
    event = {
        "schema_version": 1,
        "event": "enterprise_skill_lock_refusal",
        "policy_id": policy.get("policy_id"),
        "mode": policy.get("mode"),
        "action": action,
        "reason": reason,
        "details": details or {},
        "remediation": remediation,
    }
    if (policy.get("audit") or {}).get("log_refusals", True):
        write_policy_audit(event, home=home)
    if policy.get("mode") == "audit":
        return
    message = (
        "This instance is managed by Enterprise Skill Lock. "
        f"Action blocked: {action}. Reason: {reason}. "
        f"Remediation: {remediation}"
    )
    raise PolicyViolation(redact_sensitive_text(message))


def enforce_registry_url(url: str, *, action: str = "registry access", home: Path | None = None) -> None:
    policy = active_policy(home)
    if not policy:
        return
    allowed = set(policy.get("allowed_registries") or [])
    if not allowed:
        return
    origin = normalize_origin(url)
    if origin not in allowed:
        _violation(
            action,
            f"registry origin {origin or '(unknown)'} is not approved by policy",
            "Ask your corporate Unlimited Skills administrator to publish through an approved enterprise registry.",
            {"origin": origin, "allowed_registries": sorted(allowed)},
            home=home,
        )


def enforce_release_channel(channel: str, *, action: str = "release channel", home: Path | None = None) -> None:
    policy = active_policy(home)
    if not policy:
        return
    allowed = set(str(item) for item in policy.get("allowed_release_channels") or [])
    if allowed and channel not in allowed:
        _violation(
            action,
            f"release channel {channel} is not approved by policy",
            "Use an approved release channel or request an enterprise policy update.",
            {"channel": channel, "allowed_release_channels": sorted(allowed)},
            home=home,
        )


def enforce_manifest_signature_present(has_signature: bool, *, purpose: str, home: Path | None = None) -> None:
    policy = active_policy(home)
    if not policy or not policy.get("required_manifest_signatures", False):
        return
    if not has_signature:
        _violation(
            purpose,
            "manifest is unsigned but policy requires signed manifests",
            "Use a signed manifest from an approved enterprise registry or administrator.",
            {"purpose": purpose},
            home=home,
        )


def enforce_manifest_key(key_id: str, *, scope: str = "", registry_url: str = "", purpose: str = "manifest verification", home: Path | None = None) -> None:
    policy = active_policy(home)
    if not policy:
        return
    allowed_ids = set(str(item) for item in policy.get("allowed_key_ids") or [])
    allowed_scopes = set(str(item) for item in policy.get("allowed_key_scopes") or [])
    if allowed_ids and key_id not in allowed_ids:
        _violation(
            purpose,
            f"manifest key {key_id or '(missing)'} is not approved by policy",
            "Ask your corporate Unlimited Skills administrator to rotate trust or publish through an approved key.",
            {"key_id": key_id, "scope": scope, "registry_origin": normalize_origin(registry_url)},
            home=home,
        )
    if allowed_scopes and scope and scope not in allowed_scopes:
        _violation(
            purpose,
            f"manifest scope {scope} is not approved by policy",
            "Use a policy-approved manifest scope or request an enterprise policy update.",
            {"key_id": key_id, "scope": scope, "allowed_key_scopes": sorted(allowed_scopes)},
            home=home,
        )


def enforce_community_install(*, home: Path | None = None) -> None:
    policy = active_policy(home)
    if policy and not (policy.get("community") or {}).get("install_allowed", True):
        _violation(
            "community install",
            "community installs are denied by policy",
            "Ask your corporate Unlimited Skills administrator to publish the skill through an approved registry.",
            home=home,
        )


def enforce_community_submit(*, home: Path | None = None) -> None:
    policy = active_policy(home)
    if policy and not (policy.get("community") or {}).get("submit_allowed", True):
        _violation(
            "community submit",
            "community submissions are denied by policy",
            "Use the corporate skill publication workflow.",
            home=home,
        )


def enforce_local_allowlist_signed(allowlist: dict[str, Any], *, home: Path | None = None) -> None:
    policy = active_policy(home)
    if not policy:
        return
    if (policy.get("hub") or {}).get("unsigned_local_allowlist_allowed", True):
        return
    has_signature = bool(allowlist.get("manifest_signature") or allowlist.get("signature_envelope"))
    if not has_signature:
        _violation(
            "hub init allowlist",
            "unsigned local allowlists are denied by policy",
            "Use a signed allowlist from an approved enterprise registry or administrator.",
            home=home,
        )


def enforce_remote_fallback_allowed(*, home: Path | None = None) -> None:
    policy = active_policy(home)
    if not policy:
        return
    hub = policy.get("hub") or {}
    if hub.get("remote_required") and not hub.get("local_fallback_allowed", True):
        _violation(
            "remote hub fallback",
            "local fallback is denied because remote hub is required by policy",
            "Connect to the corporate Local Skill Hub or contact your administrator.",
            home=home,
        )


def enforce_local_root(root: Path, *, action: str = "local library root", home: Path | None = None) -> None:
    policy = active_policy(home)
    if not policy:
        return
    allowed = [Path(item).expanduser().resolve() for item in policy.get("allowed_local_roots") or []]
    if not allowed:
        return
    resolved = root.expanduser().resolve()
    if not any(resolved == allowed_root or allowed_root in resolved.parents for allowed_root in allowed):
        _violation(
            action,
            "local library root is not approved by policy",
            "Use an approved local library root or request an enterprise policy update.",
            {"root": str(resolved)},
            home=home,
        )
