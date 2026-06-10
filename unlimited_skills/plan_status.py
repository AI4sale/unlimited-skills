from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hub_entitlements import entitlement_summary, refresh_entitlements
from .registration import RegistrationState, load_registration, redact_sensitive_text


DENIAL_REASONS = {
    "unregistered": "Register this installation to refresh hosted plan and entitlement state.",
    "no_entitlement": "The current plan does not include this feature.",
    "plan_limit_exceeded": "The current plan limit was exceeded.",
    "past_due": "The registered subscription is past due.",
    "suspended": "Hosted entitlements are suspended for this installation or scope.",
    "expired": "The registered subscription or entitlement expired.",
    "service_unavailable": "The hosted entitlement service is unavailable.",
    "policy_denied": "A local or enterprise policy denied this feature.",
    "unknown_feature": "The requested feature is not known by this client.",
}

DENIAL_ALIASES = {
    "no_private_pack_entitlement": "no_entitlement",
    "missing_entitlement": "no_entitlement",
    "registry_access_denied": "no_entitlement",
    "client_limit_reached": "plan_limit_exceeded",
    "max_clients_reached": "plan_limit_exceeded",
    "payment_failed": "past_due",
    "billing_past_due": "past_due",
    "subscription_past_due": "past_due",
    "past_due_subscription": "past_due",
    "subscription_expired": "expired",
    "entitlement_expired": "expired",
    "billing_expired": "expired",
    "canceled": "suspended",
    "cancelled": "suspended",
    "subscription_canceled": "suspended",
    "denied_by_policy": "policy_denied",
    "offline": "service_unavailable",
    "unreachable": "service_unavailable",
    "service_unreachable": "service_unavailable",
}

KNOWN_FEATURES = {
    "local_skill_hub",
    "private_team_packs",
    "team_sync",
    "team_sync_enabled",
    "enterprise_policy_sync",
    "admin_console",
    "release_channels",
    "max_hub_clients",
    "max_private_packs",
}


class PlanStatusError(RuntimeError):
    """Raised when plan status or refresh cannot be completed safely."""


def normalize_denial_reason(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = DENIAL_ALIASES.get(normalized, normalized)
    return normalized if normalized in DENIAL_REASONS else "policy_denied"


def redacted_plan_summary(*, state: RegistrationState | None = None, home: Path | None = None) -> dict[str, Any]:
    state = state or load_registration(home)
    summary = entitlement_summary(state, home)
    status = str(summary.get("status") or "")
    denial_reason = ""
    if not state.registered:
        denial_reason = "unregistered"
    elif status in {"past_due", "suspended", "expired"}:
        denial_reason = status
    elif status in {"canceled", "cancelled"}:
        denial_reason = "suspended"
    elif summary.get("offline_grace_status") == "expired":
        denial_reason = "suspended"
    payload = {
        "schema_version": 1,
        "registered": state.registered,
        "source": summary["source"],
        "plan": summary["plan"],
        "status": status or "active",
        "features_enabled": sorted(set(summary.get("features_enabled") or [])),
        "limits": _safe_limits(summary.get("limits")),
        "policy": _safe_policy(summary.get("policy")),
        "last_heartbeat_at": summary.get("last_heartbeat_at", ""),
        "offline_grace_status": summary.get("offline_grace_status", "none"),
        "denial_reason": denial_reason,
        "privacy": {
            "tokens_included": False,
            "proofs_included": False,
            "private_keys_included": False,
            "local_paths_included": False,
            "private_pack_bodies_included": False,
            "skill_names_included": False,
            "search_queries_included": False,
        },
    }
    assert_plan_output_safe(payload)
    return payload


def refresh_plan_status(*, timeout: float = 30.0, home: Path | None = None) -> dict[str, Any]:
    state = load_registration(home)
    if not state.registered:
        raise PlanStatusError(f"{DENIAL_REASONS['unregistered']} Denial reason: unregistered.")
    try:
        refreshed = refresh_entitlements(state, endpoint="entitlements", timeout=timeout, home=home)
    except Exception as exc:
        raise PlanStatusError(f"{DENIAL_REASONS['service_unavailable']} Denial reason: service_unavailable. {redact_sensitive_text(exc)}") from exc
    payload = {
        "schema_version": 1,
        "refreshed": True,
        "endpoint": refreshed["endpoint"],
        "plan_status": redacted_plan_summary(state=state, home=home),
    }
    assert_plan_output_safe(payload)
    return payload


def explain_feature(feature: str, *, home: Path | None = None) -> dict[str, Any]:
    requested = str(feature or "").strip().lower().replace("-", "_")
    state = load_registration(home)
    summary = redacted_plan_summary(state=state, home=home)
    if requested not in KNOWN_FEATURES:
        return _feature_payload(requested, False, "unknown_feature", summary)
    if not state.registered and requested not in {"local_skill_hub"}:
        return _feature_payload(requested, False, "unregistered", summary)
    if summary.get("status") in {"past_due", "suspended", "expired"}:
        return _feature_payload(requested, False, str(summary["status"]), summary)
    if summary.get("status") in {"canceled", "cancelled"}:
        return _feature_payload(requested, False, "suspended", summary)
    features = set(summary.get("features_enabled") or [])
    limits = summary.get("limits") if isinstance(summary.get("limits"), dict) else {}
    allowed = requested in features
    reason = ""
    if requested == "team_sync":
        allowed = "team_sync" in features or "team_sync_enabled" in features or bool(summary.get("policy", {}).get("team_sync_enabled"))
    elif requested == "max_hub_clients":
        allowed = int(limits.get("max_hub_clients") or 0) > 0
        reason = "" if allowed else "plan_limit_exceeded"
    elif requested == "max_private_packs":
        allowed = int(limits.get("max_private_packs") or 0) > 0
        reason = "" if allowed else "plan_limit_exceeded"
    elif requested == "release_channels":
        allowed = bool(limits.get("release_channels") or summary.get("policy", {}).get("release_channels"))
    if not allowed and not reason:
        reason = "no_entitlement"
    return _feature_payload(requested, allowed, reason, summary)


def doctor(*, home: Path | None = None) -> dict[str, Any]:
    state = load_registration(home)
    summary = redacted_plan_summary(state=state, home=home)
    checks = {
        "registration": {"ok": state.registered, "denial_reason": "" if state.registered else "unregistered"},
        "cached_entitlement": {"ok": summary["source"] != "unregistered", "source": summary["source"]},
        "plan_state": {"ok": summary["denial_reason"] not in {"past_due", "suspended", "expired"}, "status": summary["status"], "denial_reason": summary["denial_reason"]},
        "offline_grace": {"ok": summary["offline_grace_status"] in {"none", "active"}, "status": summary["offline_grace_status"]},
        "local_core": {"ok": True, "requires_registration": False},
    }
    payload = {
        "schema_version": 1,
        "ok": all(item["ok"] for item in checks.values()),
        "plan_status": summary,
        "checks": checks,
        "denial_vocabulary": sorted(DENIAL_REASONS),
    }
    assert_plan_output_safe(payload)
    return payload


def format_plan_status(payload: dict[str, Any]) -> str:
    lines = [
        "Registered: " + ("yes" if payload.get("registered") else "no"),
        f"Plan: {payload.get('plan') or 'community-core'}",
        f"Status: {payload.get('status') or 'active'}",
        f"Source: {payload.get('source') or 'unknown'}",
        "Offline grace: " + str(payload.get("offline_grace_status") or "none"),
    ]
    if payload.get("denial_reason"):
        lines.append("Denial reason: " + str(payload["denial_reason"]))
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    if limits:
        lines.append("Limits: " + ", ".join(f"{key}={value}" for key, value in sorted(limits.items())))
    features = payload.get("features_enabled") or []
    lines.append("Features: " + (", ".join(features) if features else "(none)"))
    return "\n".join(lines)


def _feature_payload(feature: str, allowed: bool, denial_reason: str, summary: dict[str, Any]) -> dict[str, Any]:
    denial_reason = normalize_denial_reason(denial_reason) if denial_reason else ""
    payload = {
        "schema_version": 1,
        "feature": feature,
        "allowed": allowed,
        "denial_reason": denial_reason,
        "message": "" if allowed else DENIAL_REASONS[denial_reason],
        "plan": summary["plan"],
        "status": summary["status"],
        "registered": summary["registered"],
    }
    assert_plan_output_safe(payload)
    return payload


def _safe_limits(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {}
    for key in ("max_hub_clients", "max_private_packs", "release_channels"):
        if key in value:
            allowed[key] = value[key]
    return allowed


def _safe_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {}
    for key in ("hub_distribution_mode", "signed_manifests_required", "hosted_query_forwarding_allowed", "team_sync_enabled"):
        if key in value:
            allowed[key] = value[key]
    return allowed


def assert_plan_output_safe(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    forbidden = [
        "authorization",
        "bearer ",
        "license_token",
        "device_private_key",
        '"private_key":',
        "x-uls-proof",
        "skill.md",
        "archive_url",
        "download_url",
        "c:\\",
        "/users/",
    ]
    for marker in forbidden:
        if marker in serialized:
            raise PlanStatusError(f"Plan diagnostic contains forbidden marker: {marker}")
