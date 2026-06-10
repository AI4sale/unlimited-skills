from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from unlimited_skills.recommendation_policy import PRIVATE_DATA_KEYS, RecommendationPolicyError, _assert_public_safe
from unlimited_skills.recommendation_preview import build_policy_aware_preview, fixture_preview


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "recommendations"
SCHEMAS = ROOT / "schemas"


def _base_item(**overrides: object) -> dict[str, object]:
    item = {
        "item_id": "community:browser-qa-pack:0.1.0",
        "pack_id": "browser-qa-pack",
        "source": "community",
        "review_status": "published",
        "installable": True,
        "requires_registration": True,
        "plan_requirement": "registered-community",
        "compatible_agents": ["codex", "claude-code"],
        "version": "0.1.0",
        "channel": "stable",
    }
    item.update(overrides)
    return item


def _registered_plan(**overrides: object) -> dict[str, object]:
    plan = {
        "registered": True,
        "source": "fixture",
        "plan": "community",
        "status": "active",
        "features_enabled": ["local_skill_hub"],
        "limits": {},
        "policy": {"signed_manifests_required": True},
        "denial_reason": "",
    }
    plan.update(overrides)
    return plan


def _assert_preview_safe(payload: dict[str, object]) -> None:
    _assert_public_safe(payload)
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in PRIVATE_DATA_KEYS:
        assert f'"{forbidden}"' not in serialized
    assert payload["preview_only"] is True
    assert payload["automatic_install"] is False
    assert payload["automatic_update"] is False
    assert payload["automatic_remove"] is False
    assert payload["will_install"] is False
    assert payload["will_update"] is False
    assert payload["will_remove"] is False


def test_runtime_preview_allows_explicit_install_flow_without_applying_changes() -> None:
    payload = build_policy_aware_preview(
        catalog_item=_base_item(),
        quality_status={"item_id": "community:browser-qa-pack:0.1.0", "quality_grade": "a", "install_allowed": True},
        entitlement_status=_registered_plan(),
        policy_status={"installed": False, "signed_manifests_required": True},
        active_agent="codex",
    )

    _assert_preview_safe(payload)
    assert payload["fixture_only"] is False
    assert payload["manifest_type"] == "policy-aware-recommendation-preview"
    assert payload["decision"]["outcome"] == "allow_install"
    assert payload["decision"]["next_command"].endswith("--dry-run")


@pytest.mark.parametrize(
    ("item", "quality", "plan", "policy", "expected_outcome", "expected_refusal"),
    [
        (_base_item(), {}, _registered_plan(denial_reason="no_entitlement"), {}, "require_entitlement", "entitlement_denied"),
        (_base_item(), {}, _registered_plan(), {"default_action": "deny"}, "require_policy_override", "policy_denied"),
        (_base_item(), {"blockers": ["unsafe"], "install_allowed": False}, _registered_plan(), {}, "deny_install", "blocked_item"),
        (_base_item(), {"quality_grade": "f", "install_allowed": True}, _registered_plan(), {}, "deny_install", "low_score"),
        (_base_item(retired=True), {}, _registered_plan(), {}, "deny_update", "retired_item"),
        (_base_item(compatible_agents=["hermes"]), {}, _registered_plan(), {}, "unsupported", "wrong_agent"),
    ],
)
def test_runtime_preview_denials_are_public_safe(item: dict[str, object], quality: dict[str, object], plan: dict[str, object], policy: dict[str, object], expected_outcome: str, expected_refusal: str) -> None:
    payload = build_policy_aware_preview(
        catalog_item=item,
        quality_status=quality,
        entitlement_status=plan,
        policy_status=policy,
        active_agent="codex",
    )

    _assert_preview_safe(payload)
    assert payload["decision"]["outcome"] == expected_outcome
    assert payload["decision"]["refusal_code"] == expected_refusal
    assert payload["decision"]["owner"]
    assert payload["decision"]["fallback"]


def test_runtime_preview_update_preview_for_fixed_pending_eval() -> None:
    payload = build_policy_aware_preview(
        catalog_item=_base_item(),
        quality_status={"quality_grade": "a", "install_allowed": True},
        improvement_status={
            "fix_status": "fixed_pending_eval",
            "installed_version": "0.1.0",
            "recommended_version": "0.2.0",
            "recommended_channel": "stable",
        },
        entitlement_status=_registered_plan(),
        policy_status={},
        active_agent="codex",
    )

    _assert_preview_safe(payload)
    assert payload["decision"]["outcome"] == "allow_update_preview"
    assert payload["decision"]["will_update"] is False


def test_runtime_preview_requires_registration_without_hosted_call() -> None:
    payload = build_policy_aware_preview(
        catalog_item=_base_item(review_status="registration_required", installable=False),
        registered=False,
        entitlement_status=_registered_plan(registered=False, denial_reason="unregistered"),
    )

    _assert_preview_safe(payload)
    assert payload["decision"]["outcome"] == "require_registration"
    assert payload["decision"]["refusal_code"] == "registration_required"


def test_runtime_preview_rejects_private_fields() -> None:
    with pytest.raises(RecommendationPolicyError, match="private data"):
        build_policy_aware_preview(catalog_item=_base_item(license_token="uls_token_secret"))


def test_fixture_preview_reuses_decision_contract() -> None:
    payload = fixture_preview("stale_installed_version")

    _assert_preview_safe(payload)
    assert payload["decision"]["outcome"] == "allow_update_preview"
    assert payload["signals"]["catalog_metadata"]["present"] is True


def test_runtime_preview_schema_and_example_are_public_safe_json() -> None:
    for path in [
        SCHEMAS / "policy-aware-recommendation-preview.schema.json",
        EXAMPLES / "runtime-preview.example.json",
    ]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload
        _assert_public_safe(payload)
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for forbidden in PRIVATE_DATA_KEYS:
            assert f'"{forbidden}"' not in serialized

    example = json.loads((EXAMPLES / "runtime-preview.example.json").read_text(encoding="utf-8"))
    _assert_preview_safe(example)
    assert example["manifest_type"] == "policy-aware-recommendation-preview"
    assert example["fixture_only"] is False


def test_cli_fixture_preview_outputs_json_without_registration() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unlimited_skills.cli",
            "catalog",
            "recommendation-preview",
            "--fixture-case",
            "policy_denied",
            "--json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    _assert_preview_safe(payload)
    assert payload["fixture_only"] is True
    assert payload["decision"]["outcome"] == "require_policy_override"
