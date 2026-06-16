from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from scripts.verify_v064_money_saved_tier_smoke import (
    EXPECTED_SURFACES,
    RELEASE,
    REPORT_TYPE,
    run_smoke,
    validate_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v064_money_saved_tier_smoke_passes(tmp_path: Path) -> None:
    report = run_smoke(tmp_path / "smoke")

    assert report["ok"] is True
    assert report["release"] == RELEASE
    assert report["report_type"] == REPORT_TYPE
    assert report["privacy"]["no_egress_asserted"] is True
    assert report["claims"]["dollars_disabled_by_default"] is True
    assert report["claims"]["tokens_are_estimates"] is True

    surfaces = set(report["surfaces_checked"])
    assert set(EXPECTED_SURFACES).issubset(surfaces)

    tamper = next(row for row in report["rows"] if row["surface"] == "money-saved evidence-pack tamper check")
    assert tamper["ok"] is True
    assert tamper["expected_success"] is False
    assert tamper["returncode"] != 0
    assert tamper["details"]["ok"] is False


def test_v064_money_saved_tier_smoke_validation_fails_for_missing_artifact(tmp_path: Path) -> None:
    report = run_smoke(tmp_path / "smoke")
    artifact_row = next(row for row in report["rows"] if row["artifact_paths"])
    artifact_row["artifact_paths"] = [str(tmp_path / "missing.json")]

    errors = validate_report(report)

    assert any("artifact missing" in error for error in errors)


def test_v064_money_saved_tier_smoke_validation_fails_for_bad_tamper_row(tmp_path: Path) -> None:
    report = run_smoke(tmp_path / "smoke")
    tamper = next(row for row in report["rows"] if row["surface"] == "money-saved evidence-pack tamper check")
    tamper["returncode"] = 0
    tamper["details"]["ok"] = True

    errors = validate_report(report)

    assert any("tamper row" in error for error in errors)


def test_v064_money_saved_tier_smoke_validation_fails_for_asserted_overclaim(tmp_path: Path) -> None:
    report = run_smoke(tmp_path / "smoke")
    admin_row = next(row for row in report["rows"] if row["surface"] == "money-saved admin-export")
    admin_json = REPO_ROOT / admin_row["artifact_paths"][0]
    payload = json.loads(admin_json.read_text(encoding="utf-8"))
    payload["claim_boundary"]["allowed_claims"] = ["exact money saved"]
    admin_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    errors = validate_report(report)

    assert any("asserts forbidden claim" in error for error in errors)


def test_v064_money_saved_tier_smoke_validation_fails_for_enabled_dollars(tmp_path: Path) -> None:
    report = run_smoke(tmp_path / "smoke")
    team_row = next(row for row in report["rows"] if row["surface"] == "money-saved team-rollup")
    team_json = REPO_ROOT / team_row["artifact_paths"][0]
    payload = json.loads(team_json.read_text(encoding="utf-8"))
    payload["dollars"]["enabled"] = True
    team_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    errors = validate_report(report)

    assert any("dollars.enabled must stay false" in error for error in errors)


def test_v064_hyphenated_entrypoint_imports_underscore_main() -> None:
    verifier_path = REPO_ROOT / "scripts" / "verify-v064-money-saved-tier-smoke.py"
    spec = importlib.util.spec_from_file_location("verify_v064_money_saved_tier_smoke_shim_test", verifier_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.main)
