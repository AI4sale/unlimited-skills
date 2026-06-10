from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from unlimited_skills.cli import main
from unlimited_skills.skill_improvements import SkillImprovementClient, SkillImprovementError

from test_catalog_browser import FakeResponse, registered_state, sign_catalog_payload, trust_test_key, write_registration


ITEM_ID = "community:browser-qa-pack:0.1.0"


def improvement_status() -> dict:
    return {
        "item_id": ITEM_ID,
        "installed_version": "0.1.0",
        "latest_version": "0.2.0",
        "recommended_version": "0.2.0",
        "recommended_channel": "stable",
        "open_issue_count": 3,
        "severity_summary": {"critical": 1, "high": 1, "medium": 1},
        "fix_status": "fixed",
        "deprecated": False,
        "retired": False,
        "compatibility_notes": ["codex >=0.3.8", "claude-code ok"],
        "stale_installed_version": True,
        "update_available": True,
        "recommended_action": "update",
    }


def known_issues() -> dict:
    return {
        "item_id": ITEM_ID,
        "open_issue_count": 2,
        "severity_summary": {"high": 1, "medium": 1},
        "fix_status": "partial",
        "issues": [
            {
                "issue_id": "ISSUE-1",
                "severity": "high",
                "status": "open",
                "fix_status": "fixed",
                "title": "Installer compatibility warning",
                "fixed_in_version": "0.2.0",
                "compatibility_notes": ["codex ok"],
            },
            {"issue_id": "ISSUE-2", "severity": "medium", "status": "open", "fix_status": "pending", "title": "Docs need refresh"},
        ],
        "compatibility_notes": ["hermes requires router refresh"],
    }


def recommendation(item_id: str = ITEM_ID, *, action: str = "update") -> dict:
    return {
        "item_id": item_id,
        "installed_version": "0.1.0",
        "recommended_version": "0.2.0",
        "recommended_channel": "stable",
        "recommended_action": action,
        "reason": "Fixes signed high severity known issue metadata.",
        "open_issue_count": 2,
        "severity_summary": {"high": 1, "medium": 1},
        "fix_status": "fixed",
        "deprecated": action == "remove",
        "retired": action == "remove",
        "stale_installed_version": True,
        "compatibility_notes": ["codex >=0.3.8"],
        "preview_only": True,
        "will_install": False,
        "will_update": False,
        "will_remove": False,
    }


def deprecation_status() -> dict:
    return {
        "item_id": ITEM_ID,
        "deprecated": True,
        "retired": False,
        "deprecation_reason": "Superseded by browser-qa-pack v0.2.0.",
        "retirement_reason": "",
        "replacement_item_id": "community:browser-qa-pack:0.2.0",
        "recommended_version": "0.2.0",
        "recommended_channel": "stable",
        "recommended_action": "update",
        "compatibility_notes": ["old command aliases remain supported"],
    }


def test_skill_improvement_commands_require_registration(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(tmp_path / ".unlimited-skills"))

    assert main(["catalog", "improvement-status", ITEM_ID]) == 2
    assert "Registration is required for hosted skill improvement status" in capsys.readouterr().err


def test_skill_improvement_commands_are_signed_and_preview_only(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    root = tmp_path / "library"
    write_registration(home)
    monkeypatch.setenv("UNLIMITED_SKILLS_HOME", str(home / ".unlimited-skills"))
    private_key = trust_test_key(monkeypatch)
    seen_urls: list[str] = []

    def fake_urlopen(request, timeout=30.0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        seen_urls.append(url)
        if url.endswith("/v1/catalog/improvements/status"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"improvement_status": improvement_status()}, private_key, manifest_type="skill-improvement-status")).encode(
                    "utf-8"
                )
            )
        if url.endswith("/v1/catalog/improvements/known-issues"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"known_issues": known_issues()}, private_key, manifest_type="skill-known-issues")).encode("utf-8")
            )
        if url.endswith("/v1/catalog/improvements/update-recommendations"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"recommendations": [recommendation()]}, private_key, manifest_type="update-recommendations")).encode("utf-8")
            )
        if url.endswith("/v1/catalog/improvements/update-preview"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"recommendation": recommendation()}, private_key, manifest_type="update-preview")).encode("utf-8")
            )
        if url.endswith("/v1/catalog/improvements/deprecation-status"):
            return FakeResponse(
                json.dumps(sign_catalog_payload({"deprecation_status": deprecation_status()}, private_key, manifest_type="deprecation-status")).encode("utf-8")
            )
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", fake_urlopen):
        assert main(["--root", str(root), "catalog", "improvement-status", ITEM_ID, "--json"]) == 0
        status = json.loads(capsys.readouterr().out)
        assert status["open_issue_count"] == 3
        assert status["severity_summary"]["critical"] == 1
        assert status["stale_installed_version"] is True
        assert status["privacy"]["skill_bodies_included"] is False

        assert main(["--root", str(root), "catalog", "known-issues", ITEM_ID, "--json"]) == 0
        issues = json.loads(capsys.readouterr().out)
        assert issues["issues"][0]["fixed_in_version"] == "0.2.0"

        assert main(["--root", str(root), "catalog", "update-recommendations", "--json"]) == 0
        recommendations = json.loads(capsys.readouterr().out)
        assert recommendations["preview_only"] is True
        assert recommendations["automatic_update"] is False
        assert recommendations["recommendations"][0]["will_update"] is False

        assert main(["--root", str(root), "catalog", "update-preview", ITEM_ID, "--json"]) == 0
        preview = json.loads(capsys.readouterr().out)
        assert preview["preview_only"] is True
        assert preview["privacy"]["automatic_remove"] is False

        assert main(["--root", str(root), "catalog", "deprecation-status", ITEM_ID, "--json"]) == 0
        deprecation = json.loads(capsys.readouterr().out)
        assert deprecation["deprecated"] is True
        assert deprecation["replacement_item_id"] == "community:browser-qa-pack:0.2.0"

    assert len(seen_urls) == 5


def test_skill_improvement_rejects_unsigned_sensitive_or_write_payload(tmp_path: Path, monkeypatch) -> None:
    private_key = trust_test_key(monkeypatch)
    client = SkillImprovementClient(registered_state())

    def unsigned_urlopen(request, timeout=30.0):
        return FakeResponse(json.dumps({"schema_version": 1, "manifest_type": "skill-improvement-status", "improvement_status": improvement_status()}).encode("utf-8"))

    with patch("urllib.request.urlopen", unsigned_urlopen):
        with pytest.raises(SkillImprovementError, match="manifest_signature"):
            client.improvement_status(tmp_path / "library", ITEM_ID)

    def sensitive_urlopen(request, timeout=30.0):
        payload = {"improvement_status": {**improvement_status(), "repo_path": "C:\\Users\\tedja\\private\\repo"}}
        return FakeResponse(json.dumps(sign_catalog_payload(payload, private_key, manifest_type="skill-improvement-status")).encode("utf-8"))

    with patch("urllib.request.urlopen", sensitive_urlopen):
        with pytest.raises(SkillImprovementError, match="disallowed field"):
            client.improvement_status(tmp_path / "library", ITEM_ID)

    def write_urlopen(request, timeout=30.0):
        payload = {"recommendation": {**recommendation(), "preview_only": False, "will_update": True}}
        return FakeResponse(json.dumps(sign_catalog_payload(payload, private_key, manifest_type="update-preview")).encode("utf-8"))

    with patch("urllib.request.urlopen", write_urlopen):
        with pytest.raises(SkillImprovementError, match="preview-only"):
            client.update_preview(tmp_path / "library", ITEM_ID)
