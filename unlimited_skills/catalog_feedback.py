from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .registration import RegistrationError, RegistrationState, post_json
from .updates import RegistrationRequired


CATALOG_FEEDBACK_REQUIRED_MESSAGE = (
    "Registration is required for hosted catalog feedback. "
    "Local learning-loop feedback remains available through: unlimited-skills feedback"
)
FEEDBACK_TYPES = {
    "install_failure",
    "compatibility_issue",
    "missing_capability",
    "documentation_issue",
    "security_concern",
}
SEVERITIES = {"low", "medium", "high", "critical"}
DETAIL_ALLOWED_KEYS = {
    "agent",
    "client_version",
    "core_version",
    "os",
    "command",
    "error_code",
    "http_status",
    "expected_behavior",
    "actual_behavior",
    "reproduction_hint",
}
ITEM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
FORBIDDEN_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE|OPENSSH) KEY-----", re.IGNORECASE),
    "hosted_token": re.compile(r"\b(?:uls_(?:hub|token|license)_[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b"),
    "windows_path": re.compile(r"\b[A-Za-z]:[\\/][^\s]+"),
    "unix_home_path": re.compile(r"(?<![\w-])/(?:home|Users|root)/[^\s]+"),
    "repo_path": re.compile(r"\b(?:\.git|node_modules|site-packages)[\\/]", re.IGNORECASE),
    "prompt_or_body_field": re.compile(r'"(?:prompt|prompts|skill_body|skill_bodies)"\s*:', re.IGNORECASE),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
}


class CatalogFeedbackError(RuntimeError):
    """Raised when catalog feedback cannot be prepared or submitted safely."""


class CatalogFeedbackRegistrationRequired(RegistrationRequired):
    """Raised when catalog feedback is requested without registration."""


@dataclass(frozen=True)
class CatalogFeedbackPayload:
    item_id: str
    feedback_type: str
    severity: str = "medium"
    title: str = ""
    detail: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "item_id": self.item_id,
            "feedback_type": self.feedback_type,
            "severity": self.severity,
        }
        if self.title:
            payload["title"] = self.title
        if self.detail:
            payload["detail"] = self.detail
        return payload


def build_feedback_payload(
    *,
    item_id: str,
    feedback_type: str,
    severity: str = "medium",
    title: str = "",
    detail: dict[str, Any] | None = None,
) -> CatalogFeedbackPayload:
    clean_item_id = _safe_item_id(item_id)
    clean_type = feedback_type.strip()
    if clean_type not in FEEDBACK_TYPES:
        raise CatalogFeedbackError("Unsupported catalog feedback type.")
    clean_severity = (severity or "medium").strip()
    if clean_severity not in SEVERITIES:
        raise CatalogFeedbackError("Unsupported catalog feedback severity.")
    return CatalogFeedbackPayload(
        item_id=clean_item_id,
        feedback_type=clean_type,
        severity=clean_severity,
        title=_safe_text(title, "title", max_len=160) if title else "",
        detail=sanitize_feedback_detail(detail or {}),
    )


def sanitize_feedback_detail(detail: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in detail.items():
        safe_key = str(key)
        if safe_key not in DETAIL_ALLOWED_KEYS:
            continue
        if isinstance(value, bool):
            sanitized[safe_key] = value
        elif isinstance(value, int):
            sanitized[safe_key] = value
        else:
            sanitized[safe_key] = _safe_text(str(value), safe_key, max_len=2000)
    return sanitized


def redacted_catalog_feedback_summary() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "registered_operation": True,
        "explicit_feedback_only": True,
        "automatic_telemetry": False,
        "raw_feedback_included": False,
        "prompts_included": False,
        "skill_bodies_included": False,
        "local_paths_included": False,
        "tokens_included": False,
        "proofs_included": False,
        "private_keys_included": False,
    }


class CatalogFeedbackClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0) -> None:
        if not state.registered:
            raise CatalogFeedbackRegistrationRequired(CATALOG_FEEDBACK_REQUIRED_MESSAGE)
        self.state = state
        self.timeout = timeout

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return post_json(
                f"{self.state.server_url.rstrip('/')}{endpoint}",
                payload,
                token=self.state.license_token,
                proof_state=self.state,
                timeout=self.timeout,
            )
        except RegistrationError as exc:
            raise CatalogFeedbackError(str(exc)) from exc

    def submit(self, payload: CatalogFeedbackPayload) -> dict[str, Any]:
        return self._post("/v1/catalog/feedback/submit", payload.to_json())

    def status(self, item_id: str, *, limit: int = 100) -> dict[str, Any]:
        return self._post("/v1/catalog/feedback/summary", {"item_id": _safe_item_id(item_id), "limit": max(1, min(int(limit), 500))})


def _safe_item_id(value: str) -> str:
    item_id = str(value or "").strip()
    if not ITEM_ID_RE.match(item_id):
        raise CatalogFeedbackError("Catalog item id must be a safe item id.")
    return item_id


def _safe_text(value: str, label: str, *, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        raise CatalogFeedbackError(f"{label} is too long.")
    for name, pattern in FORBIDDEN_PATTERNS.items():
        if pattern.search(text):
            raise CatalogFeedbackError(f"{label} contains disallowed {name} data.")
    return text
