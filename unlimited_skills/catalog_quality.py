from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from .catalog_feedback import ITEM_ID_RE
from .registration import RegistrationError, RegistrationState, post_json
from .signatures import ManifestSignatureError, verify_manifest_signature
from .updates import RegistrationRequired


CATALOG_QUALITY_REQUIRED_MESSAGE = (
    "Registration is required for hosted catalog quality and evaluation status. "
    "The public client only shows signed metadata and does not evaluate local content."
)
QUALITY_WARNING_THRESHOLD = {"a": 0, "b": 1, "c": 2, "d": 3, "f": 4, "blocked": 5, "unknown": 6}
DEFAULT_MIN_INSTALL_GRADE = "b"
SENSITIVE_KEYS = {
    "skill_body",
    "skill_bodies",
    "body",
    "prompt",
    "prompts",
    "task_text",
    "user_prompt",
    "customer_data",
    "token",
    "license_token",
    "proof",
    "private_key",
    "repo_path",
    "local_path",
    "archive_url",
    "checkout_url",
}
FORBIDDEN_TEXT_PATTERNS = (
    re.compile(r"\b[A-Za-z]:[\\/][^\s\"']+"),
    re.compile(r"(?<![\w-])/(?:home|Users|root)/[^\s\"']+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE|OPENSSH) KEY-----", re.IGNORECASE),
)


class CatalogQualityError(RuntimeError):
    """Raised when catalog quality metadata cannot be trusted or displayed safely."""


class CatalogQualityRegistrationRequired(RegistrationRequired):
    """Raised when quality status is requested without registration."""


@dataclass(frozen=True)
class CatalogQualityStatus:
    item_id: str
    quality_grade: str = "unknown"
    score_band: str = "unknown"
    last_eval_at: str = ""
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    compatibility_notes: tuple[str, ...] = ()
    deprecation_status: str = "active"
    retired: bool = False
    feedback_issue_categories: tuple[str, ...] = ()
    install_risk: str = "unknown"
    install_allowed: bool = True

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CatalogEvalStatus:
    item_id: str
    evaluation_status: str = "unknown"
    quality_grade: str = "unknown"
    score_band: str = "unknown"
    last_eval_at: str = ""
    next_eval_at: str = ""
    evaluator_version: str = ""
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    compatibility_notes: tuple[str, ...] = ()
    feedback_issue_categories: tuple[str, ...] = ()
    deprecation_status: str = "active"
    retired: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return ()


def _safe_item_id(value: str) -> str:
    item_id = str(value or "").strip()
    if not ITEM_ID_RE.match(item_id):
        raise CatalogQualityError("Catalog item id must be a safe item id.")
    return item_id


def _verify_signed_quality_payload(data: dict[str, Any], *, purpose: str, expected_type: str) -> None:
    manifest_type = str(data.get("manifest_type") or "")
    if manifest_type != expected_type:
        raise CatalogQualityError(f"{purpose} manifest_type must be {expected_type}.")
    try:
        verify_manifest_signature(
            data,
            purpose=purpose,
            required=True,
            scope=expected_type,
            registry_url="",
        )
    except ManifestSignatureError as exc:
        raise CatalogQualityError(str(exc)) from exc


def _assert_metadata_safe(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SENSITIVE_KEYS:
                raise CatalogQualityError(f"Catalog quality metadata contains disallowed field: {key_text}")
            _assert_metadata_safe(item, path=f"{path}.{key_text}")
        return
    if isinstance(value, list):
        for idx, item in enumerate(value):
            _assert_metadata_safe(item, path=f"{path}[{idx}]")
        return
    if isinstance(value, str):
        for pattern in FORBIDDEN_TEXT_PATTERNS:
            if pattern.search(value):
                raise CatalogQualityError(f"Catalog quality metadata contains disallowed sensitive text at {path}.")


def _status_from_json(data: dict[str, Any]) -> CatalogQualityStatus:
    item_id = _safe_item_id(str(data.get("item_id") or ""))
    grade = str(data.get("quality_grade") or data.get("grade") or "unknown").lower()
    return CatalogQualityStatus(
        item_id=item_id,
        quality_grade=grade,
        score_band=str(data.get("score_band") or "unknown"),
        last_eval_at=str(data.get("last_eval_at") or data.get("last_evaluated_at") or ""),
        blockers=_tuple(data.get("blockers")),
        warnings=_tuple(data.get("warnings")),
        compatibility_notes=_tuple(data.get("compatibility_notes")),
        deprecation_status=str(data.get("deprecation_status") or ("retired" if data.get("retired") else "active")),
        retired=bool(data.get("retired")),
        feedback_issue_categories=_tuple(data.get("feedback_issue_categories")),
        install_risk=str(data.get("install_risk") or "unknown"),
        install_allowed=bool(data.get("install_allowed", not bool(data.get("blockers")))),
    )


def _eval_from_json(data: dict[str, Any]) -> CatalogEvalStatus:
    item_id = _safe_item_id(str(data.get("item_id") or ""))
    return CatalogEvalStatus(
        item_id=item_id,
        evaluation_status=str(data.get("evaluation_status") or data.get("status") or "unknown"),
        quality_grade=str(data.get("quality_grade") or data.get("grade") or "unknown").lower(),
        score_band=str(data.get("score_band") or "unknown"),
        last_eval_at=str(data.get("last_eval_at") or data.get("last_evaluated_at") or ""),
        next_eval_at=str(data.get("next_eval_at") or ""),
        evaluator_version=str(data.get("evaluator_version") or ""),
        blockers=_tuple(data.get("blockers")),
        warnings=_tuple(data.get("warnings")),
        compatibility_notes=_tuple(data.get("compatibility_notes")),
        feedback_issue_categories=_tuple(data.get("feedback_issue_categories")),
        deprecation_status=str(data.get("deprecation_status") or ("retired" if data.get("retired") else "active")),
        retired=bool(data.get("retired")),
    )


def quality_below_threshold(grade: str, *, minimum_grade: str = DEFAULT_MIN_INSTALL_GRADE) -> bool:
    grade_rank = QUALITY_WARNING_THRESHOLD.get(str(grade or "unknown").lower(), QUALITY_WARNING_THRESHOLD["unknown"])
    threshold_rank = QUALITY_WARNING_THRESHOLD.get(str(minimum_grade or DEFAULT_MIN_INSTALL_GRADE).lower(), QUALITY_WARNING_THRESHOLD["b"])
    return grade_rank > threshold_rank


def install_risk_message(status: CatalogQualityStatus, *, minimum_grade: str = DEFAULT_MIN_INSTALL_GRADE) -> str:
    if status.retired or status.deprecation_status in {"blocked", "retired"} or not status.install_allowed or status.blockers:
        return "Catalog item is blocked for hosted install by signed quality status."
    if quality_below_threshold(status.quality_grade, minimum_grade=minimum_grade):
        return f"Catalog item quality grade {status.quality_grade.upper()} is below the recommended threshold {minimum_grade.upper()}."
    if status.warnings:
        return "Catalog item has signed quality warnings."
    return "Catalog item has no signed quality install warnings."


def assert_quality_allows_hosted_install(status: CatalogQualityStatus, *, minimum_grade: str = DEFAULT_MIN_INSTALL_GRADE) -> None:
    if status.retired or status.deprecation_status in {"blocked", "retired"} or not status.install_allowed or status.blockers:
        raise CatalogQualityError(install_risk_message(status, minimum_grade=minimum_grade))


def redacted_catalog_quality_summary() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "registered_operation": True,
        "metadata_only": True,
        "summary_counts_only": True,
        "automatic_telemetry": False,
        "queries_included": False,
        "item_names_included": False,
        "skill_bodies_included": False,
        "prompts_included": False,
        "local_paths_included": False,
        "repo_paths_included": False,
        "customer_data_included": False,
        "tokens_included": False,
        "proofs_included": False,
        "private_keys_included": False,
        "quality_status": {
            "known_count": 0,
            "blocked_count": 0,
            "warning_count": 0,
            "deprecated_or_retired_count": 0,
            "feedback_issue_category_count": 0,
        },
    }


class CatalogQualityClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0) -> None:
        if not state.registered:
            raise CatalogQualityRegistrationRequired(CATALOG_QUALITY_REQUIRED_MESSAGE)
        self.state = state
        self.timeout = timeout

    def _client_payload(self) -> dict[str, str]:
        from . import __version__

        return {"name": "unlimited-skills", "version": __version__}

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
            raise CatalogQualityError(str(exc)) from exc

    def _payload(self, item_id: str, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": self._client_payload(),
            "item_id": _safe_item_id(item_id),
        }
        for key, value in extra.items():
            if value in {"", None, ()} or value == []:
                continue
            payload[key] = value
        return payload

    def quality(self, item_id: str) -> CatalogQualityStatus:
        response = self._post("/v1/catalog/quality/status", self._payload(item_id))
        _verify_signed_quality_payload(response, purpose="Catalog quality status", expected_type="catalog-quality-status")
        _assert_metadata_safe(response)
        raw = response.get("quality_status") if isinstance(response.get("quality_status"), dict) else response
        return _status_from_json(raw)

    def eval_status(self, item_id: str) -> CatalogEvalStatus:
        response = self._post("/v1/catalog/quality/eval-status", self._payload(item_id))
        _verify_signed_quality_payload(response, purpose="Catalog evaluation status", expected_type="catalog-eval-status")
        _assert_metadata_safe(response)
        raw = response.get("eval_status") if isinstance(response.get("eval_status"), dict) else response
        return _eval_from_json(raw)

    def explain_risk(self, item_id: str, *, minimum_grade: str = DEFAULT_MIN_INSTALL_GRADE) -> dict[str, Any]:
        status = self.quality(item_id)
        return {
            "schema_version": 1,
            "item_id": status.item_id,
            "quality_status": status.to_json(),
            "minimum_recommended_grade": minimum_grade.lower(),
            "blocked": bool(status.retired or status.deprecation_status in {"blocked", "retired"} or not status.install_allowed or status.blockers),
            "warning": quality_below_threshold(status.quality_grade, minimum_grade=minimum_grade) or bool(status.warnings),
            "message": install_risk_message(status, minimum_grade=minimum_grade),
            "privacy": {
                "metadata_only": True,
                "automatic_telemetry": False,
                "skill_bodies_included": False,
                "prompts_included": False,
                "local_paths_included": False,
                "tokens_included": False,
            },
        }


def dumps_status(status: CatalogQualityStatus | CatalogEvalStatus) -> str:
    return json.dumps(status.to_json(), ensure_ascii=False, indent=2, sort_keys=True)
