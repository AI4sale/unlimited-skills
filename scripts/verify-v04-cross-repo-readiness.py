from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "docs" / "releases" / "v0.4-cross-repo-readiness-report.json"
REPORT_MD = ROOT / "docs" / "releases" / "v0.4-cross-repo-readiness-report.md"
RISK_REGISTER = ROOT / "docs" / "rfcs" / "v0.4-risk-register.md"
PLATFORM_RFC = ROOT / "docs" / "rfcs" / "v0.4-skillops-platform-rfc.md"
KNOWN_LIMITATIONS = ROOT / "docs" / "known-limitations.md"
README = ROOT / "README.md"
SECURITY = ROOT / "SECURITY.md"
CHANGELOG = ROOT / "CHANGELOG.md"

REQUIRED_CHECKS = {
    "signed_skillops_metadata_contract",
    "unsigned_metadata_rejection",
    "forbidden_field_rejection",
    "policy_aware_recommendation_refusal_codes",
    "eval_release_gate_outcomes",
    "maintainer_queue_transitions",
    "skill_improvement_workflow",
    "support_bundle_redaction",
    "no_automatic_install_update_remove",
    "no_automatic_skill_rewriting",
    "no_auto_publish",
    "no_production_hosted_calls",
    "no_production_signing_key_required",
    "no_live_billing",
    "no_pypi",
    "no_full_catalog_distribution",
    "no_private_registry_content_in_public_repo",
}

REQUIRED_BLOCKERS = {"B-01", "B-02", "B-03", "B-04"}

FORBIDDEN_PATTERNS = (
    re.compile(r"\b[A-Za-z]:[\\/][^\s\"`|]+"),
    re.compile(r"(?<![\w-])/(?:home|Users|root|var|opt|srv|mnt)/[^\s\"`|]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\buls_(?:hub|token|license)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE|OPENSSH) KEY-----", re.IGNORECASE),
)


def fail(message: str) -> None:
    raise SystemExit(f"v0.4 cross-repo readiness verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def require_phrase(path: Path, phrase: str) -> None:
    require(phrase.lower() in read_text(path).lower(), f"{path.relative_to(ROOT)} missing phrase: {phrase}")


def assert_public_safe(path: Path) -> None:
    text = read_text(path)
    for pattern in FORBIDDEN_PATTERNS:
        require(pattern.search(text) is None, f"{path.relative_to(ROOT)} contains forbidden private marker: {pattern.pattern}")


def assert_report_shape(report: dict[str, Any]) -> None:
    require(report.get("schema_version") == 1, "schema_version must be 1")
    require(report.get("report") == "v0.4-cross-repo-readiness", "unexpected report name")
    require(report.get("status") == "passed", "report status must be passed")
    require(report.get("mode") in {"fixture", "external-local-registry"}, "unexpected report mode")
    require(report.get("implementation_approval", {}).get("approved") is False, "report must not approve v0.4 implementation")
    require(set(report.get("blocker_closure_inputs", {})) == REQUIRED_BLOCKERS, "B-01..B-04 closure inputs are incomplete")

    checks = report.get("checks", {})
    require(set(checks) >= REQUIRED_CHECKS, "report is missing required readiness checks")
    for key in REQUIRED_CHECKS:
        require(checks.get(key) is True, f"readiness check must be true: {key}")

    skillops = report.get("registry", {}).get("skillops_contracts", {})
    require(skillops.get("unsigned_rejection") is True, "unsigned metadata rejection proof missing")
    require(skillops.get("forbidden_field_rejection") is True, "forbidden-field rejection proof missing")
    require(skillops.get("production_signing_key_required") is False, "production signing key must not be required")
    require(skillops.get("production_hosted_calls") is False, "production hosted calls must be false")

    eval_gates = report.get("registry", {}).get("eval_release_gates", {})
    require("rollback_recommended" in set(eval_gates.get("covered_outcomes") or []), "rollback-recommended eval fixture missing")
    require(eval_gates.get("automatic_production_rollback") is False, "eval gates must not trigger automatic rollback")

    queue = report.get("registry", {}).get("maintainer_queue", {})
    require(queue.get("valid_transitions_checked") is True, "maintainer queue valid transition proof missing")
    require(queue.get("invalid_transitions_rejected") is True, "maintainer queue invalid transition proof missing")
    require(queue.get("automatic_skill_rewrite") is False, "maintainer queue must not rewrite skills")
    require(queue.get("auto_publish") is False, "maintainer queue must not publish")

    public_client = report.get("public_client", {})
    require(public_client.get("recommendation_policy", {}).get("no_mutation") is True, "public recommendation non-mutation proof missing")
    require(public_client.get("skill_improvement_e2e", {}).get("update_recommendations_preview_only") is True, "update recommendations must be preview-only")
    require(public_client.get("skill_improvement_e2e", {}).get("update_preview_will_update") is False, "update preview must not mutate")

    boundaries = report.get("safety_boundaries", {})
    for key, expected in {
        "automatic_telemetry": False,
        "prompts_included": False,
        "task_text_included": False,
        "skill_bodies_included": False,
        "local_paths_included": False,
        "repo_paths_included": False,
        "tokens_included": False,
        "proofs_included": False,
        "private_keys_included": False,
        "production_hosted_calls": False,
        "production_signing_key_required": False,
        "live_billing": False,
        "pypi_publication": False,
        "full_catalog_distribution": False,
    }.items():
        require(boundaries.get(key) is expected, f"safety boundary mismatch: {key}")


def assert_docs() -> None:
    for path in (REPORT_JSON, REPORT_MD, RISK_REGISTER, PLATFORM_RFC, KNOWN_LIMITATIONS, README, SECURITY, CHANGELOG):
        require(path.is_file(), f"missing required file: {path.relative_to(ROOT)}")
    require_phrase(REPORT_MD, "technical readiness evidence only")
    require_phrase(RISK_REGISTER, "cross-repo readiness suite")
    require_phrase(PLATFORM_RFC, "Cross-Repo Readiness Suite")
    require_phrase(KNOWN_LIMITATIONS, "v0.4 cross-repo readiness")
    require_phrase(README, "v0.4 cross-repo readiness")
    require_phrase(SECURITY, "v0.4 cross-repo readiness")
    require_phrase(CHANGELOG, "v0.4 cross-repo readiness")


def main() -> int:
    assert_docs()
    for path in (REPORT_JSON, REPORT_MD):
        assert_public_safe(path)
    report = json.loads(read_text(REPORT_JSON))
    assert_report_shape(report)
    print("v0.4 cross-repo readiness verification passed")
    print("status: " + report["status"])
    print("mode: " + report["mode"])
    print("v0.4 implementation approved: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
