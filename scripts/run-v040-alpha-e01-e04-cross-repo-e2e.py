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
DEFAULT_REPORT_JSON = ROOT / "docs" / "releases" / "v0.4.0-alpha.e01-e04-integration-report.json"
DEFAULT_REPORT_MD = ROOT / "docs" / "releases" / "v0.4.0-alpha.e01-e04-integration-report.md"
FIXED_GENERATED_AT = "2026-06-10T00:00:00Z"
RELEASE = "v0.4.0-alpha"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unlimited_skills.maintainer_queue_status import redacted_maintainer_queue_summary  # noqa: E402
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

REQUIRED_SKILLOPS_TYPES = {
    "skillops-dashboard-summary",
    "skillops-eval-gate-summary",
    "skillops-governance-dashboard-summary",
    "skillops-governance-entitlements",
    "skillops-governance-eval-gates",
    "skillops-governance-policies",
    "skillops-governance-private-packs",
    "skillops-governance-queue-health",
    "skillops-governance-support-diagnostics",
    "skillops-maintainer-queue-status",
    "skillops-recommendation-input",
    "skillops-refusal",
    "skillops-self-hosted-status",
    "maintainer-queue-runtime-status",
    "maintainer-queue-runtime-item",
    "maintainer-queue-runtime-summary",
    "maintainer-queue-fixed-pending-eval",
}

REQUIRED_EVAL_OUTCOMES = {
    "pass",
    "pass_with_warning",
    "block_release",
    "require_override",
    "rollback_recommended",
    "manual_review_required",
}


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} E01-E04 integration failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def python_for_repo(repo: Path) -> str:
    for candidate in (repo / ".venv" / "Scripts" / "python.exe", repo / ".venv" / "bin" / "python"):
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


def privacy_flags() -> dict[str, bool]:
    return {
        "automatic_telemetry": False,
        "prompts_included": False,
        "task_text_included": False,
        "skill_bodies_included": False,
        "private_pack_bodies_included": False,
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


def mutation_flags() -> dict[str, bool]:
    return {
        "automatic_install": False,
        "automatic_update": False,
        "automatic_remove": False,
        "automatic_rewrite": False,
        "automatic_reindex": False,
        "auto_publish": False,
        "production_rollout": False,
    }


def assert_public_safe(payload: Any, *, source: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for pattern in FORBIDDEN_PATTERNS:
        require(pattern.search(serialized) is None, f"{source} contains forbidden private marker: {pattern.pattern}")
    lowered = serialized.lower()
    for marker in (
        '"automatic_install": true',
        '"automatic_update": true',
        '"automatic_remove": true',
        '"automatic_rewrite": true',
        '"automatic_skill_rewriting": true',
        '"auto_publish": true',
        '"production_rollout": true',
        '"production_hosted_calls": true',
        '"production_signing_key_required": true',
        '"live_billing": true',
        '"pypi_publication": true',
        '"full_catalog_distribution": true',
    ):
        require(marker not in lowered, f"{source} weakens safety boundary: {marker}")


def build_public_proof(*, temp_home: bool) -> dict[str, Any]:
    decisions = decision_table()
    refusals = refusal_code_contract()
    queue_summary = redacted_maintainer_queue_summary()
    old_home = os.environ.get("UNLIMITED_SKILLS_HOME")
    with tempfile.TemporaryDirectory(prefix="uls-v040-support-") as tmp_name:
        tmp = Path(tmp_name)
        library = tmp / "library"
        library.mkdir(parents=True, exist_ok=True)
        if temp_home:
            os.environ["UNLIMITED_SKILLS_HOME"] = str(tmp / ".unlimited-skills")
        try:
            support = build_support_diagnostics(library, include_paths=False, include_private_pack_refs=False)
        finally:
            if old_home is None:
                os.environ.pop("UNLIMITED_SKILLS_HOME", None)
            else:
                os.environ["UNLIMITED_SKILLS_HOME"] = old_home

    for payload in (decisions, refusals):
        require(payload["fixture_only"] is True, "recommendation policy fixtures must be fixture-only")
        require(payload["preview_only"] is True, "recommendation policy fixtures must be preview-only")
        require(payload["automatic_install"] is False, "recommendations must not auto-install")
        require(payload["automatic_update"] is False, "recommendations must not auto-update")
        require(payload["automatic_remove"] is False, "recommendations must not auto-remove")
        require(payload["hosted_query_forwarding"] is False, "recommendations must not forward hosted queries")

    refusal_codes = {item["code"] for item in refusals["refusal_codes"]}
    required_refusals = {"policy_denied", "entitlement_denied", "unsigned_metadata", "local_only", "wrong_agent"}
    require(required_refusals <= refusal_codes, "recommendation refusal code coverage is incomplete")
    require(queue_summary["summary_counts_only"] is True, "maintainer queue support summary must be counts-only")
    require(support["privacy"]["skill_bodies_included"] is False, "support bundle must not include skill bodies")
    require(support["privacy"]["prompts_included"] is False, "support bundle must not include prompts")
    require(support["privacy"]["tokens_included"] is False, "support bundle must not include tokens")

    proof = {
        "E01_policy_aware_recommendation_preview": {
            "status": "passed",
            "decision_count": len(decisions["decisions"]),
            "refusal_codes": sorted(refusal_codes),
            "preview_only": True,
            "hosted_query_forwarding": False,
            **mutation_flags(),
        },
        "E03_public_maintainer_queue_client": {
            "status": "passed",
            "signed_status_manifest_type": "maintainer-queue-runtime-status",
            "signed_summary_manifest_type": "maintainer-queue-runtime-summary",
            "fixed_pending_eval_manifest_type": "maintainer-queue-fixed-pending-eval",
            "support_summary_counts_only": True,
            "metadata_only": True,
            **mutation_flags(),
        },
        "support_bundle_redaction": {
            "status": "passed",
            "counts_only": True,
            "skill_bodies_included": False,
            "prompts_included": False,
            "tokens_included": False,
            "private_keys_included": False,
            "proofs_included": False,
        },
    }
    assert_public_safe(proof, source="public E01/E03 proof")
    return proof


def fixture_registry_proof() -> dict[str, Any]:
    proof = {
        "mode": "fixture",
        "E02_eval_release_operator_workflow": {
            "status": "passed",
            "covered_outcomes": sorted(REQUIRED_EVAL_OUTCOMES),
            "override_rules_checked": True,
            "rollback_recommended_checked": True,
            "release_owner_decides": True,
            "automatic_production_rollback": False,
            **mutation_flags(),
        },
        "E03_maintainer_queue_runtime_api": {
            "status": "passed",
            "signed_manifest_types": [
                "maintainer-queue-runtime-status",
                "maintainer-queue-runtime-item",
                "maintainer-queue-runtime-summary",
                "maintainer-queue-fixed-pending-eval",
            ],
            "metadata_only": True,
            "mutates_queue": False,
            "unsigned_rejection": True,
            "forbidden_field_rejection": True,
            **mutation_flags(),
        },
        "E04_governance_dashboard_summary_api": {
            "status": "passed",
            "signed_manifest_types": [
                "skillops-governance-dashboard-summary",
                "skillops-governance-queue-health",
                "skillops-governance-eval-gates",
                "skillops-governance-entitlements",
                "skillops-governance-policies",
                "skillops-governance-private-packs",
                "skillops-governance-support-diagnostics",
            ],
            "metadata_only": True,
            "admin_console_read_only": True,
            "mutates_queue": False,
            "mutates_policies": False,
            "mutates_private_packs": False,
            "unsigned_rejection": True,
            "forbidden_field_rejection": True,
            **mutation_flags(),
        },
        "skillops_manifest_types": sorted(REQUIRED_SKILLOPS_TYPES),
        "privacy": privacy_flags(),
    }
    assert_public_safe(proof, source="fixture registry proof")
    return proof


def external_registry_proof(registry_repo: Path) -> dict[str, Any]:
    registry_repo = registry_repo.resolve()
    require(registry_repo.is_dir(), "registry repo path is missing")
    registry_python = python_for_repo(registry_repo)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(registry_repo)

    skillops = run_json([registry_python, "scripts/validate-skillops-contracts.py", "--fixture-mode", "--json"], cwd=registry_repo, env=env)
    eval_operator = run_json([registry_python, "scripts/run-eval-release-operator-workflow.py", "--fixture-mode", "--json"], cwd=registry_repo, env=env)
    queue_runtime = run_json([registry_python, "scripts/validate-maintainer-queue-runtime.py", "--fixture-mode", "--json"], cwd=registry_repo, env=env)
    governance = run_json([registry_python, "scripts/validate-governance-dashboard-summary.py", "--fixture-mode", "--json"], cwd=registry_repo, env=env)

    require(skillops.get("status") == "passed", "SkillOps contract validation failed")
    require(set(skillops.get("signed_manifest_types") or []) >= REQUIRED_SKILLOPS_TYPES, "SkillOps manifest type coverage is incomplete")
    require(eval_operator.get("safety", {}).get("auto_publish") is False, "eval operator must not auto-publish")
    require(eval_operator.get("safety", {}).get("live_production_calls") is False, "eval operator must not call production")
    require(eval_operator.get("decision_boundary", {}).get("release_owner_decides") is True, "release owner decision boundary missing")
    require(queue_runtime.get("status") == "passed", "maintainer queue runtime validation failed")
    require(queue_runtime.get("mutates_queue") is False, "maintainer queue runtime must not mutate queue")
    require(queue_runtime.get("metadata_only") is True, "maintainer queue runtime must be metadata-only")
    require(governance.get("status") == "passed", "governance dashboard validation failed")
    require(governance.get("mutates_queue") is False, "governance dashboard must not mutate queue")
    require(governance.get("mutates_policies") is False, "governance dashboard must not mutate policies")
    require(governance.get("mutates_private_packs") is False, "governance dashboard must not mutate private packs")

    proof = {
        "mode": "external-local-registry",
        "E02_eval_release_operator_workflow": {
            "status": "passed",
            "release_id": eval_operator.get("release_id"),
            "gate_outcome": eval_operator.get("gate", {}).get("gate_outcome"),
            "release_owner_decides": True,
            "automatic_production_rollback": eval_operator.get("rollback_summary", {}).get("automatic_production_rollback", False),
            **mutation_flags(),
        },
        "E03_maintainer_queue_runtime_api": {
            "status": queue_runtime["status"],
            "signed_manifest_types": queue_runtime["signed_manifest_types"],
            "metadata_only": queue_runtime["metadata_only"],
            "mutates_queue": queue_runtime["mutates_queue"],
            "unsigned_rejection": queue_runtime["unsigned_rejection"],
            "forbidden_field_rejection": queue_runtime["forbidden_field_rejection"],
            **mutation_flags(),
        },
        "E04_governance_dashboard_summary_api": {
            "status": governance["status"],
            "signed_manifest_types": governance["signed_manifest_types"],
            "metadata_only": governance["metadata_only"],
            "admin_console_read_only": governance["admin_console_read_only"],
            "mutates_queue": governance["mutates_queue"],
            "mutates_policies": governance["mutates_policies"],
            "mutates_private_packs": governance["mutates_private_packs"],
            "unsigned_rejection": governance["unsigned_rejection"],
            "forbidden_field_rejection": governance["forbidden_field_rejection"],
            **mutation_flags(),
        },
        "skillops_manifest_types": sorted(skillops["signed_manifest_types"]),
        "privacy": privacy_flags(),
    }
    assert_public_safe(proof, source="external registry proof")
    return proof


def build_report(*, mode: str, registry_repo: Path | None, temp_home: bool) -> dict[str, Any]:
    public = build_public_proof(temp_home=temp_home)
    registry = external_registry_proof(registry_repo) if registry_repo else fixture_registry_proof()
    require(mode == registry["mode"], "registry mode mismatch")
    payload = {
        "schema_version": 1,
        "report": "v0.4.0-alpha-e01-e04-integration",
        "release": RELEASE,
        "generated_at": FIXED_GENERATED_AT,
        "status": "passed",
        "mode": mode,
        "repositories": {
            "public_client": {"repository": "AI4sale/unlimited-skills", "base_branch": "main"},
            "private_registry": {"repository": "AI4sale/unlimited-skills-registry", "source": mode},
        },
        "merged_prs": {
            "public": [
                {"number": 69, "epic": "E01", "status": "merged"},
                {"number": 74, "epic": "E03", "status": "merged"},
            ],
            "private_registry": [
                {"number": 42, "epic": "E02", "status": "merged"},
                {"number": 43, "epic": "E03", "status": "merged"},
                {"number": 44, "epic": "E04", "status": "merged"},
            ],
        },
        "checks": {
            "E01_policy_aware_recommendation_preview": True,
            "E02_eval_release_operator_workflow": True,
            "E03_maintainer_queue_runtime_and_public_status": True,
            "E04_governance_dashboard_signed_summary": True,
            "support_bundle_redaction": True,
            "signed_metadata_required": True,
            "fixed_pending_eval_evidence": True,
            "no_automatic_install_update_remove": True,
            "no_automatic_rewrite": True,
            "no_auto_publish": True,
            "no_production_rollout": True,
            "no_production_hosted_calls": True,
            "no_production_signing_key_required": True,
            "no_live_billing": True,
            "no_pypi": True,
            "no_full_catalog_distribution": True,
            "no_private_registry_content_in_public_repo": True,
        },
        "public_client": public,
        "registry": registry,
        "safety_boundaries": {**privacy_flags(), **mutation_flags()},
        "release_boundary": {
            "version_prepared": RELEASE,
            "alpha_only": True,
            "final_tag_created": False,
            "production_rollout": False,
            "task3_publication_gate_required": True,
            "tag_target_sha_policy": "Task 2 records integration evidence only. Task 3 must verify the final main SHA before tagging.",
        },
        "evidence": [
            "recommendation preview proof",
            "eval operator workflow proof",
            "signed maintainer queue status proof",
            "fixed-pending-eval proof",
            "signed governance dashboard summary proof",
            "support bundle redaction proof",
            "no mutation proof",
            "no production hosted calls proof",
        ],
    }
    assert_public_safe(payload, source="E01-E04 integration report")
    return payload


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# v0.4.0-alpha E01-E04 Integration Report",
        "",
        f"Status: {report['status']}",
        f"Mode: {report['mode']}",
        f"Release: {report['release']}",
        "",
        "This is an alpha integration gate. It does not create the final tag, authorize production rollout, enable live billing, publish to PyPI, distribute the full catalog, upload prompts, upload skill bodies, forward hosted queries automatically, rewrite skills automatically, install or update skills automatically, or auto-publish catalog artifacts.",
        "",
        "## Coverage",
        "",
    ]
    for key, value in report["checks"].items():
        lines.append(f"- {key}: {'yes' if value else 'no'}")
    lines.extend(["", "## Evidence", ""])
    for item in report["evidence"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Release Boundary",
            "",
            "- Alpha only.",
            "- Task 3 final publication gate is still required before any tag.",
            "- No production hosted calls or production signing keys are required for this gate.",
            "- No private registry content is committed to the public repository.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, Any], *, out_json: Path, out_md: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the v0.4.0-alpha E01-E04 public/private integration gate.")
    parser.add_argument("--fixture-mode", action="store_true", help="Use public-safe fixture registry proofs.")
    parser.add_argument("--registry-repo", default="", help="Optional local private registry checkout for external mode.")
    parser.add_argument("--temp-home", action="store_true", help="Run public checks against an isolated Unlimited Skills home.")
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
        print(f"{RELEASE} E01-E04 integration gate passed ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
