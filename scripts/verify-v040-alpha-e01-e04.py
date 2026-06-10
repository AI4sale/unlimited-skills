from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.0-alpha"
REPORT_JSON = ROOT / "docs" / "releases" / "v0.4.0-alpha.e01-e04-integration-report.json"
REPORT_MD = ROOT / "docs" / "releases" / "v0.4.0-alpha.e01-e04-integration-report.md"
RELEASE_DOC = ROOT / "docs" / "releases" / "v0.4.0-alpha.md"
CHECKLIST = ROOT / "docs" / "releases" / "v0.4.0-alpha-checklist.md"
MANIFEST = ROOT / "docs" / "releases" / "v0.4.0-alpha.release-manifest.json"
KNOWN_ISSUES = ROOT / "docs" / "releases" / "v0.4.0-alpha-known-issues.md"
REQUIRED_DOCS = [
    REPORT_JSON,
    REPORT_MD,
    RELEASE_DOC,
    CHECKLIST,
    MANIFEST,
    KNOWN_ISSUES,
    ROOT / "docs" / "policy-aware-recommendations.md",
    ROOT / "docs" / "eval-release-gates.md",
    ROOT / "docs" / "maintainer-queue-status.md",
    ROOT / "docs" / "governance-dashboard.md",
    ROOT / "docs" / "known-limitations.md",
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
]

FORBIDDEN_PATTERNS = (
    re.compile(r"\b[A-Za-z]:[\\/][^\s\"`|]+"),
    re.compile(r"(?<![\w-])/(?:home|Users|root|var|opt|srv|mnt)/[^\s\"`|]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\buls_(?:hub|token|license)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE|OPENSSH) KEY-----", re.IGNORECASE),
)


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} E01-E04 verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def require_phrase(path: Path, phrase: str) -> None:
    require(phrase.lower() in read(path).lower(), f"{path.relative_to(ROOT)} missing phrase: {phrase}")


def assert_public_safe(path: Path) -> None:
    text = read(path)
    for pattern in FORBIDDEN_PATTERNS:
        require(pattern.search(text) is None, f"{path.relative_to(ROOT)} contains forbidden private marker: {pattern.pattern}")


def git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    require(completed.returncode == 0, completed.stderr.strip() or "git rev-parse failed")
    return completed.stdout.strip()


def assert_report(report: dict[str, Any]) -> None:
    require(report.get("schema_version") == 1, "report schema_version must be 1")
    require(report.get("report") == "v0.4.0-alpha-e01-e04-integration", "unexpected report type")
    require(report.get("release") == RELEASE, "unexpected release")
    require(report.get("status") == "passed", "report status must be passed")
    require(report.get("mode") in {"fixture", "external-local-registry"}, "unexpected report mode")
    checks = report.get("checks", {})
    required_checks = {
        "E01_policy_aware_recommendation_preview",
        "E02_eval_release_operator_workflow",
        "E03_maintainer_queue_runtime_and_public_status",
        "E04_governance_dashboard_signed_summary",
        "support_bundle_redaction",
        "signed_metadata_required",
        "fixed_pending_eval_evidence",
        "no_automatic_install_update_remove",
        "no_automatic_rewrite",
        "no_auto_publish",
        "no_production_rollout",
        "no_production_hosted_calls",
        "no_production_signing_key_required",
        "no_live_billing",
        "no_pypi",
        "no_full_catalog_distribution",
        "no_private_registry_content_in_public_repo",
    }
    require(set(checks) >= required_checks, "integration report is missing required checks")
    for key in required_checks:
        require(checks.get(key) is True, f"check must be true: {key}")

    public = report.get("public_client", {})
    require(public.get("E01_policy_aware_recommendation_preview", {}).get("preview_only") is True, "E01 preview must be preview-only")
    require(public.get("E01_policy_aware_recommendation_preview", {}).get("automatic_install") is False, "E01 must not install")
    require(public.get("E03_public_maintainer_queue_client", {}).get("metadata_only") is True, "public E03 client must be metadata-only")
    require(public.get("support_bundle_redaction", {}).get("counts_only") is True, "support bundle proof must be counts-only")

    registry = report.get("registry", {})
    require(registry.get("E02_eval_release_operator_workflow", {}).get("release_owner_decides") is True, "E02 release owner boundary missing")
    require(registry.get("E03_maintainer_queue_runtime_api", {}).get("metadata_only") is True, "E03 runtime must be metadata-only")
    require(registry.get("E03_maintainer_queue_runtime_api", {}).get("mutates_queue") is False, "E03 runtime must not mutate queue")
    governance = registry.get("E04_governance_dashboard_summary_api", {})
    require(governance.get("metadata_only") is True, "E04 governance must be metadata-only")
    require(governance.get("admin_console_read_only") is True, "E04 governance dashboard must be read-only")
    require(governance.get("mutates_queue") is False, "E04 governance must not mutate queue")
    require(governance.get("mutates_policies") is False, "E04 governance must not mutate policies")
    require(governance.get("mutates_private_packs") is False, "E04 governance must not mutate private packs")

    boundary = report.get("release_boundary", {})
    require(boundary.get("version_prepared") == RELEASE, "release version is not prepared")
    require(boundary.get("final_tag_created") is False, "Task 2 must not create final tag")
    require(boundary.get("task3_publication_gate_required") is True, "Task 3 publication gate must remain required")


def assert_manifest(manifest: dict[str, Any], expected_sha: str | None) -> None:
    require(manifest.get("release") == RELEASE, "release manifest has wrong release")
    require(manifest.get("package_version") == "0.4.0", "release manifest has wrong package version")
    git = manifest.get("git", {})
    require(git.get("tag") == RELEASE, "release manifest has wrong tag")
    require(git.get("tag_status") in {"not_created_by_task2", "pending_release_owner_approval"}, "manifest must not mark the final tag as created")
    require(git.get("tag_target_sha_policy"), "tag target SHA policy is missing")
    if expected_sha:
        require(len(expected_sha) == 40, "--expected-sha must be a full 40-character commit SHA")
        require(git_head() == expected_sha, "current HEAD does not match --expected-sha")


def assert_docs() -> None:
    for path in REQUIRED_DOCS:
        require(path.is_file(), f"missing required file: {path.relative_to(ROOT)}")
    for path in (REPORT_JSON, REPORT_MD, RELEASE_DOC, CHECKLIST, MANIFEST, KNOWN_ISSUES):
        assert_public_safe(path)
    for phrase in (
        "v0.4.0-alpha",
        "E01",
        "E02",
        "E03",
        "E04",
        "no production rollout",
        "no automatic telemetry",
        "no prompt upload",
        "no skill body upload",
        "no automatic hosted query forwarding",
        "no automatic rewriting",
        "no auto-publish",
        "no live billing",
        "no PyPI",
        "no full catalog distribution",
        "MIT local core remains registration-free",
    ):
        require_phrase(RELEASE_DOC, phrase)
    require_phrase(ROOT / "docs" / "eval-release-gates.md", "release owner")
    require_phrase(ROOT / "docs" / "governance-dashboard.md", "read-only signed metadata")
    require_phrase(ROOT / "docs" / "known-limitations.md", "v0.4.0-alpha E01-E04 integration")
    require_phrase(ROOT / "README.md", "v0.4.0-alpha E01-E04 integration")
    require_phrase(ROOT / "SECURITY.md", "v0.4.0-alpha E01-E04")
    require_phrase(ROOT / "CHANGELOG.md", "v0.4.0-alpha E01-E04")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the v0.4.0-alpha E01-E04 integration gate.")
    parser.add_argument("--expected-sha", default="", help="Optional current checkout SHA expected by release automation.")
    args = parser.parse_args(argv)

    assert_docs()
    report = json.loads(read(REPORT_JSON))
    manifest = json.loads(read(MANIFEST))
    assert_report(report)
    assert_manifest(manifest, args.expected_sha or None)
    print("v0.4.0-alpha E01-E04 integration verification passed")
    print("status: " + report["status"])
    print("mode: " + report["mode"])
    print("release: " + RELEASE)
    print("final tag created: false")
    print("production hosted calls: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
