from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from .recommendation_policy import (
    SAFE_FLAGS,
    RecommendationDecision,
    RecommendationPolicyError,
    _assert_public_safe,
    decision_for_case,
)


SCHEMA_VERSION = 1
PREVIEW_MANIFEST_TYPE = "policy-aware-recommendation-preview"


@dataclass(frozen=True)
class RecommendationSignal:
    present: bool
    status: str = "unknown"
    summary: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        payload = {
            "present": self.present,
            "status": self.status,
            "summary": self.summary or {},
        }
        _assert_public_safe(payload)
        return payload


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_json"):
        result = value.to_json()
        return result if isinstance(result, dict) else {}
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return {}


def _tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return ()


def _status(value: Any, *keys: str, default: str = "unknown") -> str:
    data = _as_dict(value)
    for key in keys:
        if str(data.get(key) or "").strip():
            return str(data[key])
    return default


def _bool(value: Any, key: str, default: bool = False) -> bool:
    data = _as_dict(value)
    return bool(data.get(key, default))


def _safe_summary(value: Any, *, allowed: tuple[str, ...]) -> dict[str, Any]:
    data = _as_dict(value)
    summary = {key: data[key] for key in allowed if key in data and data[key] not in ("", None, (), [], {})}
    _assert_public_safe(summary)
    return summary


def _item_summary(catalog_item: Any) -> dict[str, Any]:
    return _safe_summary(
        catalog_item,
        allowed=(
            "item_id",
            "pack_id",
            "source",
            "source_type",
            "channel",
            "version",
            "review_status",
            "installable",
            "requires_registration",
            "plan_requirement",
            "compatible_agents",
            "deprecated",
            "retired",
            "skill_kind",
            "quality_grade",
            "score_band",
            "deprecation_status",
            "fix_status",
            "stale_installed_version",
        ),
    )


def _quality_signal(quality_status: Any) -> RecommendationSignal:
    summary = _safe_summary(
        quality_status,
        allowed=(
            "quality_grade",
            "score_band",
            "install_risk",
            "install_allowed",
            "deprecation_status",
            "retired",
            "blockers",
            "warnings",
            "compatibility_notes",
        ),
    )
    return RecommendationSignal(present=bool(summary), status=str(summary.get("install_risk") or summary.get("score_band") or "unknown"), summary=summary)


def _improvement_signal(improvement_status: Any) -> RecommendationSignal:
    summary = _safe_summary(
        improvement_status,
        allowed=(
            "recommended_action",
            "fix_status",
            "open_issue_count",
            "severity_summary",
            "stale_installed_version",
            "update_available",
            "deprecated",
            "retired",
            "recommended_channel",
            "installed_version",
            "recommended_version",
        ),
    )
    return RecommendationSignal(present=bool(summary), status=str(summary.get("fix_status") or summary.get("recommended_action") or "unknown"), summary=summary)


def _entitlement_signal(entitlement_status: Any, *, source_type: str, plan_requirement: str) -> RecommendationSignal:
    summary = _safe_summary(
        entitlement_status,
        allowed=("registered", "source", "plan", "status", "features_enabled", "limits", "policy", "denial_reason"),
    )
    required = source_type == "private_team_pack" or plan_requirement not in {"", "registered-community", "community-core", "mit-local"}
    denied = str(summary.get("denial_reason") or "").strip()
    features = set(summary.get("features_enabled") or [])
    if required and not denied and source_type == "private_team_pack" and "private_team_packs" not in features:
        denied = "no_entitlement"
        summary["denial_reason"] = denied
    status = denied or str(summary.get("status") or ("required" if required else "ok"))
    _assert_public_safe(summary)
    return RecommendationSignal(present=bool(summary) or required, status=status, summary=summary)


def _policy_signal(policy_status: Any) -> RecommendationSignal:
    summary = _safe_summary(
        policy_status,
        allowed=("installed", "policy_id", "mode", "default_action", "allowed_sources", "blocked_sources", "signed_manifests_required"),
    )
    status = "ok"
    default_action = str(summary.get("default_action") or "").lower()
    if default_action in {"deny", "block", "blocked"}:
        status = "denied"
    return RecommendationSignal(present=bool(summary), status=status, summary=summary)


def _source_type(catalog_item: Any) -> str:
    data = _as_dict(catalog_item)
    source_type = str(data.get("source_type") or "").strip()
    if source_type:
        return source_type
    source = str(data.get("source") or "").strip()
    if source == "community":
        return "community_catalog"
    if source in {"private", "private-visible", "team", "team-pack"}:
        return "private_team_pack"
    if source in {"local", "local_mit"}:
        return "local_mit"
    return "hosted_official"


def _decision(
    *,
    item_id: str,
    source_type: str,
    status: str,
    reason: str,
    next_command: str,
    outcome: str,
    refusal_code: str = "",
    owner: str = "",
    action: str = "",
    fallback: str = "",
    installed_version: str = "",
    recommended_version: str = "",
    recommended_channel: str = "stable",
) -> RecommendationDecision:
    return RecommendationDecision(
        case="runtime_preview",
        item_id=item_id,
        source_type=source_type,
        status=status,
        outcome=outcome,
        reason=reason,
        next_command=next_command,
        refusal_code=refusal_code,
        owner=owner,
        action=action,
        fallback=fallback,
        installed_version=installed_version,
        recommended_version=recommended_version,
        recommended_channel=recommended_channel,
    )


def _preview_flags(*, fixture_only: bool) -> dict[str, bool]:
    flags = dict(SAFE_FLAGS)
    flags["fixture_only"] = fixture_only
    return flags


def build_policy_aware_preview(
    *,
    catalog_item: Any,
    signed_metadata: bool = True,
    registered: bool = True,
    active_agent: str = "",
    channel: str = "stable",
    quality_status: Any = None,
    improvement_status: Any = None,
    entitlement_status: Any = None,
    policy_status: Any = None,
) -> dict[str, Any]:
    item = _as_dict(catalog_item)
    _assert_public_safe(item)
    item_id = str(item.get("item_id") or item.get("id") or "").strip()
    if not item_id:
        raise RecommendationPolicyError("Recommendation preview requires item_id.")
    source_type = _source_type(item)
    plan_requirement = str(item.get("plan_requirement") or "")
    quality = _quality_signal(quality_status or item.get("quality_status"))
    improvement = _improvement_signal(improvement_status or item)
    entitlement = _entitlement_signal(entitlement_status, source_type=source_type, plan_requirement=plan_requirement)
    policy = _policy_signal(policy_status)

    compatible_agents = set(_tuple(item.get("compatible_agents")))
    blockers = set(_tuple(quality.summary.get("blockers") if quality.summary else item.get("blockers")))
    quality_grade = str((quality.summary or {}).get("quality_grade") or item.get("quality_grade") or "").lower()
    install_allowed = bool((quality.summary or {}).get("install_allowed", item.get("installable", False)))
    fix_status = str((improvement.summary or {}).get("fix_status") or item.get("fix_status") or "")
    stale = bool((improvement.summary or {}).get("stale_installed_version") or item.get("stale_installed_version"))
    update_available = bool((improvement.summary or {}).get("update_available"))
    recommended_version = str((improvement.summary or {}).get("recommended_version") or item.get("recommended_version") or "")
    installed_version = str((improvement.summary or {}).get("installed_version") or item.get("installed_version") or "")

    if not signed_metadata:
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status="unsigned_metadata",
            outcome="deny_install",
            reason="Unsigned hosted metadata cannot drive a recommendation preview.",
            next_command=f"unlimited-skills catalog preview {item_id}",
            refusal_code="unsigned_metadata",
            owner="catalog maintainer",
            action="publish signed metadata",
            fallback="Treat the item as unavailable for hosted install advice.",
        )
    elif source_type == "local_mit":
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status="local",
            outcome="local_only",
            reason="Local MIT skills remain available offline, but hosted install/update recommendations do not apply.",
            next_command=f"unlimited-skills view {item_id}",
            refusal_code="local_only",
            owner="user",
            action="inspect or edit the local skill manually",
            fallback="Use local search/list/view without hosted recommendation actions.",
        )
    elif not registered:
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status="registration_required",
            outcome="require_registration",
            reason="Hosted recommendation metadata is unavailable until this installation is registered.",
            next_command="unlimited-skills register",
            refusal_code="registration_required",
            owner="user",
            action="register this installation",
            fallback="Use local search/list/view offline.",
        )
    elif policy.status == "denied":
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status="policy_denied",
            outcome="require_policy_override",
            reason="Managed policy denies this item for the current installation.",
            next_command="unlimited-skills policy status",
            refusal_code="policy_denied",
            owner="policy owner",
            action="approve a policy override or choose an allowed item",
            fallback="Use local approved skills only.",
        )
    elif entitlement.status in {"no_entitlement", "past_due", "suspended", "expired", "plan_limit_exceeded"}:
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status="entitlement_denied",
            outcome="require_entitlement",
            reason="The current plan or team entitlement does not allow this catalog item.",
            next_command="unlimited-skills plan status",
            refusal_code="entitlement_denied",
            owner="organization admin",
            action="grant the required entitlement or choose a public item",
            fallback="Use public MIT and community-core skills.",
        )
    elif active_agent and compatible_agents and active_agent not in compatible_agents:
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status="wrong_agent",
            outcome="unsupported",
            reason="The item targets a different agent runtime than this installation.",
            next_command="unlimited-skills doctor",
            refusal_code="wrong_agent",
            owner="user",
            action="use an item for the active agent or switch runtimes explicitly",
            fallback="Keep the current runtime-specific local skills.",
        )
    elif bool(item.get("retired")) or (quality.summary or {}).get("deprecation_status") == "retired":
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status="retired",
            outcome="deny_update",
            reason="Retired items must not receive update recommendations.",
            next_command=f"unlimited-skills catalog deprecation-status {item_id}",
            refusal_code="retired_item",
            owner="catalog maintainer",
            action="publish a replacement mapping if one exists",
            fallback="Pin the installed version or remove it manually after review.",
        )
    elif blockers or not install_allowed or (quality.summary or {}).get("deprecation_status") == "blocked":
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status="blocked",
            outcome="deny_install",
            reason="Signed catalog quality metadata blocks this item for hosted install advice.",
            next_command=f"unlimited-skills catalog quality {item_id}",
            refusal_code="blocked_item",
            owner="catalog maintainer",
            action="remove the blocker or publish a replacement item",
            fallback="Do not install this item.",
        )
    elif quality_grade in {"d", "f", "blocked"}:
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status="low_score",
            outcome="deny_install",
            reason="The item score is below the public install threshold.",
            next_command=f"unlimited-skills catalog quality {item_id}",
            refusal_code="low_score",
            owner="catalog maintainer",
            action="improve the item and rerun evaluation before recommending install",
            fallback="Preview metadata only.",
        )
    elif fix_status == "fixed_pending_eval" or stale or update_available:
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status="fixed_pending_eval" if fix_status == "fixed_pending_eval" else "stale_installed_version",
            outcome="allow_update_preview",
            reason="A fix or newer version exists; only an update preview may be shown.",
            next_command=f"unlimited-skills catalog update-preview {item_id}",
            installed_version=installed_version,
            recommended_version=recommended_version,
            recommended_channel=channel or "stable",
        )
    elif bool(item.get("deprecated")) or (quality.summary or {}).get("deprecation_status") == "deprecated":
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status="deprecated",
            outcome="warn_before_install",
            reason="The item is deprecated; clients must warn before any explicit install command.",
            next_command=f"unlimited-skills catalog deprecation-status {item_id}",
            recommended_version=recommended_version,
            recommended_channel=channel or "stable",
        )
    elif bool(item.get("installable")):
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status=str(item.get("review_status") or "published"),
            outcome="allow_install",
            reason="Signed catalog metadata and local policy allow offering an explicit install flow.",
            next_command=f"unlimited-skills catalog install {item_id} --dry-run",
            recommended_version=str(item.get("version") or recommended_version),
            recommended_channel=channel or str(item.get("channel") or "stable"),
        )
    else:
        decision = _decision(
            item_id=item_id,
            source_type=source_type,
            status=str(item.get("review_status") or "preview"),
            outcome="allow_preview",
            reason="Metadata may be previewed, but install eligibility is not established.",
            next_command=f"unlimited-skills catalog preview {item_id}",
            recommended_version=str(item.get("version") or recommended_version),
            recommended_channel=channel or str(item.get("channel") or "stable"),
        )

    decision_payload = decision.to_json()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": PREVIEW_MANIFEST_TYPE,
        **_preview_flags(fixture_only=False),
        "item_id": item_id,
        "channel": channel or str(item.get("channel") or "stable"),
        "decision": decision_payload,
        "signals": {
            "catalog_metadata": RecommendationSignal(True, status=str(item.get("review_status") or item.get("status") or "unknown"), summary=_item_summary(item)).to_json(),
            "quality_status": quality.to_json(),
            "improvement_status": improvement.to_json(),
            "entitlement": entitlement.to_json(),
            "policy": policy.to_json(),
        },
        "will_install": False,
        "will_update": False,
        "will_remove": False,
    }
    _assert_public_safe(payload)
    return payload


def fixture_preview(case: str) -> dict[str, Any]:
    decision = decision_for_case(case).to_json()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": PREVIEW_MANIFEST_TYPE,
        **_preview_flags(fixture_only=True),
        "item_id": decision["item_id"],
        "channel": decision.get("recommended_channel") or "stable",
        "decision": decision,
        "signals": {
            "catalog_metadata": RecommendationSignal(True, status=decision["status"], summary={key: decision[key] for key in ("item_id", "source_type", "status", "recommended_channel", "installed_version", "recommended_version") if key in decision}).to_json(),
            "quality_status": RecommendationSignal(False).to_json(),
            "improvement_status": RecommendationSignal(False).to_json(),
            "entitlement": RecommendationSignal(False).to_json(),
            "policy": RecommendationSignal(False).to_json(),
        },
        "will_install": False,
        "will_update": False,
        "will_remove": False,
    }
    _assert_public_safe(payload)
    return payload


def dumps_preview(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
