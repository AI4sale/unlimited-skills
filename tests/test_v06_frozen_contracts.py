from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "verify-v06-frozen-contracts.py"


def run_harness(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def test_v06_frozen_contract_harness_passes_all_current_tree_surfaces() -> None:
    proc = run_harness("--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)

    assert report["schema_version"] == 1
    assert report["report_type"] == "v06_frozen_contracts"
    assert report["ok"] is True
    assert report["expected_version"] == "0.6.8"
    assert report["status_counts"] == {"pass": 11}

    expected_surfaces = {
        "version",
        "quickstart_json",
        "suggest_json",
        "mcp_install_dry_run",
        "mcp_savings_json",
        "feedback_prepare_json",
        "learning_summary_events_json",
        "roi_receipt_markdown",
        "roi_receipt_json",
        "roi_receipt_since_7d",
        "signal_rollup_fixture",
    }
    rows = report["rows"]
    assert {row["surface"] for row in rows} == expected_surfaces
    assert all(row["status"] == "pass" for row in rows)
    assert any(row["command"] == "unlimited-skills learning-summary --events --json" for row in rows)
    assert any(row["command"] == "unlimited-skills roi receipt --format json" for row in rows)
    assert any(row["command"] == "python scripts/generate-public-alpha-signal-rollup.py --fixture-mode --out <tmp>" for row in rows)


def test_v06_frozen_contract_harness_reports_drift_with_owner_action_fallback() -> None:
    proc = run_harness("--only", "version", "--expected-version", "9.9.9", "--json")
    assert proc.returncode == 1
    report = json.loads(proc.stdout)

    assert report["ok"] is False
    assert report["status_counts"] == {"drift": 1}
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["surface"] == "version"
    assert row["status"] == "drift"
    assert row["owner"] == "release owner"
    assert "Fix the frozen contract drift" in row["action"]
    assert "Keep the release gate blocked" in row["fallback"]
    assert row["evidence"]["reason"] == "version output mismatch"
