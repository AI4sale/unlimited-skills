from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from unlimited_skills.catalog_quality import CatalogQualityClient, CatalogQualityError
from unlimited_skills.cli import main

from test_catalog_browser import FakeResponse, catalog_item, registered_state, sign_catalog_payload, trust_test_key, write_registration


def quality_status(item_id: str = "community:browser-qa-pack:0.1.0", *, grade: str = "a", blocked: bool = False) -> dict:
    return {
        "item_id": item_id,
        "quality_grade": grade,
        "score_band": "90-100" if grade == "a" else "60-69",
        "last_eval_at": "2026-06-10T08:00:00Z",
        "blockers": ["malware_reported"] if blocked else [],
        "warnings": ["low_recent_success_rate"] if grade not in {"a", "b"} else [],
        "compatibility_notes": ["codex ok", "claude-code requires >=0.3.4"],
        "deprecation_status": "blocked" if blocked else "active",
        "retired": False,
        "feedback_issue_categories": ["install_failure", "documentation_issue"],
        "install_risk": "blocked" if blocked else ("warning" if grade not in {"a", "b"} else "low"),
        "install_allowed": not blocked,
    }


def eval_status() -> dict:
    return {
        "item_id": "community:browser-qa-pack:0.1.0",
        "evaluation_status": "passed",
        "quality_grade": "a",
        "score_band": "90-100",
        "last_eval_at": "2026-06-10T08:00:00Z",
        "next_eval_at": "2026-06-17T08:00:00Z",
        "evaluator_version": "catalog-eval-fixture-v1",
        "blockers": [],
        "warnings": [],
        "compatibility_notes": ["codex ok"],
        "feedback_issue_categories": ["install_failure"],
        "deprecation_status": "active",
        "retired": False,
    }


def test_catalog_quality_commands_require_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["catalog", "quality", "community:browser-qa-pack:0.1.0"]) == 2
    assert "Registration is required for hosted catalog quality" in capsys.readouterr().err


def test_catalog_quality_eval_and_explain_risk_are_signed(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    private_key = trust_test_key(monkeypatch)

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/catalog/quality/status"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"quality_status": quality_status(grade="c")}, private_key, manifest_type="catalog-quality-status")).encode(
                    "utf-8"
                )
            )
        if url.endswith("/v1/catalog/quality/eval-status"):
            return FakeResponse(json.dumps(sign_catalog_payload({"eval_status": eval_status()}, private_key, manifest_type="catalog-eval-status")).encode("utf-8"))
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["catalog", "quality", "community:browser-qa-pack:0.1.0", "--json"]) == 0
        quality = json.loads(capsys.readouterr().out)
        assert quality["quality_grade"] == "c"
        assert quality["feedback_issue_categories"] == ["install_failure", "documentation_issue"]

        assert main(["catalog", "eval-status", "community:browser-qa-pack:0.1.0", "--json"]) == 0
        evaluation = json.loads(capsys.readouterr().out)
        assert evaluation["evaluation_status"] == "passed"

        assert main(["catalog", "explain-risk", "community:browser-qa-pack:0.1.0", "--json"]) == 0
        risk = json.loads(capsys.readouterr().out)
        assert risk["warning"] is True
        assert risk["privacy"]["automatic_telemetry"] is False


def test_catalog_quality_rejects_unsigned_or_sensitive_payload(tmp_path: Path, monkeypatch) -> None:
    private_key = trust_test_key(monkeypatch)
    client = CatalogQualityClient(registered_state())

    def unsigned_urlopen(request, timeout=30.0):
        return FakeResponse(json.dumps({"quality_status": quality_status()}).encode("utf-8"))

    with patch("urllib.request.urlopen", unsigned_urlopen):
        with pytest.raises(CatalogQualityError):
            client.quality("community:browser-qa-pack:0.1.0")

    def sensitive_urlopen(request, timeout=30.0):
        payload = {"quality_status": {**quality_status(), "local_path": "C:\\Users\\tedja\\secret"}}
        return FakeResponse(json.dumps(sign_catalog_payload(payload, private_key, manifest_type="catalog-quality-status")).encode("utf-8"))

    with patch("urllib.request.urlopen", sensitive_urlopen):
        with pytest.raises(CatalogQualityError, match="disallowed field"):
            client.quality("community:browser-qa-pack:0.1.0")


def test_catalog_install_warns_for_low_grade_and_refuses_blocked(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    private_key = trust_test_key(monkeypatch)
    blocked = False

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/catalog/browser/item"):
            return FakeResponse(json.dumps(sign_catalog_payload({"item": catalog_item("published")}, private_key, manifest_type="catalog-browser-item")).encode("utf-8"))
        if url.endswith("/v1/catalog/quality/status"):
            return FakeResponse(
                json.dumps(
                    sign_catalog_payload(
                        {"quality_status": quality_status(grade="c", blocked=blocked)},
                        private_key,
                        manifest_type="catalog-quality-status",
                    )
                ).encode("utf-8")
            )
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["--root", str(root), "catalog", "install", "community:browser-qa-pack:0.1.0", "--dry-run", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["quality_grade"] == "c"
        assert "below the recommended threshold" in payload["quality_warning"]

        blocked = True
        assert main(["--root", str(root), "catalog", "install", "community:browser-qa-pack:0.1.0", "--dry-run", "--json"]) == 2
        assert "blocked for hosted install" in capsys.readouterr().err
