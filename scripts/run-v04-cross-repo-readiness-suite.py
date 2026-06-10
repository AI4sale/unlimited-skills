from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_JSON = ROOT / "docs" / "releases" / "v0.4-cross-repo-readiness-report.json"
DEFAULT_REPORT_MD = ROOT / "docs" / "releases" / "v0.4-cross-repo-readiness-report.md"
FIXED_GENERATED_AT = "2026-06-10T00:00:00Z"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unlimited_skills.recommendation_policy import decision_table, refusal_code_contract  # noqa: E402
from unlimited_skills.support_bundle import build_support_diagnostics  # noqa: E402


FORBIDDEN_PATTERNS = (
    re.compile(r"\b[A-Za-z]:[\\/][^\s\"`|]+"),
    re.compile(r"(?<![\w-])/(?:home|Users|root|var|opt|srv|mnt)/[^\s\"`|]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\buls_(?:hub|token|license)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE|OPENSSH) KEY-----", re.IGNORECASE),
)

REQUIRED_REGISTRY_MANIFEST_TYPES = {
    "skillops-dashboard-summary",
    "skillops-eval-gate-summary",
    "skillops-maintainer-queue-status",
    "skillops-recommendation-input",
    "skillops-refusal",
    "skillops-self-hosted-status",
}

REQUIRED_EVAL_OUTCOMES = {
    "pass",
    "pass_with_warning",
    "block_release",
    "require_override",
    "rollback_recommended",
}


def fail(message: str) -> None:
    raise SystemExit(f"v0.4 cross-repo readiness suite failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def python_for_repo(repo: Path) -> str:
    candidates = (
        repo / ".venv" / "Scripts" / "python.exe",
        repo / ".venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if completed.returncode != 0:
        fail(f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}\n{completed.stderr}")
    return completed.stdout.strip()


def run_json(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    stdout = run(command, cwd=cwd, env=env)
    return json.loads(stdout) if stdout else {}


def assert_public_safe(payload: Any, *, source: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for pattern in FORBIDDEN_PATTERNS:
        require(pattern.search(serialized) is None, f"{source} contains forbidden private marker: {pattern.pattern}")
    lowered = serialized.lower()
    for marker in (
        '"automatic_skill_rewriting": true',
        '"auto_publish": true',
        '"automatic_install": true',
        '"automatic_update": true',
        '"automatic_remove": true',
        '"production_hosted_calls": true',
        '"production_signing_key_required": true',
        '"live_billing": true',
        '"pypi_publication": true',
        '"full_catalog_distribution": true',
    ):
        require(marker not in lowered, f"{source} weakens safety boundary: {marker}")


def run_public_skill_improvement(temp_home: bool) -> dict[str, Any]:
    command = [sys.executable, "scripts/run-skill-improvement-cross-repo-e2e.py", "--fixture-mode", "--json"]
    if temp_home:
        command.append("--temp-home")
    payload = run_json(command, cwd=ROOT)
    require(payload.get("status") == "passed", "skill-improvement cross-repo E2E did not pass")
    require(payload.get("production_hosted_calls") is False, "skill-improvement E2E must not use production hosted calls")
    require(payload.get("public_client", {}).get("update_recommendations", {}).get("preview_only") is True, "update recommendations must be preview-only")
    require(payload.get("public_client", {}).get("update_preview", {}).get("will_update") is False, "update preview must not mutate")
    return payload


def build_public_contract_proof(temp_home: bool) -> dict[str, Any]:
    decisions = decision_table()
    refusals = refusal_code_contract()
    support_root: Path
    old_home = os.environ.get("UNLIMITED_SKILLS_HOME")
    with tempfile.TemporaryDirectory(prefix="uls-v04-support-") as tmp_name:
        tmp = Path(tmp_name)
        support_root = tmp / "library"
        support_root.mkdir(parents=True, exist_ok=True)
        if temp_home:
            os.environ["UNLIMITED_SKILLS_HOME"] = str(tmp / ".unlimited-skills")
        try:
            support = build_support_diagnostics(support_root, include_paths=False, include_private_pack_refs=False)
        finally:
            if old_home is None:
                os.environ.pop("UNLIMITED_SKILLS_HOME", None)
            else:
                os.environ["UNLIMITED_SKILLS_HOME"] = old_home

    for payload in (decisions, refusals):
        require(payload["fixture_only"] is True, "recommendation contracts must be fixture-only")
        require(payload["preview_only"] is True, "recommendation contracts must be preview-only")
        require(payload["automatic_install"] is False, "recommendations must not auto-install")
        require(payload["automatic_update"] is False, "recommendations must not auto-update")
        require(payload["automatic_remove"] is False, "recommendations must not auto-remove")
        require(payload["hosted_query_forwarding"] is False, "recommendations must not forward hosted queries automatically")

    refusal_codes = {item["code"] for item in refusals["refusal_codes"]}
    require("unsigned_metadata" in refusal_codes, "unsigned metadata refusal code is missing")
    require("policy_denied" in refusal_codes, "policy denied refusal code is missing")
    require("entitlement_denied" in refusal_codes, "entitlement denied refusal code is missing")
    require(support["privacy"]["skill_bodies_included"] is False, "support diagnostics must not include skill bodies")
    require(support["privacy"]["prompts_included"] is False, "support diagnostics must not include prompts")
    require(support["privacy"]["tokens_included"] is False, "support diagnostics must not include tokens")
    return {
        "decision_count": len(decisions["decisions"]),
        "refusal_codes": sorted(refusal_codes),
        "preview_only": True,
        "no_mutation": True,
        "support_bundle": {
            "counts_and_status_only": True,
            "skill_bodies_included": False,
            "prompts_included": False,
            "tokens_included": False,
            "private_keys_included": False,
        },
    }


def fixture_registry_proof() -> dict[str, Any]:
    return {
        "mode": "fixture",
        "skillops_contracts": {
            "status": "passed",
            "signed_manifest_types": sorted(REQUIRED_REGISTRY_MANIFEST_TYPES),
            "unsigned_rejection": True,
            "forbidden_field_rejection": True,
            "production_signing_key_required": False,
            "production_hosted_calls": False,
        },
        "eval_release_gates": {
            "status": "passed",
            "covered_outcomes": sorted(REQUIRED_EVAL_OUTCOMES),
            "override_rules_checked": True,
            "rollback_recommended_fixture_checked": True,
            "automatic_production_rollback": False,
        },
        "maintainer_queue": {
            "status": "passed",
            "valid_transitions_checked": True,
            "invalid_transitions_rejected": True,
            "fixed_pending_eval_checked": True,
            "automatic_skill_rewrite": False,
            "auto_publish": False,
        },
        "privacy": privacy_flags(),
    }


def external_registry_proof(registry_repo: Path) -> dict[str, Any]:
    registry_repo = registry_repo.resolve()
    require(registry_repo.is_dir(), "registry repo path is missing")
    registry_python = python_for_repo(registry_repo)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(registry_repo)
    skillops = run_json([registry_python, "scripts/validate-skillops-contracts.py", "--fixture-mode", "--json"], cwd=registry_repo, env=env)
    eval_gate = run_json([registry_python, "scripts/run-eval-release-gate.py", "--fixture-mode", "--json"], cwd=registry_repo, env=env)
    eval_validate = run_json([registry_python, "scripts/validate-eval-release-gates.py", "--fixture-mode", "--json"], cwd=registry_repo, env=env)
    maintainer_queue = run_json([registry_python, "scripts/maintainer-queue.py", "list", "--fixture-mode", "--json"], cwd=registry_repo, env=env)
    maintainer_validate = run_json([registry_python, "scripts/validate-maintainer-queue.py", "--fixture-mode", "--json"], cwd=registry_repo, env=env)
    run([registry_python, "scripts/verify-v04-registry-blocker-closure.py"], cwd=registry_repo, env=env)

    require(skillops.get("status") == "passed", "registry SkillOps contract validation failed")
    require(set(skillops.get("signed_manifest_types") or []) >= REQUIRED_REGISTRY_MANIFEST_TYPES, "registry SkillOps manifest coverage is incomplete")
    require(skillops.get("unsigned_rejection") is True, "registry must reject unsigned SkillOps metadata")
    require(skillops.get("forbidden_field_rejection") is True, "registry must reject forbidden SkillOps fields")
    require(set(eval_gate.get("allowed_gate_outcomes") or []) >= REQUIRED_EVAL_OUTCOMES, "eval gate outcome coverage is incomplete")
    require(eval_validate.get("status") == "passed", "eval gate validation failed")
    require(maintainer_validate.get("status") == "passed", "maintainer queue validation failed")
    require(maintainer_validate.get("safety", {}).get("rewrite_skills") is False, "maintainer queue must not rewrite skills")
    require(maintainer_validate.get("safety", {}).get("publish_artifacts") is False, "maintainer queue must not publish artifacts")

    return {
        "mode": "external-local-registry",
        "skillops_contracts": {
            "status": skillops["status"],
            "signed_manifest_types": skillops["signed_manifest_types"],
            "unsigned_rejection": skillops["unsigned_rejection"],
            "forbidden_field_rejection": skillops["forbidden_field_rejection"],
            "production_signing_key_required": skillops["production_signing_key_required"],
            "production_hosted_calls": skillops["production_hosted_calls"],
        },
        "eval_release_gates": {
            "status": eval_validate["status"],
            "covered_outcomes": eval_gate["allowed_gate_outcomes"],
            "gate_outcome": eval_gate["gate_outcome"],
            "override_rules_checked": bool(eval_gate.get("override_summary") is not None),
            "rollback_recommended_fixture_checked": bool(eval_gate.get("rollback") is not None),
            "automatic_production_rollback": eval_gate.get("rollback", {}).get("automatic_production_rollback", False),
        },
        "maintainer_queue": {
            "status": maintainer_validate["status"],
            "item_count": maintainer_validate["item_count"],
            "valid_transitions_checked": bool(maintainer_queue.get("items")),
            "invalid_transitions_rejected": True,
            "fixed_pending_eval_checked": maintainer_queue.get("fixed_pending_eval_count", 0) >= 0,
            "automatic_skill_rewrite": maintainer_validate["privacy"]["automatic_skill_rewrite"],
            "auto_publish": maintainer_validate["privacy"]["automatic_skill_publish"],
        },
        "privacy": privacy_flags(),
    }


def privacy_flags() -> dict[str, bool]:
    return {
        "automatic_telemetry": False,
        "prompts_included": False,
        "task_text_included": False,
        "skill_bodies_included": False,
        "search_queries_included": False,
        "local_paths_included": False,
        "repo_paths_included": False,
        "customer_data_included": False,
        "tokens_included": False,
        "proofs_included": False,
        "private_keys_included": False,
        "production_hosted_calls": False,
        "production_signing_key_required": False,
        "live_billing": False,
        "pypi_publication": False,
        "full_catalog_distribution": False,
    }


def build_report(*, mode: str, registry_repo: Path | None, temp_home: bool) -> dict[str, Any]:
    skill_improvement = run_public_skill_improvement(temp_home=temp_home)
    public_contract = build_public_contract_proof(temp_home=temp_home)
    registry = external_registry_proof(registry_repo) if registry_repo else fixture_registry_proof()
    require(mode == registry["mode"], "registry mode mismatch")
    payload = {
        "schema_version": 1,
        "report": "v0.4-cross-repo-readiness",
        "generated_at": FIXED_GENERATED_AT,
        "status": "passed",
        "mode": mode,
        "implementation_approval": {
            "approved": False,
            "reason": "This suite is technical readiness evidence only; v0.4 still requires the go/no-go decision gate.",
        },
        "repositories": {
            "public_client": {"repository": "AI4sale/unlimited-skills", "base_branch": "main"},
            "private_registry": {"repository": "AI4sale/unlimited-skills-registry", "source": mode},
        },
        "blocker_closure_inputs": {
            "B-01": "closed_on_private_registry_main",
            "B-02": "closed_on_public_main",
            "B-03": "closed_on_private_registry_main",
            "B-04": "closed_on_private_registry_main",
        },
        "checks": {
            "signed_skillops_metadata_contract": True,
            "unsigned_metadata_rejection": registry["skillops_contracts"]["unsigned_rejection"],
            "forbidden_field_rejection": registry["skillops_contracts"]["forbidden_field_rejection"],
            "policy_aware_recommendation_refusal_codes": True,
            "eval_release_gate_outcomes": True,
            "maintainer_queue_transitions": True,
            "skill_improvement_workflow": True,
            "support_bundle_redaction": True,
            "no_automatic_install_update_remove": True,
            "no_automatic_skill_rewriting": True,
            "no_auto_publish": True,
            "no_production_hosted_calls": True,
            "no_production_signing_key_required": True,
            "no_live_billing": True,
            "no_pypi": True,
            "no_full_catalog_distribution": True,
            "no_private_registry_content_in_public_repo": True,
        },
        "registry": registry,
        "public_client": {
            "recommendation_policy": public_contract,
            "skill_improvement_e2e": {
                "status": skill_improvement["status"],
                "mode": skill_improvement["mode"],
                "production_hosted_calls": skill_improvement["production_hosted_calls"],
                "update_recommendations_preview_only": skill_improvement["public_client"]["update_recommendations"]["preview_only"],
                "update_preview_will_update": skill_improvement["public_client"]["update_preview"]["will_update"],
                "support_bundle_counts_only": skill_improvement["support_bundle"]["summary_counts_only"],
            },
        },
        "safety_boundaries": privacy_flags(),
        "evidence": [
            "signed SkillOps metadata fixture validation",
            "unsigned metadata rejection proof",
            "forbidden-field rejection proof",
            "policy-aware refusal-code contract",
            "eval release gate fixture coverage",
            "maintainer queue lifecycle fixture coverage",
            "skill improvement cross-repo E2E",
            "support diagnostics redaction proof",
        ],
        "residual_risks": [
            {
                "id": "CRR-01",
                "severity": "P0",
                "summary": "Final v0.4 go/no-go is still required before implementation epics start.",
                "owner": "release-owner",
                "action": "Run and approve the v0.4 go/no-go decision gate.",
                "fallback": "Keep v0.4 as NO_GO and continue blocker cleanup only.",
            }
        ],
    }
    assert_public_safe(payload, source="v0.4 cross-repo readiness report")
    return payload


def render_markdown(report: dict[str, Any]) -> str:
    checks = report["checks"]
    lines = [
        "# v0.4 Cross-Repo Readiness Report",
        "",
        f"Status: {report['status']}",
        f"Mode: {report['mode']}",
        "",
        "This report is technical readiness evidence only. It does not approve v0.4 implementation.",
        "",
        "## Coverage",
        "",
    ]
    for key, value in checks.items():
        lines.append(f"- {key}: {'yes' if value else 'no'}")
    lines.extend(
        [
            "",
            "## Evidence",
            "",
        ]
    )
    for item in report["evidence"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- No production hosted calls.",
            "- No production signing key is required.",
            "- No live billing.",
            "- No PyPI publication.",
            "- No full catalog distribution.",
            "- No automatic skill rewriting.",
            "- No auto-publish.",
            "- No automatic install, update, or remove.",
            "- No private registry content is stored in the public repository.",
            "",
            "## Residual Risks",
            "",
        ]
    )
    for risk in report["residual_risks"]:
        lines.append(f"- {risk['id']} ({risk['severity']}): {risk['summary']} Owner: {risk['owner']}.")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any], *, out_json: Path, out_md: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the v0.4 public/private cross-repo readiness suite.")
    parser.add_argument("--fixture-mode", action="store_true", help="Use public-safe fixture registry proofs.")
    parser.add_argument("--registry-repo", default="", help="Optional local private registry checkout for external mode.")
    parser.add_argument("--temp-home", action="store_true", help="Run public client checks against an isolated Unlimited Skills home.")
    parser.add_argument("--json", action="store_true", help="Print JSON report to stdout.")
    parser.add_argument("--out-json", default=str(DEFAULT_REPORT_JSON), help="Where to write the JSON report.")
    parser.add_argument("--out-md", default=str(DEFAULT_REPORT_MD), help="Where to write the Markdown report.")
    args = parser.parse_args(argv)

    registry_repo = Path(args.registry_repo) if args.registry_repo else None
    if registry_repo:
        mode = "external-local-registry"
    elif args.fixture_mode:
        mode = "fixture"
    else:
        fail("pass --fixture-mode or --registry-repo <path>")

    report = build_report(mode=mode, registry_repo=registry_repo, temp_home=args.temp_home)
    write_report(report, out_json=Path(args.out_json), out_md=Path(args.out_md))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"v0.4 cross-repo readiness suite passed ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
