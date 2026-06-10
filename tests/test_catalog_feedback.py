from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from unlimited_skills.catalog_feedback import CatalogFeedbackError, build_feedback_payload
from unlimited_skills.cli import main

from test_catalog_browser import write_registration


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._stream = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def test_catalog_feedback_requires_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["catalog", "feedback", "community:browser-qa-pack:0.1.0", "--type", "install_failure", "--dry-run"]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["dry_run"] is True

    assert main(["catalog", "feedback-status", "community:browser-qa-pack:0.1.0"]) == 2
    assert "Registration is required for hosted catalog feedback" in capsys.readouterr().err


def test_catalog_feedback_submit_and_status(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    seen_payloads: list[dict] = []

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        payload = json.loads(request.data.decode("utf-8"))
        seen_payloads.append(payload)
        if url.endswith("/v1/catalog/feedback/submit"):
            return FakeResponse({"schema_version": 1, "feedback_id": "cfb_test", "status": "received", "triage_status": "new"})
        if url.endswith("/v1/catalog/feedback/summary"):
            return FakeResponse(
                {
                    "schema_version": 1,
                    "feedback_count": 1,
                    "counts_by_type": {"install_failure": 1},
                    "counts_by_status": {"new": 1},
                    "counts_by_severity": {"high": 1},
                    "privacy": {"explicit_feedback_only": True, "automatic_telemetry": False, "skill_bodies_included": False},
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        assert (
            main(
                [
                    "catalog",
                    "feedback",
                    "community:browser-qa-pack:0.1.0",
                    "--type",
                    "install_failure",
                    "--severity",
                    "high",
                    "--title",
                    "Install plan unavailable",
                    "--error-code",
                    "install_plan_missing",
                    "--http-status",
                    "404",
                    "--yes",
                    "--json",
                ]
            )
            == 0
        )
        submitted = json.loads(capsys.readouterr().out)
        assert submitted["feedback_id"] == "cfb_test"

        assert main(["catalog", "feedback-status", "community:browser-qa-pack:0.1.0", "--json"]) == 0
        status = json.loads(capsys.readouterr().out)
        assert status["feedback_count"] == 1

    assert seen_payloads[0]["feedback_type"] == "install_failure"
    assert seen_payloads[0]["detail"]["error_code"] == "install_plan_missing"
    serialized = json.dumps(seen_payloads, sort_keys=True)
    assert "license_token" not in serialized
    assert "device_private_key" not in serialized
    assert "skill_body" not in serialized


def test_catalog_feedback_rejects_sensitive_detail() -> None:
    with pytest.raises(CatalogFeedbackError):
        build_feedback_payload(
            item_id="community:browser-qa-pack:0.1.0",
            feedback_type="security_concern",
            detail={"actual_behavior": "token uls_token_1234567890abcdef leaked"},
        )
    with pytest.raises(CatalogFeedbackError):
        build_feedback_payload(
            item_id="community:browser-qa-pack:0.1.0",
            feedback_type="security_concern",
            detail={"actual_behavior": "see C:/Users/alice/project"},
        )
