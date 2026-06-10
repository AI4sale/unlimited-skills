from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from unlimited_skills.recommendation_policy import (
    DENIAL_OUTCOMES,
    PRIVATE_DATA_KEYS,
    decision_table,
    refusal_code_contract,
)


ROOT = Path(__file__).resolve().parents[1]
LEDGER_JSON = ROOT / "docs" / "releases" / "v0.4-public-blocker-closure-ledger.json"
LEDGER_MD = ROOT / "docs" / "releases" / "v0.4-public-blocker-closure-ledger.md"
POLICY_DOC = ROOT / "docs" / "policy-aware-recommendations.md"
SUPPORT_DOC = ROOT / "docs" / "support-diagnostic-bundle.md"
CORE_DOC = ROOT / "docs" / "public-core-boundary.md"
RISK_REGISTER = ROOT / "docs" / "rfcs" / "v0.4-risk-register.md"
CHANGELOG = ROOT / "CHANGELOG.md"

EXPECTED_MERGE_SHA = "ff518157916d9312f5ca51217b6088ae97ae661e"
EXPECTED_REFUSAL_CODES = {
    "registration_required",
    "entitlement_denied",
    "policy_denied",
    "blocked_item",
    "retired_item",
    "low_score",
    "wrong_channel",
    "wrong_agent",
    "unsigned_metadata",
    "local_only",
}
FORBIDDEN_REPORT_PATTERNS = (
    re.compile(r"\b[A-Za-z]:[\\/][^\s\"`|]+"),
    re.compile(r"(?<![\w-])/(?:home|Users|root|var|opt|srv|mnt)/[^\s\"`|]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\buls_(?:hub|token|license)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*(?:PRIVATE|OPENSSH) KEY-----", re.IGNORECASE),
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"v0.4 public blocker closure verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def require_phrase(text: str, phrase: str, source: str) -> None:
    require(phrase.lower() in text.lower(), f"{source} missing phrase: {phrase}")


def assert_git_commit_present(sha: str) -> None:
    result = subprocess.run(
        ["git", "cat-file", "-t", sha],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    require(result.returncode == 0 and result.stdout.strip() == "commit", f"merge SHA is not present locally: {sha}")


def assert_ledger_shape(ledger: dict[str, Any]) -> None:
    require(ledger["ledger"] == "v0.4-public-blocker-closure", "unexpected ledger name")
    require(ledger["implementation_approval"]["approved"] is False, "ledger must not approve v0.4 implementation")
    require("final go/no-go" in ledger["implementation_approval"]["reason"], "ledger must require final go/no-go")
    require(ledger["public_main"]["repository"] == "AI4sale/unlimited-skills", "unexpected public repository")
    require(ledger["public_main"]["base_branch"] == "main", "unexpected base branch")
    require(ledger["public_main"]["merged_pr"] == 69, "ledger must record public PR #69")
    require(ledger["public_main"]["merge_sha"] == EXPECTED_MERGE_SHA, "ledger must record the PR #69 merge SHA")
    require(ledger["public_main"]["verified_on_main"] is True, "public main verification must be recorded")

    b02 = ledger["blockers"]["B-02"]
    require(b02["status"] == "closed_on_public_main", "B-02 must be closed on public main")
    require(b02["vfp_delivered"] is True, "B-02 VFP must be marked delivered")
    for evidence in ("deterministic recommendation decision table", "stable refusal-code vocabulary", "recommendation policy tests"):
        require(evidence in b02["evidence"], f"B-02 evidence missing: {evidence}")

    boundaries = ledger["public_safety_boundaries"]
    require(boundaries["recommendation_outcomes_preview_or_decision_only"] is True, "recommendations must stay preview/decision-only")
    require(boundaries["recommendation_paths_apply_changes_automatically"] is False, "recommendations must not apply changes")
    require(boundaries["mit_local_core_requires_registration"] is False, "MIT local core must remain registration-free")
    require(
        boundaries["hosted_recommendation_metadata_requires_signed_response_where_applicable"] is True,
        "hosted recommendation metadata must require signed responses where applicable",
    )
    require(boundaries["support_bundle_counts_and_status_only"] is True, "support bundle must be counts/status only")
    require(boundaries["support_bundle_contains_payload_content"] is False, "support bundle must not contain payload content")
    require(set(ledger["refusal_code_coverage"]) == EXPECTED_REFUSAL_CODES, "refusal code coverage mismatch")
    require(len(ledger["verification_evidence"]) >= 8, "ledger must record required verification gates")
    for gate in ledger["verification_evidence"]:
        require(gate["status"] == "passed", f"verification gate must be passed: {gate['name']}")
        require(str(gate.get("result") or "").strip(), f"verification gate must record a result: {gate['name']}")
    require(any(risk["severity"] == "P0" for risk in ledger["residual_risks"]), "ledger must record residual P0 risk")


def assert_recommendation_contract() -> None:
    decisions = decision_table()
    refusals = refusal_code_contract()
    require(set(decisions["denial_outcomes"]) == set(DENIAL_OUTCOMES), "denial outcome set mismatch")
    require({item["code"] for item in refusals["refusal_codes"]} == EXPECTED_REFUSAL_CODES, "refusal code contract mismatch")
    for payload in (decisions, refusals):
        require(payload["fixture_only"] is True, "recommendation contract must be fixture-only")
        require(payload["preview_only"] is True, "recommendation contract must be preview-only")
        require(payload["automatic_install"] is False, "recommendation contract must not auto-install")
        require(payload["automatic_update"] is False, "recommendation contract must not auto-update")
        require(payload["automatic_remove"] is False, "recommendation contract must not auto-remove")
        require(payload["hosted_query_forwarding"] is False, "recommendation contract must not forward hosted queries automatically")

    for decision in decisions["decisions"]:
        require(decision["will_install"] is False, f"decision may install automatically: {decision['case']}")
        require(decision["will_update"] is False, f"decision may update automatically: {decision['case']}")
        require(decision["will_remove"] is False, f"decision may remove automatically: {decision['case']}")
        if decision["outcome"] in DENIAL_OUTCOMES:
            require(decision.get("refusal_code") in EXPECTED_REFUSAL_CODES, f"missing refusal code: {decision['case']}")


def assert_docs() -> None:
    policy = read_text(POLICY_DOC)
    support = read_text(SUPPORT_DOC)
    core = read_text(CORE_DOC)
    risk = read_text(RISK_REGISTER)
    changelog = read_text(CHANGELOG)
    ledger_md = read_text(LEDGER_MD)

    for phrase in (
        "preview or decision-only",
        "No recommendation command applies an install, update, or remove operation automatically",
        "Hosted recommendation metadata that affects install or update advice must be signed",
        "MIT local core remains registration-free",
    ):
        require_phrase(policy, phrase, "policy-aware recommendations doc")

    for phrase in (
        "counts, booleans, status strings, and redacted summaries only",
        "No prompt or task content",
        "local or repository locations",
    ):
        require_phrase(support, phrase, "support diagnostic bundle doc")

    for phrase in (
        "MIT local core remains registration-free",
        "No recommendation path may install, update, remove, rewrite, reindex, or submit skills automatically",
        "Hosted recommendation metadata that influences install or update advice must arrive in signed responses",
    ):
        require_phrase(core, phrase, "public core boundary doc")

    require_phrase(risk, "B-02 is closed for public readiness", "risk register")
    require_phrase(risk, "not approve v0.4 implementation", "risk register")
    require_phrase(changelog, "v0.4 public blocker closure ledger", "changelog")
    require_phrase(ledger_md, "v0.4 implementation remains unapproved until the final go/no-go review passes", "ledger markdown")


def assert_report_redaction() -> None:
    def walk_keys(value: Any, *, source: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                require(str(key).lower() not in PRIVATE_DATA_KEYS, f"{source} contains private data key: {key}")
                walk_keys(item, source=source)
        elif isinstance(value, list):
            for item in value:
                walk_keys(item, source=source)

    walk_keys(json.loads(read_text(LEDGER_JSON)), source=LEDGER_JSON.name)
    for path in (LEDGER_JSON, LEDGER_MD):
        text = read_text(path)
        for pattern in FORBIDDEN_REPORT_PATTERNS:
            require(pattern.search(text) is None, f"{path.name} contains forbidden private marker")


def main() -> int:
    for path in (LEDGER_JSON, LEDGER_MD, POLICY_DOC, SUPPORT_DOC, CORE_DOC, RISK_REGISTER, CHANGELOG):
        require(path.is_file(), f"missing required file: {path.relative_to(ROOT)}")
    ledger = json.loads(read_text(LEDGER_JSON))
    assert_ledger_shape(ledger)
    assert_git_commit_present(EXPECTED_MERGE_SHA)
    assert_recommendation_contract()
    assert_docs()
    assert_report_redaction()
    print("v0.4 public blocker closure verification passed")
    print("B-02 status: closed on public main")
    print("PR #69 merge SHA: " + EXPECTED_MERGE_SHA)
    print("v0.4 implementation approved: false")
    print("final go/no-go required: true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
