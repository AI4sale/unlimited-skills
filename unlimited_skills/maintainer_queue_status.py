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
from .updates import RegistrationRequired, current_collection_state


MAINTAINER_QUEUE_REQUIRED_MESSAGE = (
    "Registration is required for hosted maintainer queue status. "
    "The MIT local search/list/view commands remain fully usable offline."
)
MAINTAINER_QUEUE_STATUS_MANIFEST = "maintainer-queue-runtime-status"
MAINTAINER_QUEUE_SUMMARY_MANIFEST = "maintainer-queue-runtime-summary"
FIXED_PENDING_EVAL_MANIFEST = "maintainer-queue-fixed-pending-eval"


class MaintainerQueueStatusError(RuntimeError):
    """Raised when signed maintainer queue metadata cannot be trusted or displayed safely."""


class MaintainerQueueRegistrationRequired(RegistrationRequired):
    """Raised when queue status is requested without registration."""


@dataclass(frozen=True)
class MaintainerQueueStatus:
    item_id: str
    queue_status: str = "unknown"
    severity_summary: dict[str, int] = field(default_factory=dict)
    maintainer_state: str = "unknown"
    fixed_pending_eval_evidence_ref: str = ""
    eval_gate_ref: str = ""
    recommended_user_action: str = "none"
    issue_categories: tuple[str, ...] = ()
    updated_at: str = ""
    metadata_only: bool = True

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["privacy"] = metadata_privacy()
        return payload


@dataclass(frozen=True)
class MaintainerQueueSummary:
    total_count: int = 0
    queue_status_counts: dict[str, int] = field(default_factory=dict)
    severity_summary: dict[str, int] = field(default_factory=dict)
    issue_categories: tuple[str, ...] = ()
    maintainer_state_counts: dict[str, int] = field(default_factory=dict)
    fixed_pending_eval_count: int = 0
    blocked_eval_gate_count: int = 0
    recommended_user_actions: dict[str, int] = field(default_factory=dict)
    metadata_only: bool = True

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["privacy"] = metadata_privacy(summary_only=True)
        return payload


@dataclass(frozen=True)
class FixedPendingEvalStatus:
    item_id: str
    fixed_pending_eval: bool = False
    queue_status: str = "unknown"
    severity_summary: dict[str, int] = field(default_factory=dict)
    maintainer_state: str = "unknown"
    evidence_ref: str = ""
    eval_gate_ref: str = ""
    recommended_user_action: str = "none"
    issue_categories: tuple[str, ...] = ()
    metadata_only: bool = True

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["privacy"] = metadata_privacy()
        return payload


def metadata_privacy(*, summary_only: bool = False) -> dict[str, Any]:
    return {
        "metadata_only": True,
        "summary_counts_only": summary_only,
        "automatic_update": False,
        "automatic_install": False,
        "automatic_remove": False,
        "automatic_rewrite": False,
        "automatic_reindex": False,
        "automatic_publish": False,
        "skill_bodies_included": False,
        "prompts_included": False,
        "task_text_included": False,
        "maintainer_private_notes_included": False,
        "local_paths_included": False,
        "repo_paths_included": False,
        "customer_data_included": False,
        "tokens_included": False,
        "proofs_included": False,
        "private_keys_included": False,
    }


def redacted_maintainer_queue_summary() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "registered_operation": True,
        "metadata_only": True,
        "summary_counts_only": True,
        "queue_status": {
            "total_count": 0,
            "queue_status_counts": {},
            "severity_summary": {},
            "fixed_pending_eval_count": 0,
            "blocked_eval_gate_count": 0,
            "issue_categories": [],
        },
        "item_ids_included": False,
        "item_names_included": False,
        "skill_bodies_included": False,
        "prompts_included": False,
        "task_text_included": False,
        "maintainer_private_notes_included": False,
        "local_paths_included": False,
        "repo_paths_included": False,
        "customer_data_included": False,
        "tokens_included": False,
        "proofs_included": False,
        "private_keys_included": False,
    }


def _safe_item_id(value: str) -> str:
    item_id = str(value or "").strip()
    if not ITEM_ID_RE.match(item_id):
        raise MaintainerQueueStatusError("Catalog item id must be a safe item id.")
    return item_id


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _count_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for key, count in value.items():
        label = str(key or "").strip().lower()
        if label:
            counts[label] = _int(count)
    return counts


def _status_from_json(data: dict[str, Any]) -> MaintainerQueueStatus:
    category = str(data.get("category") or "")
    severity = str(data.get("severity") or "")
    return MaintainerQueueStatus(
        item_id=_safe_item_id(str(data.get("item_id") or "")),
        queue_status=str(data.get("queue_status") or data.get("status") or "unknown"),
        severity_summary=_count_map(data.get("severity_summary") or ({severity: 1} if severity else {})),
        maintainer_state=str(data.get("maintainer_state") or data.get("public_maintainer_state") or data.get("maintainer_action_state") or "unknown"),
        fixed_pending_eval_evidence_ref=str(data.get("fixed_pending_eval_evidence_ref") or data.get("evidence_ref") or ""),
        eval_gate_ref=str(data.get("eval_gate_ref") or ""),
        recommended_user_action=str(data.get("recommended_user_action") or data.get("recommended_action") or "none"),
        issue_categories=_tuple(data.get("issue_categories") or ([category] if category else [])),
        updated_at=str(data.get("updated_at") or data.get("last_updated") or ""),
    )


def _summary_from_json(data: dict[str, Any]) -> MaintainerQueueSummary:
    action = str(data.get("recommended_user_action") or "")
    maintainer_state = str(data.get("maintainer_action_state") or "")
    return MaintainerQueueSummary(
        total_count=_int(data.get("total_count") or data.get("item_count")),
        queue_status_counts=_count_map(data.get("queue_status_counts") or data.get("counts_by_state")),
        severity_summary=_count_map(data.get("severity_summary")),
        issue_categories=_tuple(data.get("issue_categories")),
        maintainer_state_counts=_count_map(data.get("maintainer_state_counts") or data.get("public_maintainer_state_counts") or ({maintainer_state: 1} if maintainer_state else {})),
        fixed_pending_eval_count=_int(data.get("fixed_pending_eval_count")),
        blocked_eval_gate_count=_int(data.get("blocked_eval_gate_count")),
        recommended_user_actions=_count_map(data.get("recommended_user_actions") or ({action: 1} if action else {})),
    )


def _fixed_pending_eval_from_json(data: dict[str, Any]) -> FixedPendingEvalStatus:
    category = str(data.get("category") or "")
    severity = str(data.get("severity") or "")
    return FixedPendingEvalStatus(
        item_id=_safe_item_id(str(data.get("item_id") or "")),
        fixed_pending_eval=bool(data.get("fixed_pending_eval") or data.get("status") == "fixed_pending_eval"),
        queue_status=str(data.get("queue_status") or data.get("status") or "unknown"),
        severity_summary=_count_map(data.get("severity_summary") or ({severity: 1} if severity else {})),
        maintainer_state=str(data.get("maintainer_state") or data.get("public_maintainer_state") or data.get("maintainer_action_state") or "unknown"),
        evidence_ref=str(data.get("evidence_ref") or data.get("fixed_pending_eval_evidence_ref") or ""),
        eval_gate_ref=str(data.get("eval_gate_ref") or ""),
        recommended_user_action=str(data.get("recommended_user_action") or data.get("recommended_action") or "none"),
        issue_categories=_tuple(data.get("issue_categories") or ([category] if category else [])),
    )


def _verify_signed_payload(data: dict[str, Any], *, purpose: str, expected_type: str) -> None:
    manifest_type = str(data.get("manifest_type") or "")
    if manifest_type != expected_type:
        raise MaintainerQueueStatusError(f"{purpose} manifest_type must be {expected_type}.")
    try:
        verify_manifest_signature(
            data,
            purpose=purpose,
            required=True,
            scope=expected_type,
            registry_url="",
        )
    except ManifestSignatureError as exc:
        raise MaintainerQueueStatusError(str(exc)) from exc


def _assert_safe_metadata(data: dict[str, Any]) -> None:
    try:
        _assert_metadata_safe(data)
    except CatalogQualityError as exc:
        raise MaintainerQueueStatusError(str(exc)) from exc


class MaintainerQueueStatusClient:
    def __init__(self, state: RegistrationState, *, timeout: float = 30.0) -> None:
        if not state.registered:
            raise MaintainerQueueRegistrationRequired(MAINTAINER_QUEUE_REQUIRED_MESSAGE)
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
            raise MaintainerQueueStatusError(str(exc)) from exc

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

    def status(self, root: Path, item_id: str) -> MaintainerQueueStatus:
        response = self._post("/v1/skillops/maintainer-queue/status", self._payload(root, item_id=item_id))
        _verify_signed_payload(response, purpose="Maintainer queue status", expected_type=MAINTAINER_QUEUE_STATUS_MANIFEST)
        _assert_safe_metadata(response)
        runtime = response.get("runtime") if isinstance(response.get("runtime"), dict) else {}
        items = runtime.get("items") if isinstance(runtime.get("items"), list) else []
        raw = dict(items[0]) if items and isinstance(items[0], dict) else dict(runtime)
        if "recommended_user_action" not in raw:
            raw["recommended_user_action"] = runtime.get("recommended_user_action")
        return _status_from_json(raw)

    def summary(self, root: Path) -> MaintainerQueueSummary:
        response = self._post("/v1/skillops/maintainer-queue/summary", self._payload(root))
        _verify_signed_payload(response, purpose="Maintainer queue summary", expected_type=MAINTAINER_QUEUE_SUMMARY_MANIFEST)
        _assert_safe_metadata(response)
        raw = response.get("runtime") if isinstance(response.get("runtime"), dict) else response
        return _summary_from_json(raw)

    def fixed_pending_eval(self, root: Path, item_id: str) -> FixedPendingEvalStatus:
        response = self._post("/v1/skillops/maintainer-queue/fixed-pending-eval", self._payload(root, item_id=item_id))
        _verify_signed_payload(response, purpose="Fixed pending eval status", expected_type=FIXED_PENDING_EVAL_MANIFEST)
        _assert_safe_metadata(response)
        runtime = response.get("runtime") if isinstance(response.get("runtime"), dict) else {}
        items = runtime.get("items") if isinstance(runtime.get("items"), list) else []
        raw = dict(items[0]) if items and isinstance(items[0], dict) else dict(runtime)
        if "eval_gate_ref" not in raw:
            raw["eval_gate_ref"] = runtime.get("eval_gate_reference")
        if "recommended_user_action" not in raw:
            raw["recommended_user_action"] = runtime.get("recommended_user_action")
        return _fixed_pending_eval_from_json(raw)


def dumps_queue(value: MaintainerQueueStatus | MaintainerQueueSummary | FixedPendingEvalStatus) -> str:
    return json.dumps(value.to_json(), ensure_ascii=False, indent=2, sort_keys=True)
