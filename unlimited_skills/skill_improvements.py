from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .catalog_feedback import ITEM_ID_RE
from .catalog_quality import CatalogQualityError, _assert_metadata_safe, _tuple
from .registration import RegistrationError, RegistrationState, post_json
from .signatures import ManifestSignatureError, verify_manifest_signature
from .updates import RegistrationRequired, current_collection_state, preview_only_update_recommendation_flags


SKILL_IMPROVEMENT_REQUIRED_MESSAGE = (
    "Registration is required for hosted skill improvement status and update recommendations. "
    "The MIT local search/list/view commands remain fully usable offline."
)
IMPROVEMENT_STATUS_MANIFEST = "skill-improvement-status"
KNOWN_ISSUES_MANIFEST = "skill-known-issues"
UPDATE_RECOMMENDATIONS_MANIFEST = "update-recommendations"
UPDATE_PREVIEW_MANIFEST = "update-preview"
DEPRECATION_STATUS_MANIFEST = "deprecation-status"


class SkillImprovementError(RuntimeError):
    """Raised when signed skill-improvement metadata cannot be trusted or displayed safely."""


class SkillImprovementRegistrationRequired(RegistrationRequired):
    """Raised when improvement status is requested without registration."""


@dataclass(frozen=True)
class KnownIssue:
    issue_id: str
    severity: str
    status: str = "open"
    fix_status: str = "unknown"
    title: str = ""
    fixed_in_version: str = ""
    compatibility_notes: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkillImprovementStatus:
    item_id: str
    installed_version: str = ""
    latest_version: str = ""
    recommended_version: str = ""
    recommended_channel: str = "stable"
    open_issue_count: int = 0
    severity_summary: dict[str, int] = field(default_factory=dict)
    fix_status: str = "unknown"
    deprecated: bool = False
    retired: bool = False
    deprecation_reason: str = ""
    retirement_reason: str = ""
    compatibility_notes: tuple[str, ...] = ()
    stale_installed_version: bool = False
    update_available: bool = False
    recommended_action: str = "none"
    metadata_only: bool = True

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["privacy"] = metadata_privacy()
        return payload


@dataclass(frozen=True)
class KnownIssuesStatus:
    item_id: str
    open_issue_count: int = 0
    severity_summary: dict[str, int] = field(default_factory=dict)
    fix_status: str = "unknown"
    issues: tuple[KnownIssue, ...] = ()
    compatibility_notes: tuple[str, ...] = ()
    metadata_only: bool = True

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [issue.to_json() for issue in self.issues]
        payload["privacy"] = metadata_privacy()
        return payload


@dataclass(frozen=True)
class UpdateRecommendation:
    item_id: str
    installed_version: str = ""
    recommended_version: str = ""
    recommended_channel: str = "stable"
    recommended_action: str = "none"
    reason: str = ""
    open_issue_count: int = 0
    severity_summary: dict[str, int] = field(default_factory=dict)
    fix_status: str = "unknown"
    deprecated: bool = False
    retired: bool = False
    stale_installed_version: bool = False
    compatibility_notes: tuple[str, ...] = ()
    preview_only: bool = True
    will_install: bool = False
    will_update: bool = False
    will_remove: bool = False
    metadata_only: bool = True

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["privacy"] = metadata_privacy(preview_only=True)
        return payload


@dataclass(frozen=True)
class DeprecationStatus:
    item_id: str
    deprecated: bool = False
    retired: bool = False
    deprecation_reason: str = ""
    retirement_reason: str = ""
    replacement_item_id: str = ""
    recommended_version: str = ""
    recommended_channel: str = "stable"
    recommended_action: str = "none"
    compatibility_notes: tuple[str, ...] = ()
    metadata_only: bool = True

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["privacy"] = metadata_privacy()
        return payload


def metadata_privacy(*, preview_only: bool = False) -> dict[str, Any]:
    payload = {
        "metadata_only": True,
        "preview_only": preview_only,
        "automatic_update": False,
        "automatic_install": False,
        "automatic_remove": False,
        "skill_bodies_included": False,
        "prompts_included": False,
        "task_text_included": False,
        "local_paths_included": False,
        "repo_paths_included": False,
        "customer_data_included": False,
        "tokens_included": False,
        "proofs_included": False,
        "private_keys_included": False,
    }
    if preview_only:
        payload.update(preview_only_update_recommendation_flags())
    return payload


def redacted_skill_improvement_summary() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "registered_operation": True,
        "metadata_only": True,
        "summary_counts_only": True,
        "automatic_update": False,
        "automatic_install": False,
        "automatic_remove": False,
        "item_names_included": False,
        "skill_bodies_included": False,
        "prompts_included": False,
        "local_paths_included": False,
        "repo_paths_included": False,
        "customer_data_included": False,
        "tokens_included": False,
        "proofs_included": False,
        "private_keys_included": False,
        "improvement_status": {
            "known_item_count": 0,
            "open_issue_count": 0,
            "critical_or_high_issue_count": 0,
            "update_recommendation_count": 0,
            "remove_recommendation_count": 0,
            "deprecated_or_retired_count": 0,
            "stale_installed_count": 0,
        },
    }


def _safe_item_id(value: str) -> str:
    item_id = str(value or "").strip()
    if not ITEM_ID_RE.match(item_id):
        raise SkillImprovementError("Catalog item id must be a safe item id.")
    return item_id


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _severity_summary(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    summary: dict[str, int] = {}
    for key, count in value.items():
        label = str(key or "").strip().lower()
        if label:
            summary[label] = _int(count)
    return summary


def _issue_from_json(data: dict[str, Any]) -> KnownIssue:
    return KnownIssue(
        issue_id=str(data.get("issue_id") or data.get("id") or ""),
        severity=str(data.get("severity") or "unknown").lower(),
        status=str(data.get("status") or "open"),
        fix_status=str(data.get("fix_status") or "unknown"),
        title=str(data.get("title") or ""),
        fixed_in_version=str(data.get("fixed_in_version") or ""),
        compatibility_notes=_tuple(data.get("compatibility_notes")),
    )


def _status_from_json(data: dict[str, Any]) -> SkillImprovementStatus:
    item_id = _safe_item_id(str(data.get("item_id") or ""))
    return SkillImprovementStatus(
        item_id=item_id,
        installed_version=str(data.get("installed_version") or ""),
        latest_version=str(data.get("latest_version") or ""),
        recommended_version=str(data.get("recommended_version") or ""),
        recommended_channel=str(data.get("recommended_channel") or data.get("channel") or "stable"),
        open_issue_count=_int(data.get("open_issue_count")),
        severity_summary=_severity_summary(data.get("severity_summary")),
        fix_status=str(data.get("fix_status") or "unknown"),
        deprecated=bool(data.get("deprecated")),
        retired=bool(data.get("retired")),
        deprecation_reason=str(data.get("deprecation_reason") or ""),
        retirement_reason=str(data.get("retirement_reason") or ""),
        compatibility_notes=_tuple(data.get("compatibility_notes")),
        stale_installed_version=bool(data.get("stale_installed_version")),
        update_available=bool(data.get("update_available")),
        recommended_action=str(data.get("recommended_action") or "none"),
    )


def _known_issues_from_json(data: dict[str, Any]) -> KnownIssuesStatus:
    raw_issues = data.get("issues") if isinstance(data.get("issues"), list) else []
    issues = tuple(_issue_from_json(item) for item in raw_issues if isinstance(item, dict))
    return KnownIssuesStatus(
        item_id=_safe_item_id(str(data.get("item_id") or "")),
        open_issue_count=_int(data.get("open_issue_count") if "open_issue_count" in data else len(issues)),
        severity_summary=_severity_summary(data.get("severity_summary")),
        fix_status=str(data.get("fix_status") or "unknown"),
        issues=issues,
        compatibility_notes=_tuple(data.get("compatibility_notes")),
    )


def _recommendation_from_json(data: dict[str, Any]) -> UpdateRecommendation:
    return UpdateRecommendation(
        item_id=_safe_item_id(str(data.get("item_id") or "")),
        installed_version=str(data.get("installed_version") or ""),
        recommended_version=str(data.get("recommended_version") or ""),
        recommended_channel=str(data.get("recommended_channel") or data.get("channel") or "stable"),
        recommended_action=str(data.get("recommended_action") or "none"),
        reason=str(data.get("reason") or ""),
        open_issue_count=_int(data.get("open_issue_count")),
        severity_summary=_severity_summary(data.get("severity_summary")),
        fix_status=str(data.get("fix_status") or "unknown"),
        deprecated=bool(data.get("deprecated")),
        retired=bool(data.get("retired")),
        stale_installed_version=bool(data.get("stale_installed_version")),
        compatibility_notes=_tuple(data.get("compatibility_notes")),
        preview_only=bool(data.get("preview_only", True)),
        will_install=bool(data.get("will_install", False)),
        will_update=bool(data.get("will_update", False)),
        will_remove=bool(data.get("will_remove", False)),
    )


def _deprecation_from_json(data: dict[str, Any]) -> DeprecationStatus:
    return DeprecationStatus(
        item_id=_safe_item_id(str(data.get("item_id") or "")),
        deprecated=bool(data.get("deprecated")),
        retired=bool(data.get("retired")),
        deprecation_reason=str(data.get("deprecation_reason") or ""),
        retirement_reason=str(data.get("retirement_reason") or ""),
        replacement_item_id=str(data.get("replacement_item_id") or ""),
        recommended_version=str(data.get("recommended_version") or ""),
        recommended_channel=str(data.get("recommended_channel") or data.get("channel") or "stable"),
        recommended_action=str(data.get("recommended_action") or "none"),
        compatibility_notes=_tuple(data.get("compatibility_notes")),
    )


def _verify_signed_payload(data: dict[str, Any], *, purpose: str, expected_type: str) -> dict[str, Any]:
    manifest_type = str(data.get("manifest_type") or "")
    if manifest_type != expected_type:
        raise SkillImprovementError(f"{purpose} manifest_type must be {expected_type}.")
    try:
        return verify_manifest_signature(
            data,
            purpose=purpose,
            required=True,
            scope=expected_type,
            registry_url="",
        )
    except ManifestSignatureError as exc:
        raise SkillImprovementError(str(exc)) from exc


def _assert_safe_metadata(data: dict[str, Any]) -> None:
    try:
        _assert_metadata_safe(data)
    except CatalogQualityError as exc:
        raise SkillImprovementError(str(exc)) from exc


def _assert_preview_only(recommendation: UpdateRecommendation) -> None:
    if not recommendation.preview_only:
        raise SkillImprovementError("Update recommendation responses must be preview-only.")
    if recommendation.will_install or recommendation.will_update or recommendation.will_remove:
        raise SkillImprovementError("Update recommendation preview must not report automatic write actions.")


class SkillImprovementClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0) -> None:
        if not state.registered:
            raise SkillImprovementRegistrationRequired(SKILL_IMPROVEMENT_REQUIRED_MESSAGE)
        self.state = state
        self.timeout = timeout

    def _client_payload(self) -> dict[str, str]:
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
            raise SkillImprovementError(str(exc)) from exc

    def _payload(self, root: Path | None = None, *, item_id: str = "", **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "install_id": self.state.install_id,
            "client": self._client_payload(),
        }
        if item_id:
            payload["item_id"] = _safe_item_id(item_id)
        if root is not None:
            payload["collections"] = current_collection_state(root)
        for key, value in extra.items():
            if value in {"", None, ()} or value == []:
                continue
            payload[key] = value
        return payload

    def improvement_status(self, root: Path, item_id: str) -> SkillImprovementStatus:
        response = self._post("/v1/catalog/improvements/status", self._payload(root, item_id=item_id))
        _verify_signed_payload(response, purpose="Skill improvement status", expected_type=IMPROVEMENT_STATUS_MANIFEST)
        _assert_safe_metadata(response)
        raw = response.get("improvement_status") if isinstance(response.get("improvement_status"), dict) else response
        return _status_from_json(raw)

    def known_issues(self, root: Path, item_id: str) -> KnownIssuesStatus:
        response = self._post("/v1/catalog/improvements/known-issues", self._payload(root, item_id=item_id))
        _verify_signed_payload(response, purpose="Skill known issues", expected_type=KNOWN_ISSUES_MANIFEST)
        _assert_safe_metadata(response)
        raw = response.get("known_issues") if isinstance(response.get("known_issues"), dict) else response
        return _known_issues_from_json(raw)

    def update_recommendations(self, root: Path) -> list[UpdateRecommendation]:
        response = self._post("/v1/catalog/improvements/update-recommendations", self._payload(root))
        _verify_signed_payload(response, purpose="Skill update recommendations", expected_type=UPDATE_RECOMMENDATIONS_MANIFEST)
        _assert_safe_metadata(response)
        raw = response.get("recommendations") if isinstance(response.get("recommendations"), list) else []
        recommendations = [_recommendation_from_json(item) for item in raw if isinstance(item, dict)]
        for recommendation in recommendations:
            _assert_preview_only(recommendation)
        return recommendations

    def update_preview(self, root: Path, item_id: str) -> UpdateRecommendation:
        response = self._post("/v1/catalog/improvements/update-preview", self._payload(root, item_id=item_id, preview_only=True))
        _verify_signed_payload(response, purpose="Skill update preview", expected_type=UPDATE_PREVIEW_MANIFEST)
        _assert_safe_metadata(response)
        raw = response.get("recommendation") if isinstance(response.get("recommendation"), dict) else response
        recommendation = _recommendation_from_json(raw)
        _assert_preview_only(recommendation)
        return recommendation

    def deprecation_status(self, root: Path, item_id: str) -> DeprecationStatus:
        response = self._post("/v1/catalog/improvements/deprecation-status", self._payload(root, item_id=item_id))
        _verify_signed_payload(response, purpose="Skill deprecation status", expected_type=DEPRECATION_STATUS_MANIFEST)
        _assert_safe_metadata(response)
        raw = response.get("deprecation_status") if isinstance(response.get("deprecation_status"), dict) else response
        return _deprecation_from_json(raw)


def dumps_improvement(value: SkillImprovementStatus | KnownIssuesStatus | UpdateRecommendation | DeprecationStatus) -> str:
    return json.dumps(value.to_json(), ensure_ascii=False, indent=2, sort_keys=True)
