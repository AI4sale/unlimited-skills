from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from unlimited_skills.cli import main
from unlimited_skills.maintainer_queue_status import MaintainerQueueStatusClient, MaintainerQueueStatusError

from test_catalog_browser import FakeResponse, registered_state, sign_catalog_payload, trust_test_key, write_registration
from test_skill_improvement_status import ITEM_ID, improvement_status, recommendation


def queue_status(item_id: str = ITEM_ID) -> dict:
    return {
        "item_id": item_id,
        "queue_status": "fixed_pending_eval",
        "severity_summary": {"critical": 1, "high": 1},
        "maintainer_state": "public_fix_ready",
        "fixed_pending_eval_evidence_ref": "evidence:mq-123",
        "eval_gate_ref": "eval-gate:quality-regression-v1",
        "recommended_user_action": "wait_for_eval",
        "issue_categories": ["runtime_error", "docs_gap"],
        "updated_at": "2026-06-10T08:00:00Z",
    }


def queue_summary() -> dict:
    return {
        "total_count": 7,
        "queue_status_counts": {"accepted": 2, "fixed_pending_eval": 3, "blocked": 2},
        "severity_summary": {"critical": 1, "high": 3, "medium": 3},
        "issue_categories": ["runtime_error", "docs_gap", "compatibility"],
        "maintainer_state_counts": {"triaged": 2, "public_fix_ready": 3, "blocked_public": 2},
        "fixed_pending_eval_count": 3,
        "blocked_eval_gate_count": 1,
        "recommended_user_actions": {"wait_for_eval": 3, "review_before_update": 4},
    }


def fixed_pending_eval() -> dict:
    return {
        "item_id": ITEM_ID,
        "fixed_pending_eval": True,
        "queue_status": "fixed_pending_eval",
        "severity_summary": {"critical": 1},
        "maintainer_state": "public_fix_ready",
        "evidence_ref": "evidence:mq-123",
        "eval_gate_ref": "eval-gate:quality-regression-v1",
        "recommended_user_action": "wait_for_eval",
        "issue_categories": ["runtime_error"],
    }


def test_maintainer_queue_commands_require_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["catalog", "maintainer-status", ITEM_ID]) == 2
    assert "Registration is required for hosted maintainer queue status" in capsys.readouterr().err


def test_maintainer_queue_commands_are_signed_metadata_only(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    private_key = trust_test_key(monkeypatch)
    seen_urls: list[str] = []

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        seen_urls.append(url)
        if url.endswith("/v1/catalog/maintainer-queue/status"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"queue_status": queue_status()}, private_key, manifest_type="maintainer-queue-status-client")).encode("utf-8")
            )
        if url.endswith("/v1/catalog/maintainer-queue/summary"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"queue_summary": queue_summary()}, private_key, manifest_type="maintainer-queue-status-client")).encode("utf-8")
            )
        if url.endswith("/v1/catalog/maintainer-queue/fixed-pending-eval"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"fixed_pending_eval": fixed_pending_eval()}, private_key, manifest_type="fixed-pending-eval-status")).encode(
                    "utf-8"
                )
            )
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["--root", str(root), "catalog", "maintainer-status", ITEM_ID, "--json"]) == 0
        status = json.loads(capsys.readouterr().out)
        assert status["queue_status"] == "fixed_pending_eval"
        assert status["maintainer_state"] == "public_fix_ready"
        assert status["fixed_pending_eval_evidence_ref"] == "evidence:mq-123"
        assert status["eval_gate_ref"] == "eval-gate:quality-regression-v1"
        assert status["recommended_user_action"] == "wait_for_eval"
        assert status["privacy"]["skill_bodies_included"] is False
        assert status["privacy"]["maintainer_private_notes_included"] is False

        assert main(["--root", str(root), "catalog", "maintainer-queue-summary", "--json"]) == 0
        summary = json.loads(capsys.readouterr().out)
        assert summary["total_count"] == 7
        assert summary["queue_status_counts"]["fixed_pending_eval"] == 3
        assert summary["issue_categories"] == ["runtime_error", "docs_gap", "compatibility"]
        assert summary["privacy"]["summary_counts_only"] is True

        assert main(["--root", str(root), "catalog", "fixed-pending-eval", ITEM_ID, "--json"]) == 0
        fixed = json.loads(capsys.readouterr().out)
        assert fixed["fixed_pending_eval"] is True
        assert fixed["evidence_ref"] == "evidence:mq-123"
        assert fixed["eval_gate_ref"] == "eval-gate:quality-regression-v1"

    assert len(seen_urls) == 3


def test_include_queue_extends_improvement_and_recommendation_preview(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    private_key = trust_test_key(monkeypatch)

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/v1/catalog/improvements/status"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"improvement_status": improvement_status()}, private_key, manifest_type="skill-improvement-status")).encode(
                    "utf-8"
                )
            )
        if url.endswith("/v1/catalog/improvements/update-recommendations"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"recommendations": [recommendation()]}, private_key, manifest_type="update-recommendations")).encode("utf-8")
            )
        if url.endswith("/v1/catalog/maintainer-queue/status"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"queue_status": queue_status()}, private_key, manifest_type="maintainer-queue-status-client")).encode("utf-8")
            )
        if url.endswith("/v1/catalog/maintainer-queue/summary"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"queue_summary": queue_summary()}, private_key, manifest_type="maintainer-queue-status-client")).encode("utf-8")
            )
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["--root", str(root), "catalog", "improvement-status", ITEM_ID, "--include-queue", "--json"]) == 0
        status = json.loads(capsys.readouterr().out)
        assert status["recommended_action"] == "update"
        assert status["maintainer_queue"]["queue_status"] == "fixed_pending_eval"
        assert status["maintainer_queue"]["recommended_user_action"] == "wait_for_eval"

        assert main(["--root", str(root), "catalog", "update-recommendations", "--include-queue", "--json"]) == 0
        recommendations = json.loads(capsys.readouterr().out)
        assert recommendations["preview_only"] is True
        assert recommendations["automatic_update"] is False
        assert recommendations["include_queue"] is True
        assert recommendations["maintainer_queue_summary"]["fixed_pending_eval_count"] == 3
        assert recommendations["recommendations"][0]["will_update"] is False
        assert recommendations["recommendations"][0]["maintainer_queue_status"]["queue_status"] == "fixed_pending_eval"


def test_maintainer_queue_rejects_unsigned_or_sensitive_payload(tmp_path: Path, monkeypatch) -> None:
    private_key = trust_test_key(monkeypatch)
    client = MaintainerQueueStatusClient(registered_state())

    def unsigned_urlopen(request, timeout=30.0):
        return FakeResponse(json.dumps({"schema_version": 1, "manifest_type": "maintainer-queue-status-client", "queue_status": queue_status()}).encode("utf-8"))

    with patch("urllib.request.urlopen", unsigned_urlopen):
        with pytest.raises(MaintainerQueueStatusError, match="manifest_signature"):
            client.status(tmp_path / "library", ITEM_ID)

    def sensitive_urlopen(request, timeout=30.0):
        payload = {"queue_status": {**queue_status(), "maintainer_private_notes": "private task text C:\\Users\\tedja\\private"}}
        return FakeResponse(json.dumps(sign_catalog_payload(payload, private_key, manifest_type="maintainer-queue-status-client")).encode("utf-8"))

    with patch("urllib.request.urlopen", sensitive_urlopen):
        with pytest.raises(MaintainerQueueStatusError, match="disallowed field"):
            client.status(tmp_path / "library", ITEM_ID)
