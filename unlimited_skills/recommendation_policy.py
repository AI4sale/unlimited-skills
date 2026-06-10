from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any


SCHEMA_VERSION = 1
DECISION_MANIFEST_TYPE = "recommendation-decision"
REFUSAL_MANIFEST_TYPE = "recommendation-refusal"

OUTCOMES: tuple[str, ...] = (
    "allow_preview",
    "allow_install",
    "allow_update_preview",
    "warn_before_install",
    "deny_install",
    "deny_update",
    "require_registration",
    "require_entitlement",
    "require_policy_override",
    "local_only",
    "unsupported",
)

DENIAL_OUTCOMES: frozenset[str] = frozenset(
    {
        "deny_install",
        "deny_update",
        "require_registration",
        "require_entitlement",
        "require_policy_override",
        "local_only",
        "unsupported",
    }
)

PRIVATE_DATA_KEYS: frozenset[str] = frozenset(
    {
        "archive_url",
        "body",
        "checkout_url",
        "customer_data",
        "customer_name",
        "device_private_key",
        "license_token",
        "local_path",
        "local_paths",
        "private_key",
        "private_keys",
        "prompt",
        "prompts",
        "proof",
        "proofs",
        "repo_path",
        "repo_paths",
        "search_query",
        "search_queries",
        "secret",
        "skill_body",
        "skill_bodies",
        "skill_content",
        "task_text",
        "team_id",
        "team_token",
        "token",
        "tokens",
    }
)

FORBIDDEN_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[A-Za-z]:[\\/][^\s\"']+"),
    re.compile(r"(?<![\w-])/(?:home|Users|root|var|opt|srv|mnt)/[^\s\"']+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\buls_(?:hub|token|license)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE|OPENSSH) KEY-----", re.IGNORECASE),
)

SAFE_FLAGS: dict[str, bool] = {
    "fixture_only": True,
    "preview_only": True,
    "automatic_install": False,
    "automatic_update": False,
    "automatic_remove": False,
    "automatic_telemetry": False,
    "hosted_query_forwarding": False,
    "skill_rewriting": False,
    "full_catalog_distribution": False,
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


class RecommendationPolicyError(RuntimeError):
    """Raised when a recommendation policy fixture violates the public contract."""


@dataclass(frozen=True)
class RefusalCode:
    code: str
    outcome: str
    reason: str
    next_command: str
    owner: str
    action: str
    fallback: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationDecision:
    case: str
    item_id: str
    source_type: str
    status: str
    outcome: str
    reason: str
    next_command: str
    refusal_code: str = ""
    owner: str = ""
    action: str = ""
    fallback: str = ""
    recommended_channel: str = "stable"
    installed_version: str = ""
    recommended_version: str = ""

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(SAFE_FLAGS)
        payload["will_install"] = False
        payload["will_update"] = False
        payload["will_remove"] = False
        if not payload["refusal_code"]:
            payload.pop("refusal_code")
            payload.pop("owner")
            payload.pop("action")
            payload.pop("fallback")
        return payload


REFUSAL_CODES: tuple[RefusalCode, ...] = (
    RefusalCode(
        code="registration_required",
        outcome="require_registration",
        reason="Hosted catalog recommendations require a registered client before install advice can be trusted.",
        next_command="unlimited-skills register",
        owner="user",
        action="register this installation before requesting hosted install advice",
        fallback="Use local search/list/view commands without hosted recommendations.",
    ),
    RefusalCode(
        code="entitlement_denied",
        outcome="require_entitlement",
        reason="The catalog item is limited to an entitled organization or team plan.",
        next_command="unlimited-skills plan status",
        owner="organization admin",
        action="grant the required team-pack entitlement or select a public item",
        fallback="Keep using public MIT and community-core skills.",
    ),
    RefusalCode(
        code="policy_denied",
        outcome="require_policy_override",
        reason="Enterprise policy blocks this item for the current installation.",
        next_command="unlimited-skills policy status",
        owner="policy owner",
        action="approve a policy override or choose an allowed replacement",
        fallback="Use the existing allowed local skill set.",
    ),
    RefusalCode(
        code="blocked_item",
        outcome="deny_install",
        reason="Signed catalog metadata marks this item as blocked for install.",
        next_command="unlimited-skills catalog quality-status <item_id>",
        owner="catalog maintainer",
        action="remove the blocker or publish a replacement item",
        fallback="Do not install; keep the current local skill.",
    ),
    RefusalCode(
        code="retired_item",
        outcome="deny_update",
        reason="The installed item is retired and must not receive automated update advice.",
        next_command="unlimited-skills catalog deprecation-status <item_id>",
        owner="catalog maintainer",
        action="publish a replacement mapping if one exists",
        fallback="Pin the installed version or remove it manually after review.",
    ),
    RefusalCode(
        code="low_score",
        outcome="deny_install",
        reason="The item score is below the public install threshold.",
        next_command="unlimited-skills catalog quality-status <item_id>",
        owner="catalog maintainer",
        action="improve the item and rerun evaluation before recommending install",
        fallback="Preview only; do not install from recommendation output.",
    ),
    RefusalCode(
        code="wrong_channel",
        outcome="unsupported",
        reason="The requested recommendation channel is not supported by this client.",
        next_command="unlimited-skills catalog update-recommendations --channel stable",
        owner="user",
        action="retry on a supported channel",
        fallback="Use stable-channel metadata only.",
    ),
    RefusalCode(
        code="wrong_agent",
        outcome="unsupported",
        reason="The item targets a different agent runtime than this installation.",
        next_command="unlimited-skills doctor",
        owner="user",
        action="use an item for the active agent or switch runtimes explicitly",
        fallback="Keep the current runtime-specific local skills.",
    ),
    RefusalCode(
        code="unsigned_metadata",
        outcome="deny_install",
        reason="Recommendation metadata is unsigned or cannot be verified.",
        next_command="unlimited-skills catalog preview <item_id>",
        owner="catalog maintainer",
        action="publish signed metadata before this item can be recommended",
        fallback="Treat the item as unavailable for hosted install.",
    ),
    RefusalCode(
        code="local_only",
        outcome="local_only",
        reason="The item is a local MIT skill and has no hosted install or update action.",
        next_command="unlimited-skills view <skill-name>",
        owner="user",
        action="inspect and manage the local skill directly",
        fallback="No hosted recommendation action is available.",
    ),
)

DECISION_TABLE: tuple[RecommendationDecision, ...] = (
    RecommendationDecision(
        case="local_mit_skill",
        item_id="local:python_testing",
        source_type="local_mit",
        status="local",
        outcome="local_only",
        reason="Local MIT skills remain available offline, but hosted install/update recommendations do not apply.",
        next_command="unlimited-skills view python-testing",
        refusal_code="local_only",
        owner="user",
        action="inspect or edit the local skill manually",
        fallback="Use local search/list/view without hosted recommendation actions.",
    ),
    RecommendationDecision(
        case="hosted_official_catalog_item",
        item_id="official:ecc:python_testing",
        source_type="hosted_official",
        status="active",
        outcome="allow_install",
        reason="Signed official catalog metadata meets the public install threshold for the stable channel.",
        next_command="unlimited-skills catalog preview official:ecc:python_testing",
        recommended_version="0.4.0",
    ),
    RecommendationDecision(
        case="community_catalog_item",
        item_id="community:browser_qa_pack:0.1.0",
        source_type="community_catalog",
        status="active",
        outcome="allow_preview",
        reason="Community catalog metadata can be previewed, while install still requires explicit user confirmation.",
        next_command="unlimited-skills catalog preview community:browser_qa_pack:0.1.0",
        recommended_version="0.1.0",
    ),
    RecommendationDecision(
        case="private_team_pack_item",
        item_id="team_pack:qa_tools:browser_qa",
        source_type="private_team_pack",
        status="entitlement_required",
        outcome="require_entitlement",
        reason="Team-pack recommendations require an entitlement check before preview or install advice is shown.",
        next_command="unlimited-skills plan status",
        refusal_code="entitlement_denied",
        owner="organization admin",
        action="grant team-pack entitlement for this installation",
        fallback="Use public catalog alternatives.",
    ),
    RecommendationDecision(
        case="deprecated",
        item_id="community:legacy_browser_qa:0.1.0",
        source_type="community_catalog",
        status="deprecated",
        outcome="warn_before_install",
        reason="The item is deprecated but has a signed replacement path; require an explicit warning before install.",
        next_command="unlimited-skills catalog deprecation-status community:legacy_browser_qa:0.1.0",
        recommended_version="0.2.0",
    ),
    RecommendationDecision(
        case="retired",
        item_id="community:retired_browser_qa:0.1.0",
        source_type="community_catalog",
        status="retired",
        outcome="deny_update",
        reason="Retired items must not receive update recommendations; use replacement metadata if available.",
        next_command="unlimited-skills catalog deprecation-status community:retired_browser_qa:0.1.0",
        refusal_code="retired_item",
        owner="catalog maintainer",
        action="publish a replacement mapping before any future recommendation",
        fallback="Pin or remove the retired item manually after review.",
        installed_version="0.1.0",
    ),
    RecommendationDecision(
        case="blocked",
        item_id="community:blocked_pack:0.1.0",
        source_type="community_catalog",
        status="blocked",
        outcome="deny_install",
        reason="Blocked items cannot be installed from recommendation previews.",
        next_command="unlimited-skills catalog quality-status community:blocked_pack:0.1.0",
        refusal_code="blocked_item",
        owner="catalog maintainer",
        action="clear the blocker or publish a replacement",
        fallback="Do not install this item.",
    ),
    RecommendationDecision(
        case="low_score",
        item_id="community:low_score_pack:0.1.0",
        source_type="community_catalog",
        status="low_score",
        outcome="deny_install",
        reason="Low-score items stay visible for transparency but cannot be recommended for install.",
        next_command="unlimited-skills catalog quality-status community:low_score_pack:0.1.0",
        refusal_code="low_score",
        owner="catalog maintainer",
        action="raise the quality score before install recommendation",
        fallback="Preview metadata only.",
    ),
    RecommendationDecision(
        case="fixed_pending_eval",
        item_id="community:fixed_pending_eval_pack:0.1.0",
        source_type="community_catalog",
        status="fixed_pending_eval",
        outcome="allow_update_preview",
        reason="A fix exists and is pending evaluation; only an update preview may be shown.",
        next_command="unlimited-skills catalog update-preview community:fixed_pending_eval_pack:0.1.0",
        installed_version="0.1.0",
        recommended_version="0.2.0",
    ),
    RecommendationDecision(
        case="policy_denied",
        item_id="official:ecc:network_automation",
        source_type="hosted_official",
        status="policy_denied",
        outcome="require_policy_override",
        reason="Managed policy denies this category for the current installation.",
        next_command="unlimited-skills policy status",
        refusal_code="policy_denied",
        owner="policy owner",
        action="approve a policy override or choose an allowed item",
        fallback="Use local approved skills only.",
    ),
    RecommendationDecision(
        case="entitlement_denied",
        item_id="team_pack:enterprise_ops:incident_review",
        source_type="private_team_pack",
        status="entitlement_denied",
        outcome="require_entitlement",
        reason="The current plan does not include this team-delivered catalog item.",
        next_command="unlimited-skills plan status",
        refusal_code="entitlement_denied",
        owner="organization admin",
        action="grant or purchase the required entitlement",
        fallback="Use community-core alternatives.",
    ),
    RecommendationDecision(
        case="registration_required",
        item_id="official:ecc:security_review",
        source_type="hosted_official",
        status="registration_required",
        outcome="require_registration",
        reason="Hosted recommendation metadata is unavailable until this installation is registered.",
        next_command="unlimited-skills register",
        refusal_code="registration_required",
        owner="user",
        action="register this installation",
        fallback="Use local search/list/view offline.",
    ),
    RecommendationDecision(
        case="wrong_channel",
        item_id="official:ecc:python_testing",
        source_type="hosted_official",
        status="wrong_channel",
        outcome="unsupported",
        reason="The requested channel is not in the public stable/beta/canary channel set.",
        next_command="unlimited-skills catalog update-recommendations --channel stable",
        refusal_code="wrong_channel",
        owner="user",
        action="retry with a supported channel",
        fallback="Use stable-channel previews only.",
        recommended_channel="nightly",
    ),
    RecommendationDecision(
        case="wrong_agent",
        item_id="official:ecc:swiftui_patterns",
        source_type="hosted_official",
        status="wrong_agent",
        outcome="unsupported",
        reason="The item targets an agent/runtime that is not active for this installation.",
        next_command="unlimited-skills doctor",
        refusal_code="wrong_agent",
        owner="user",
        action="select an item for the active agent runtime",
        fallback="Keep current runtime-specific skills.",
    ),
    RecommendationDecision(
        case="unsigned_metadata",
        item_id="community:unsigned_pack:0.1.0",
        source_type="community_catalog",
        status="unsigned_metadata",
        outcome="deny_install",
        reason="Unsigned metadata cannot drive install or update recommendations.",
        next_command="unlimited-skills catalog preview community:unsigned_pack:0.1.0",
        refusal_code="unsigned_metadata",
        owner="catalog maintainer",
        action="publish signed metadata",
        fallback="Treat the item as unavailable.",
    ),
    RecommendationDecision(
        case="stale_installed_version",
        item_id="official:ecc:security_review",
        source_type="hosted_official",
        status="stale_installed_version",
        outcome="allow_update_preview",
        reason="The installed version is stale, so the client may show a preview-only update recommendation.",
        next_command="unlimited-skills catalog update-preview official:ecc:security_review",
        installed_version="0.3.9",
        recommended_version="0.4.0",
    ),
)


def _assert_public_safe(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in PRIVATE_DATA_KEYS:
                raise RecommendationPolicyError(f"Recommendation policy payload contains private data field: {path}.{key_text}")
            _assert_public_safe(item, path=f"{path}.{key_text}")
        return
    if isinstance(value, list):
        for idx, item in enumerate(value):
            _assert_public_safe(item, path=f"{path}[{idx}]")
        return
    if isinstance(value, str):
        for pattern in FORBIDDEN_TEXT_PATTERNS:
            if pattern.search(value):
                raise RecommendationPolicyError(f"Recommendation policy payload contains private data text at {path}.")


def _validate_decision(decision: RecommendationDecision, refusal_by_code: dict[str, RefusalCode]) -> None:
    if decision.outcome not in OUTCOMES:
        raise RecommendationPolicyError(f"Unknown recommendation outcome: {decision.outcome}")
    if decision.outcome in DENIAL_OUTCOMES:
        if not decision.refusal_code:
            raise RecommendationPolicyError(f"Denial outcome requires refusal_code: {decision.case}")
        refusal = refusal_by_code.get(decision.refusal_code)
        if refusal is None:
            raise RecommendationPolicyError(f"Unknown refusal code: {decision.refusal_code}")
        for field_name in ("reason", "next_command", "owner", "action", "fallback"):
            if not str(getattr(decision, field_name) or getattr(refusal, field_name) or "").strip():
                raise RecommendationPolicyError(f"Denial outcome requires {field_name}: {decision.case}")
    payload = decision.to_json()
    if payload["will_install"] or payload["will_update"] or payload["will_remove"]:
        raise RecommendationPolicyError(f"Recommendation fixture must not claim automatic writes: {decision.case}")
    _assert_public_safe(payload)


def refusal_code_contract() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": REFUSAL_MANIFEST_TYPE,
        **SAFE_FLAGS,
        "refusal_codes": [item.to_json() for item in REFUSAL_CODES],
    }
    _assert_public_safe(payload)
    return payload


def decision_table() -> dict[str, Any]:
    refusal_by_code = {item.code: item for item in REFUSAL_CODES}
    for decision in DECISION_TABLE:
        _validate_decision(decision, refusal_by_code)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": DECISION_MANIFEST_TYPE,
        **SAFE_FLAGS,
        "outcomes": list(OUTCOMES),
        "denial_outcomes": sorted(DENIAL_OUTCOMES),
        "decisions": [item.to_json() for item in DECISION_TABLE],
    }
    _assert_public_safe(payload)
    return payload


def decision_for_case(case: str) -> RecommendationDecision:
    for decision in DECISION_TABLE:
        if decision.case == case:
            _validate_decision(decision, {item.code: item for item in REFUSAL_CODES})
            return decision
    raise RecommendationPolicyError(f"Unknown recommendation fixture case: {case}")


def summarize_decision_counts() -> dict[str, int]:
    counts = {outcome: 0 for outcome in OUTCOMES}
    for decision in DECISION_TABLE:
        counts[decision.outcome] += 1
    return counts


def dumps_contract(payload: dict[str, Any]) -> str:
    _assert_public_safe(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
