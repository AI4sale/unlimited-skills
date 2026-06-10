from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .hub_allowlist import hub_dir
from .plan_status import DENIAL_REASONS, normalize_denial_reason, redacted_plan_summary
from .registration import RegistrationState, load_registration, post_json, redact_sensitive_text, write_private_json


BILLING_STATUS_NAME = "billing-status.json"
BILLING_STATUSES = {"unknown", "none", "trialing", "active", "past_due", "canceled", "cancelled", "suspended", "expired"}
BILLING_MODES = {"none", "sandbox_only", "external", "manual"}
FORBIDDEN_RESPONSE_KEYS = {
    "authorization",
    "bearer",
    "token",
    "tokens",
    "license_token",
    "device_private_key",
    "private_key",
    "x_uls_proof",
    "x-uls-proof",
    "checkout_url",
    "checkout_urls",
    "payment_link",
    "payment_links",
    "invoice_url",
    "invoice_urls",
    "card",
    "cards",
    "card_number",
    "cvv",
    "cvc",
    "bank",
    "bank_account",
    "email",
    "customer_email",
    "archive_url",
    "download_url",
    "skill_body",
    "skill_bodies",
    "skill_name",
    "skill_names",
    "local_path",
    "path",
}
BILLING_DENIALS = {
    **DENIAL_REASONS,
    "past_due": "The subscription is past due. Contact your admin or support.",
    "expired": "The subscription or entitlement expired. Contact your admin or support.",
}
STATUS_DENIAL = {
    "past_due": "past_due",
    "canceled": "suspended",
    "cancelled": "suspended",
    "suspended": "suspended",
    "expired": "expired",
}


class BillingStatusError(RuntimeError):
    """Raised when billing diagnostics cannot be loaded or refreshed safely."""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def billing_status_path(home: Path | None = None) -> Path:
    return hub_dir(home) / BILLING_STATUS_NAME


def load_billing_status(home: Path | None = None) -> dict[str, Any]:
    path = billing_status_path(home)
    if not path.is_file():
        return {
            "schema_version": 1,
            "source": "unregistered",
            "plan": "community-core",
            "entitlement_source": "local_core",
            "subscription_status": "none",
            "billing_mode": "none",
            "features_allowed": [],
            "features_denied": [],
            "denial_reason": "",
            "last_refreshed_at": "",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return normalize_billing_payload(payload if isinstance(payload, dict) else {}, source="cached")


def save_billing_status(payload: dict[str, Any], home: Path | None = None) -> Path:
    clean = normalize_billing_payload(payload, source=str(payload.get("source") or "cached"))
    assert_billing_output_safe(clean)
    return write_private_json(billing_status_path(home), clean)


def redacted_billing_summary(*, state: RegistrationState | None = None, home: Path | None = None) -> dict[str, Any]:
    state = state or load_registration(home)
    cached = load_billing_status(home)
    plan = redacted_plan_summary(state=state, home=home)
    status = str(cached.get("subscription_status") or "none")
    denial_reason = str(cached.get("denial_reason") or STATUS_DENIAL.get(status, ""))
    if not state.registered and status != "none":
        denial_reason = "unregistered"
    payload = {
        "schema_version": 1,
        "registered": state.registered,
        "source": cached.get("source", "cached") if state.registered else "unregistered",
        "plan": cached.get("plan") or plan.get("plan") or "community-core",
        "entitlement_source": cached.get("entitlement_source") or plan.get("source") or "unknown",
        "subscription_status": status if status in BILLING_STATUSES else "unknown",
        "billing_mode": str(cached.get("billing_mode") or "sandbox_only"),
        "features_allowed": _string_list(cached.get("features_allowed") or plan.get("features_enabled")),
        "features_denied": _feature_denials(cached.get("features_denied")),
        "denial_reason": normalize_billing_denial(denial_reason) if denial_reason else "",
        "last_refreshed_at": str(cached.get("last_refreshed_at") or ""),
        "next_action": _next_action(denial_reason, registered=state.registered),
        "privacy": {
            "tokens_included": False,
            "proofs_included": False,
            "private_keys_included": False,
            "payment_card_data_included": False,
            "checkout_urls_included": False,
            "local_paths_included": False,
            "private_pack_bodies_included": False,
            "private_skill_names_included": False,
        },
    }
    assert_billing_output_safe(payload)
    return payload


def refresh_billing_status(*, timeout: float = 30.0, home: Path | None = None) -> dict[str, Any]:
    state = load_registration(home)
    if not state.registered:
        raise BillingStatusError(f"{BILLING_DENIALS['unregistered']} Denial reason: unregistered.")
    request = {
        "schema_version": 1,
        "install_id": state.install_id,
        "client": {"name": "unlimited-skills"},
        "include_sensitive": False,
    }
    try:
        response = post_json(
            f"{state.server_url.rstrip('/')}/v1/hub/billing-status",
            request,
            token=state.license_token,
            proof_state=state,
            timeout=timeout,
            retry_safe=True,
        )
    except Exception as exc:
        raise BillingStatusError(f"{BILLING_DENIALS['service_unavailable']} Denial reason: service_unavailable. {redact_sensitive_text(exc)}") from exc
    cache = validate_billing_response(response)
    cache["source"] = "refreshed"
    cache["last_refreshed_at"] = now_iso()
    save_billing_status(cache, home)
    payload = {"schema_version": 1, "refreshed": True, "endpoint": "/v1/hub/billing-status", "billing_status": redacted_billing_summary(state=state, home=home)}
    assert_billing_output_safe(payload)
    return payload


def doctor(*, home: Path | None = None) -> dict[str, Any]:
    state = load_registration(home)
    summary = redacted_billing_summary(state=state, home=home)
    denial = summary.get("denial_reason") or ""
    checks = {
        "registration": {"ok": state.registered, "denial_reason": "" if state.registered else "unregistered"},
        "cached_billing_status": {"ok": summary["source"] != "unregistered", "source": summary["source"]},
        "subscription_status": {"ok": denial not in {"past_due", "suspended", "expired"}, "status": summary["subscription_status"], "denial_reason": denial},
        "local_core": {"ok": True, "requires_registration": False},
        "checkout": {"ok": True, "available": False, "live_provider_enabled": False},
    }
    payload = {"schema_version": 1, "ok": all(item["ok"] for item in checks.values()), "billing_status": summary, "checks": checks}
    assert_billing_output_safe(payload)
    return payload


def format_billing_status(payload: dict[str, Any]) -> str:
    lines = [
        "Registered: " + ("yes" if payload.get("registered") else "no"),
        f"Plan: {payload.get('plan') or 'community-core'}",
        f"Subscription: {payload.get('subscription_status') or 'none'}",
        f"Billing mode: {payload.get('billing_mode') or 'none'}",
        f"Source: {payload.get('source') or 'unknown'}",
    ]
    if payload.get("denial_reason"):
        lines.append("Denial reason: " + str(payload["denial_reason"]))
    if payload.get("next_action"):
        lines.append("Next action: " + str(payload["next_action"]))
    allowed = payload.get("features_allowed") or []
    lines.append("Allowed features: " + (", ".join(allowed) if allowed else "(none)"))
    denied = payload.get("features_denied") or []
    if denied:
        lines.append("Denied features: " + ", ".join(str(item.get("feature") or "") for item in denied if isinstance(item, dict)))
    return "\n".join(lines)


def normalize_billing_payload(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    status = str(payload.get("subscription_status") or payload.get("status") or "unknown").strip().lower()
    if status == "cancelled":
        status = "canceled"
    if status not in BILLING_STATUSES:
        status = "unknown"
    denial = str(payload.get("denial_reason") or STATUS_DENIAL.get(status, "")).strip()
    billing_mode = str(payload.get("billing_mode") or "sandbox_only").strip().lower()
    if billing_mode not in BILLING_MODES:
        billing_mode = "sandbox_only"
    return {
        "schema_version": 1,
        "source": source,
        "plan": str(payload.get("plan") or "registered-community"),
        "entitlement_source": str(payload.get("entitlement_source") or payload.get("source_scope") or "unknown"),
        "subscription_status": status,
        "billing_mode": billing_mode,
        "features_allowed": _string_list(payload.get("features_allowed") or payload.get("features_enabled")),
        "features_denied": _feature_denials(payload.get("features_denied") or payload.get("denied_features")),
        "denial_reason": normalize_billing_denial(denial) if denial else "",
        "last_refreshed_at": str(payload.get("last_refreshed_at") or ""),
    }


def validate_billing_response(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise BillingStatusError("Billing service returned a non-object response.")
    if response.get("schema_version") != 1:
        raise BillingStatusError("Billing service returned unsupported schema_version.")
    forbidden = _forbidden_response_paths(response)
    if forbidden:
        raise BillingStatusError("Billing service returned forbidden billing diagnostic fields: " + ", ".join(forbidden[:5]))
    normalized = normalize_billing_payload(response, source="refreshed")
    assert_billing_output_safe(normalized)
    return normalized


def normalize_billing_denial(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"canceled", "cancelled", "subscription_canceled"}:
        normalized = "suspended"
    if normalized in {"payment_failed", "billing_past_due", "subscription_past_due", "past_due_subscription"}:
        normalized = "past_due"
    if normalized in {"subscription_expired", "entitlement_expired", "billing_expired"}:
        normalized = "expired"
    if normalized in {"no_private_pack_entitlement", "missing_entitlement"}:
        normalized = "no_entitlement"
    if normalized in BILLING_DENIALS:
        return normalized
    return normalize_denial_reason(normalized)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item).strip() for item in value if str(item).strip() and "/" not in str(item)})


def _feature_denials(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            feature = str(item.get("feature") or "").strip()
            reason = normalize_billing_denial(str(item.get("denial_reason") or "no_entitlement"))
        else:
            feature = str(item).strip()
            reason = "no_entitlement"
        if feature and "/" not in feature:
            rows.append({"feature": feature, "denial_reason": reason})
    return sorted(rows, key=lambda row: row["feature"])


def _next_action(denial_reason: str, *, registered: bool) -> str:
    if not registered:
        return "Register this installation before refreshing hosted billing state."
    if denial_reason in {"past_due", "suspended", "expired"}:
        return "Contact your team admin or Unlimited Skills support."
    if denial_reason in {"no_entitlement", "plan_limit_exceeded"}:
        return "Ask your administrator to review plan entitlements."
    if denial_reason == "service_unavailable":
        return "Retry later or attach a support bundle."
    return ""


def _forbidden_response_paths(value: Any) -> list[str]:
    found: list[str] = []

    def walk(item: Any, path: str = "") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                key_text = str(key)
                normalized = key_text.lower().replace("-", "_").replace(" ", "_")
                child_path = f"{path}.{key_text}" if path else key_text
                if normalized in FORBIDDEN_RESPONSE_KEYS:
                    found.append(child_path)
                walk(child, child_path)
        elif isinstance(item, list):
            for idx, child in enumerate(item):
                walk(child, f"{path}[{idx}]")

    walk(value)
    return sorted(set(found))


def assert_billing_output_safe(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    forbidden = [
        "authorization",
        "bearer ",
        "license_token",
        "device_private_key",
        '"private_key":',
        "x-uls-proof",
        "card_number",
        '"card":',
        "cvv",
        "cvc",
        '"checkout_url":',
        '"payment_link":',
        '"invoice_url":',
        '"bank":',
        '"bank_account":',
        "skill.md",
        "archive_url",
        "download_url",
        "c:\\",
        "/users/",
    ]
    for marker in forbidden:
        if marker in serialized:
            raise BillingStatusError(f"Billing diagnostic contains forbidden marker: {marker}")
