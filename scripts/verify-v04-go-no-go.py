from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DECISION_JSON = ROOT / "docs" / "releases" / "v0.4-go-no-go-decision.json"
DECISION_MD = ROOT / "docs" / "releases" / "v0.4-go-no-go-decision.md"
CROSS_REPO_REPORT = ROOT / "docs" / "releases" / "v0.4-cross-repo-readiness-report.json"
PUBLIC_LEDGER = ROOT / "docs" / "releases" / "v0.4-public-blocker-closure-ledger.json"
EPICS_DOC = ROOT / "docs" / "rfcs" / "v0.4-implementation-epics.md"
RISK_REGISTER = ROOT / "docs" / "rfcs" / "v0.4-risk-register.md"
PLATFORM_RFC = ROOT / "docs" / "rfcs" / "v0.4-skillops-platform-rfc.md"
KNOWN_LIMITATIONS = ROOT / "docs" / "known-limitations.md"
README = ROOT / "README.md"
SECURITY = ROOT / "SECURITY.md"
CHANGELOG = ROOT / "CHANGELOG.md"

REQUIRED_BOUNDARIES = {
    "automatic_telemetry": False,
    "prompt_upload": False,
    "skill_body_upload": False,
    "automatic_rewriting": False,
    "auto_publish": False,
    "live_billing": False,
    "pypi_publication": False,
    "full_catalog_distribution": False,
    "mit_local_core_registration_required": False,
    "signed_hosted_manifests_required": True,
    "automatic_install_update_remove": False,
    "production_hosted_calls_in_tests": False,
}

REQUIRED_EPICS = {"V04-E01", "V04-E02", "V04-E03", "V04-E04"}
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
    raise SystemExit(f"v0.4 go/no-go verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))


def require_phrase(path: Path, phrase: str) -> None:
    require(phrase.lower() in read_text(path).lower(), f"{path.relative_to(ROOT)} missing phrase: {phrase}")


def assert_public_safe(path: Path) -> None:
    text = read_text(path)
    for pattern in FORBIDDEN_PATTERNS:
        require(pattern.search(text) is None, f"{path.relative_to(ROOT)} contains forbidden private marker: {pattern.pattern}")


def assert_decision_shape(decision: dict[str, Any]) -> None:
    require(decision.get("schema_version") == 1, "schema_version must be 1")
    require(decision.get("document") == "v0.4-go-no-go-decision", "unexpected document name")
    require(decision.get("decision") in {"GO", "NO_GO"}, "decision must be GO or NO_GO")
    require(decision.get("decision") == "GO", "this package should approve v0.4 implementation epic start")
    require(str(decision.get("approved_v04_vfp") or "").strip(), "approved v0.4 VFP is required")
    require(set(decision.get("evidence", {})) >= REQUIRED_BLOCKERS, "B-01..B-04 evidence is incomplete")

    for blocker_id in REQUIRED_BLOCKERS:
        blocker = decision["evidence"][blocker_id]
        require(blocker.get("status") == "closed", f"{blocker_id} must be closed")
        require(str(blocker.get("merge_sha") or "").strip(), f"{blocker_id} merge SHA is required")

    cross_repo = decision["evidence"].get("cross_repo_readiness", {})
    require(cross_repo.get("status") == "passed", "cross-repo readiness must pass")
    require(cross_repo.get("external_local_registry_checked") is True, "external local-registry evidence must be recorded")

    debt = decision.get("open_pr_debt", {})
    require(debt.get("status") == "clean", "open PR debt must be clean")
    require(debt.get("public_open_pr_count") == 0, "public open PR debt must be zero")
    require(debt.get("private_registry_open_pr_count") == 0, "private registry open PR debt must be zero")

    boundaries = decision.get("non_negotiable_boundaries", {})
    for key, expected in REQUIRED_BOUNDARIES.items():
        require(boundaries.get(key) is expected, f"boundary mismatch: {key}")

    epics = decision.get("first_four_implementation_epics", [])
    require({item.get("id") for item in epics} == REQUIRED_EPICS, "first four implementation epics mismatch")
    for epic in epics:
        require(str(epic.get("vfp") or "").strip(), f"epic {epic.get('id')} must include VFP")
        require(epic.get("repositories"), f"epic {epic.get('id')} must include repositories")
        require(epic.get("review_gates"), f"epic {epic.get('id')} must include review gates")

    require(decision.get("no_go_blockers") == [], "GO decision must have no no-go blockers")


def assert_linked_evidence(decision: dict[str, Any]) -> None:
    public_ledger = read_json(PUBLIC_LEDGER)
    cross_repo = read_json(CROSS_REPO_REPORT)
    require(public_ledger["blockers"]["B-02"]["status"] == "closed_on_public_main", "public B-02 ledger is not closed")
    require(cross_repo["status"] == "passed", "cross-repo report did not pass")
    require(cross_repo["implementation_approval"]["approved"] is False, "cross-repo report must not approve implementation")
    require(decision["evidence"]["B-02"]["merge_sha"] == public_ledger["public_main"]["merge_sha"], "B-02 merge SHA mismatch")
    require(cross_repo["checks"]["no_automatic_skill_rewriting"] is True, "cross-repo no-rewrite proof missing")
    require(cross_repo["checks"]["no_auto_publish"] is True, "cross-repo no-publish proof missing")


def assert_docs() -> None:
    for path in (
        DECISION_JSON,
        DECISION_MD,
        CROSS_REPO_REPORT,
        PUBLIC_LEDGER,
        EPICS_DOC,
        RISK_REGISTER,
        PLATFORM_RFC,
        KNOWN_LIMITATIONS,
        README,
        SECURITY,
        CHANGELOG,
    ):
        require(path.is_file(), f"missing required file: {path.relative_to(ROOT)}")
    require_phrase(DECISION_MD, "Decision: GO")
    require_phrase(EPICS_DOC, "V04-E01")
    require_phrase(RISK_REGISTER, "go/no-go")
    require_phrase(PLATFORM_RFC, "Cross-Repo Readiness Suite")
    require_phrase(KNOWN_LIMITATIONS, "v0.4 go/no-go")
    require_phrase(README, "v0.4 go/no-go")
    require_phrase(SECURITY, "v0.4 go/no-go")
    require_phrase(CHANGELOG, "v0.4 go/no-go")


def main() -> int:
    assert_docs()
    for path in (DECISION_JSON, DECISION_MD):
        assert_public_safe(path)
    decision = read_json(DECISION_JSON)
    assert_decision_shape(decision)
    assert_linked_evidence(decision)
    print("v0.4 go/no-go verification passed")
    print("decision: " + decision["decision"])
    print("epics: " + ", ".join(sorted(item["id"] for item in decision["first_four_implementation_epics"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
