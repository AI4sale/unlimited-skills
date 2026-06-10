from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from unlimited_skills.recommendation_policy import decision_table, refusal_code_contract


ROOT = Path(__file__).resolve().parents[1]
LEDGER_JSON = ROOT / "docs" / "releases" / "v0.4-public-blocker-closure-ledger.json"
LEDGER_MD = ROOT / "docs" / "releases" / "v0.4-public-blocker-closure-ledger.md"


def load_ledger() -> dict:
    return json.loads(LEDGER_JSON.read_text(encoding="utf-8"))


def test_ledger_records_public_pr69_b02_closure_and_go_no_go_boundary() -> None:
    ledger = load_ledger()

    assert ledger["public_main"]["repository"] == "AI4sale/unlimited-skills"
    assert ledger["public_main"]["base_branch"] == "main"
    assert ledger["public_main"]["merged_pr"] == 69
    assert ledger["public_main"]["merge_sha"] == "ff518157916d9312f5ca51217b6088ae97ae661e"
    assert ledger["public_main"]["verified_on_main"] is True
    assert ledger["blockers"]["B-02"]["status"] == "closed_on_public_main"
    assert ledger["blockers"]["B-02"]["vfp_delivered"] is True
    assert ledger["implementation_approval"]["approved"] is False
    assert "final go/no-go" in ledger["implementation_approval"]["reason"]
    assert "v0.4 implementation remains unapproved until the final go/no-go review passes" in LEDGER_MD.read_text(
        encoding="utf-8"
    )


def test_ledger_matches_recommendation_refusal_contract_and_non_mutation_flags() -> None:
    ledger = load_ledger()
    decision_payload = decision_table()
    refusal_payload = refusal_code_contract()

    assert set(ledger["refusal_code_coverage"]) == {item["code"] for item in refusal_payload["refusal_codes"]}
    assert decision_payload["fixture_only"] is True
    assert decision_payload["preview_only"] is True
    assert decision_payload["automatic_install"] is False
    assert decision_payload["automatic_update"] is False
    assert decision_payload["automatic_remove"] is False
    assert decision_payload["hosted_query_forwarding"] is False
    for decision in decision_payload["decisions"]:
        assert decision["will_install"] is False
        assert decision["will_update"] is False
        assert decision["will_remove"] is False


def test_ledger_records_support_redaction_and_public_core_boundaries() -> None:
    ledger = load_ledger()
    boundaries = ledger["public_safety_boundaries"]

    assert boundaries["recommendation_outcomes_preview_or_decision_only"] is True
    assert boundaries["recommendation_paths_apply_changes_automatically"] is False
    assert boundaries["mit_local_core_requires_registration"] is False
    assert boundaries["hosted_recommendation_metadata_requires_signed_response_where_applicable"] is True
    assert boundaries["support_bundle_counts_and_status_only"] is True
    assert boundaries["support_bundle_contains_payload_content"] is False

    exposed = set(ledger["redaction_proof"]["support_diagnostics_expose"])
    assert {"counts", "booleans", "status strings", "redacted summaries"}.issubset(exposed)


def test_verifier_script_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/verify-v04-public-blocker-closure.py"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "v0.4 public blocker closure verification passed" in completed.stdout
