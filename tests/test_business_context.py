from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from unlimited_skills import suggest
from unlimited_skills.business_context import (
    BusinessContextError,
    load_provider_config,
    provider_doctor,
    retrieve_business_context,
    submit_completion_candidate,
)
from unlimited_skills.search_core import save_index


PROVIDER_SOURCE = r'''
import json
import os
import sys
from pathlib import Path

request = json.load(sys.stdin)
Path(sys.argv[1]).write_text(json.dumps({"request": request, "secret_visible": bool(os.environ.get("SECRET_TOKEN")), "static_marker": os.environ.get("STATIC_MARKER"), "username": os.environ.get("USERNAME") or os.environ.get("USER") or os.environ.get("LOGNAME")}), encoding="utf-8")
operation = request["operation"]
response = {
    "schema_version": "unlimited-skills.business-context-response.v1",
    "request_id": request["request_id"],
}
if operation == "retrieve":
    if "нет контекста" in request.get("query", ""):
        response.update({"status": "no_context", "items": [], "diagnostics": {"daemon_state": "ready"}})
    else:
        response.update({
        "status": "ok",
        "items": [
            {
                "id": "offer-1",
                "title": "Current offer rule",
                "excerpt": "Use the approved fixed-price offer and cite the canonical record.",
                "source_ref": "business/offers/current-offer.md",
                "sensitivity": "internal",
            },
            {
                "id": "private-1",
                "title": "Personal note",
                "excerpt": "Must never cross the business wall.",
                "source_ref": "personal/note.md",
                "sensitivity": "restricted",
            },
            {
                "id": "path-leak",
                "title": "Absolute path",
                "excerpt": "Must be dropped because the source ref is absolute.",
                "source_ref": "C:/private/vault/record.md",
                "sensitivity": "internal",
            },
        ],
        })
elif operation == "completion_candidate":
    completion = request["completion"]
    accepted = bool(completion.get("evidence_refs")) and "completed" in completion.get("summary", "").lower()
    response.update({
        "status": "accepted" if accepted else "ignored",
        "atom_id": "release-completion-atom" if accepted else None,
        "source_ref": "business/lessons/release-completion-atom.md" if accepted else None,
        "reason": "no evidence" if not accepted else None,
    })
elif operation == "doctor":
    response["status"] = "ok"
    response["diagnostics"] = {"daemon_state": "ready", "business_wall": "fixture"}
else:
    response["status"] = "ignored"
print(json.dumps(response))
'''


def write_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **provider_overrides) -> tuple[Path, Path]:
    script = tmp_path / "provider.py"
    log = tmp_path / "provider-request.json"
    script.write_text(PROVIDER_SOURCE, encoding="utf-8")
    provider = {
        "id": "fixture-company-memory",
        "command": [sys.executable, str(script), str(log)],
        "capabilities": ["retrieve", "completion_candidate", "doctor"],
        "timeout_seconds": 2,
        "max_context_chars": 3000,
        "scope": "fixture-business",
    }
    provider.update(provider_overrides)
    config = tmp_path / "business-context-provider.json"
    config.write_text(json.dumps({"schema_version": 1, "enabled": True, "provider": provider}), encoding="utf-8")
    monkeypatch.setenv("UNLIMITED_SKILLS_CONTEXT_PROVIDER_CONFIG", str(config))
    monkeypatch.delenv("UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT", raising=False)
    return config, log


def test_missing_provider_is_a_zero_noise_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_CONTEXT_PROVIDER_CONFIG", str(tmp_path / "missing.json"))
    report = retrieve_business_context("prepare a proposal")
    assert report == {
        "schema_version": 1,
        "status": "not_configured",
        "provider_id": None,
        "items": [],
        "context": "",
    }


def test_retrieval_is_bounded_filtered_and_does_not_inherit_secret_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, log = write_provider(tmp_path, monkeypatch, env={"STATIC_MARKER": "configured-value"})
    monkeypatch.setenv("SECRET_TOKEN", "must-not-reach-provider")
    monkeypatch.setenv("USERNAME", "fixture-user")

    report = retrieve_business_context("prepare the current customer offer", agent="test")

    assert report["status"] == "ok"
    assert report["provider_id"] == "fixture-company-memory"
    assert [item["id"] for item in report["items"]] == ["offer-1"]
    assert 'authority="retrieval_only"' in report["context"]
    assert 'disclosure="internal"' in report["context"]
    assert "business/offers/current-offer.md" in report["context"]
    assert "Personal note" not in report["context"]
    assert "C:/private" not in report["context"]
    recorded = json.loads(log.read_text(encoding="utf-8"))
    assert recorded["secret_visible"] is False
    assert recorded["static_marker"] == "configured-value"
    assert recorded["username"] == "fixture-user"
    assert recorded["request"]["operation"] == "retrieve"
    assert recorded["request"]["scope"] == "fixture-business"
    first_request_id = recorded["request"]["request_id"]
    retrieve_business_context("prepare the current customer offer", agent="test")
    second_request_id = json.loads(log.read_text(encoding="utf-8"))["request"]["request_id"]
    assert second_request_id != first_request_id


def test_invalid_config_and_provider_timeout_fail_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _ = write_provider(tmp_path, monkeypatch, timeout_seconds=99)
    with pytest.raises(BusinessContextError):
        load_provider_config(config)

    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text("import time; time.sleep(5)", encoding="utf-8")
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": {
                    "id": "slow-provider",
                    "command": [sys.executable, str(sleeper)],
                    "capabilities": ["retrieve"],
                    "timeout_seconds": 0.05,
                },
            }
        ),
        encoding="utf-8",
    )
    report = retrieve_business_context("bounded timeout")
    assert report["status"] == "unavailable"
    assert "Continue only with generic work" in report["context"]


def test_utf8_no_context_is_not_reported_as_verified_absence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, log = write_provider(tmp_path, monkeypatch)
    query = "нет контекста для этого решения"
    report = retrieve_business_context(query)
    assert report["status"] == "no_context"
    assert report["diagnostics"]["daemon_state"] == "ready"
    assert "not a verified not-found result" in report["context"]
    recorded = json.loads(log.read_text(encoding="utf-8"))
    assert recorded["request"]["query"] == query


def test_completion_is_provider_decided_and_idempotency_key_is_forwarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, log = write_provider(tmp_path, monkeypatch)
    ignored = submit_completion_candidate(
        {"completion_key": "turn-1", "summary": "We are still planning the work; nothing is finished yet.", "evidence_refs": []}
    )
    assert ignored["status"] == "ignored"

    accepted = submit_completion_candidate(
        {
            "completion_key": "turn-2",
            "summary": "Completed the release and verified the public wheel.",
            "evidence_refs": ["#238", "6c8a2b7", "C:/absolute/must-drop"],
            "agent": "test-agent",
            "cwd": str(tmp_path),
        }
    )
    assert accepted["status"] == "accepted"
    assert accepted["atom_id"] == "release-completion-atom"
    recorded = json.loads(log.read_text(encoding="utf-8"))["request"]
    assert recorded["operation"] == "completion_candidate"
    assert recorded["completion"]["completion_key"] == "turn-2"
    assert recorded["completion"]["evidence_refs"] == ["#238", "6c8a2b7"]


def test_doctor_and_suggest_card_share_the_same_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    write_provider(tmp_path, monkeypatch)
    library = tmp_path / "library"
    library.mkdir()
    save_index(library)

    doctor = provider_doctor()
    assert doctor["status"] == "ok"
    assert doctor["capabilities"] == ["completion_candidate", "doctor", "retrieve"]
    assert doctor["provider_diagnostics"] == {"daemon_state": "ready", "business_wall": "fixture"}

    assert suggest.main(["prepare current offer", "--root", str(library), "--json", "--card"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["delivery_tier"] == 1
    assert payload["business_context"]["status"] == "ok"
    assert "Current offer rule" in payload["business_context"]["context"]

    assert suggest.main(["prepare current customer offer", "--root", str(library), "--json"]) == 0
    plain_json = json.loads(capsys.readouterr().out)
    assert "business_context" not in plain_json


def test_plain_suggest_contract_is_unchanged_when_provider_is_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    write_provider(tmp_path, monkeypatch)
    library = tmp_path / "library"
    library.mkdir()
    save_index(library)

    assert suggest.main(["prepare current offer", "--root", str(library)]) == 0
    assert capsys.readouterr().out == ""


def test_business_context_kill_switch_skips_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, log = write_provider(tmp_path, monkeypatch)
    monkeypatch.setenv("UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT", "1")
    report = retrieve_business_context("prepare current offer")
    assert report["status"] == "not_configured"
    assert not log.exists()
