from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_verifier():
    path = ROOT / "scripts" / "verify-v060-alpha-publication.py"
    spec = importlib.util.spec_from_file_location("verify_v060_alpha_publication_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_package_smoke() -> dict:
    return {
        "ok": True,
        "errors": [],
        "dist": {"wheel_skill_count": 267},
        "clean_install": {
            "quickstart_library": {"skill_count": 267},
            "version_output": "unlimited-skills 0.6.1",
            "suggest_candidates": 3,
        },
        "clean_install_adoption_tools": {
            "mcp_install_action": "would_write_claude_config",
            "feedback_report_type": "feedback_export",
            "effectiveness_suggest_count": 3,
        },
        "signal_rollup_fixture": {"created": True},
        "clean_install_local_event_privacy": {
            "event_count": 2,
            "feedback_count": 1,
            "contains_forbidden_needles": {"query": False, "task": False, "path": False},
        },
        "clean_install_roi_receipt": {
            "json_report_type": "local_roi_receipt",
            "json_schema_version": 1,
            "contains_forbidden_needles": {"query": False, "task": False, "path": False},
            "markdown_has_notice": True,
            "out_status_path_leak": False,
            "since_7d": True,
            "legacy_unavailable": True,
        },
    }


def patch_lightweight_verifier(monkeypatch, verifier) -> None:
    monkeypatch.setattr(verifier, "assert_clean_worktree", lambda: None)
    monkeypatch.setattr(verifier, "assert_metadata", lambda: None)
    monkeypatch.setattr(verifier, "assert_manifest", lambda: {"required_prs": {}, "excluded_prs": [119]})
    monkeypatch.setattr(verifier, "assert_docs", lambda: None)
    monkeypatch.setattr(verifier, "tag_exists", lambda tag: False)
    monkeypatch.setattr(verifier, "git_head", lambda: "a" * 40)
    monkeypatch.setattr(verifier, "run_package_smoke", sample_package_smoke)


def test_v060_publication_verifier_reports_frozen_contract_pass(monkeypatch, capsys) -> None:
    verifier = load_verifier()
    patch_lightweight_verifier(monkeypatch, verifier)
    called = {"frozen_contracts": False}

    def frozen_contracts_pass() -> dict:
        called["frozen_contracts"] = True
        return {
            "ok": True,
            "status_counts": {"pass": 11},
            "surfaces": ["learning_summary_events_json", "roi_receipt_json", "signal_rollup_fixture"],
            "failing_rows": [],
        }

    monkeypatch.setattr(verifier, "run_frozen_contracts", frozen_contracts_pass)

    rc = verifier.main(["--package-availability", "prepublish", "--allow-dirty", "--json"])

    assert rc == 0
    assert called["frozen_contracts"] is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert payload["frozen_contracts"]["ok"] is True
    assert payload["frozen_contracts"]["status_counts"] == {"pass": 11}
    assert "learning_summary_events_json" in payload["frozen_contracts"]["surfaces"]
    assert "roi_receipt_json" in payload["frozen_contracts"]["surfaces"]
    assert "signal_rollup_fixture" in payload["frozen_contracts"]["surfaces"]
    assert payload["tag_status"] == "blocked_until_pypi_upload_and_post_publish_smoke"


def test_v060_publication_verifier_blocks_on_frozen_contract_drift(monkeypatch, capsys) -> None:
    verifier = load_verifier()
    patch_lightweight_verifier(monkeypatch, verifier)

    monkeypatch.setattr(
        verifier,
        "run_frozen_contracts",
        lambda: {
            "ok": False,
            "status_counts": {"pass": 10, "drift": 1},
            "surfaces": ["learning_summary_events_json"],
            "failing_rows": [
                {
                    "surface": "learning_summary_events_json",
                    "status": "drift",
                    "owner": "release owner",
                    "action": "Restore JSON output.",
                    "fallback": "Do not tag.",
                }
            ],
            "blocker": verifier.frozen_contract_blocker(
                "release_blocked_frozen_contract_drift",
                {"failing_rows": [{"surface": "learning_summary_events_json", "status": "drift"}]},
            ),
        },
    )

    rc = verifier.main(["--package-availability", "prepublish", "--allow-dirty", "--json"])

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["blocker"]["code"] == "release_blocked_frozen_contract_drift"
    assert payload["blocker"]["owner"] == "release owner"
    assert "Fix the frozen v0.6 public contract drift" in payload["blocker"]["action"]
    assert "do not publish or tag" in payload["blocker"]["fallback"]
    assert payload["frozen_contracts"]["status_counts"] == {"pass": 10, "drift": 1}
    assert payload["frozen_contracts"]["failing_rows"][0]["surface"] == "learning_summary_events_json"


def test_published_mode_still_blocks_when_frozen_contracts_fail(monkeypatch, capsys) -> None:
    verifier = load_verifier()
    patch_lightweight_verifier(monkeypatch, verifier)
    monkeypatch.setattr(
        verifier,
        "run_frozen_contracts",
        lambda: {
            "ok": False,
            "status_counts": {"blocked": 1},
            "surfaces": ["roi_receipt_json"],
            "failing_rows": [{"surface": "roi_receipt_json", "status": "blocked"}],
            "blocker": verifier.frozen_contract_blocker(
                "release_blocked_frozen_contract_harness_failed",
                {"stderr_tail": "forced failure"},
            ),
        },
    )
    monkeypatch.setattr(
        verifier,
        "published_install_smoke",
        lambda: {
            "ok": True,
            "version_output": "unlimited-skills 0.6.1",
            "roi_receipt_json_type": "local_roi_receipt",
            "roi_receipt_markdown_has_notice": True,
        },
    )

    rc = verifier.main(["--package-availability", "published", "--allow-dirty", "--allow-existing-tag", "--json"])

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["blocker"]["code"] == "release_blocked_frozen_contract_harness_failed"
    assert payload["published_install_smoke"]["ok"] is True
    assert "tag_command" not in payload
