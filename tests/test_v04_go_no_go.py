from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / "docs" / "releases" / "v0.4-go-no-go-decision.json"
DECISION_MD = ROOT / "docs" / "releases" / "v0.4-go-no-go-decision.md"
EPICS = ROOT / "docs" / "rfcs" / "v0.4-implementation-epics.md"


def load_decision() -> dict:
    return json.loads(DECISION.read_text(encoding="utf-8"))


def test_v04_go_no_go_decision_is_go_with_closed_blockers_and_clean_pr_debt() -> None:
    payload = load_decision()

    assert payload["decision"] == "GO"
    assert payload["open_pr_debt"]["public_open_pr_count"] == 0
    assert payload["open_pr_debt"]["private_registry_open_pr_count"] == 0
    assert payload["open_pr_debt"]["status"] == "clean"
    assert {key for key in payload["evidence"] if key.startswith("B-")} == {"B-01", "B-02", "B-03", "B-04"}
    for blocker_id in ("B-01", "B-02", "B-03", "B-04"):
        assert payload["evidence"][blocker_id]["status"] == "closed"
        assert payload["evidence"][blocker_id]["merge_sha"]
    assert payload["evidence"]["cross_repo_readiness"]["status"] == "passed"
    assert payload["evidence"]["cross_repo_readiness"]["external_local_registry_checked"] is True


def test_v04_go_no_go_boundaries_are_non_negotiable() -> None:
    boundaries = load_decision()["non_negotiable_boundaries"]

    assert boundaries["automatic_telemetry"] is False
    assert boundaries["prompt_upload"] is False
    assert boundaries["skill_body_upload"] is False
    assert boundaries["automatic_rewriting"] is False
    assert boundaries["auto_publish"] is False
    assert boundaries["live_billing"] is False
    assert boundaries["pypi_publication"] is False
    assert boundaries["full_catalog_distribution"] is False
    assert boundaries["mit_local_core_registration_required"] is False
    assert boundaries["signed_hosted_manifests_required"] is True
    assert boundaries["automatic_install_update_remove"] is False
    assert boundaries["production_hosted_calls_in_tests"] is False


def test_v04_go_no_go_first_epics_are_defined_with_vfp_repositories_and_reviews() -> None:
    payload = load_decision()
    epics = {item["id"]: item for item in payload["first_four_implementation_epics"]}

    assert set(epics) == {"V04-E01", "V04-E02", "V04-E03", "V04-E04"}
    for epic in epics.values():
        assert epic["title"]
        assert epic["vfp"]
        assert epic["repositories"]
        assert epic["review_gates"]

    text = EPICS.read_text(encoding="utf-8")
    for epic_id in epics:
        assert epic_id in text
    assert "Do not accumulate another large open PR stack" in text


def test_v04_go_no_go_markdown_and_verifier_pass() -> None:
    assert "Decision: GO" in DECISION_MD.read_text(encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "scripts/verify-v04-go-no-go.py"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "v0.4 go/no-go verification passed" in completed.stdout
