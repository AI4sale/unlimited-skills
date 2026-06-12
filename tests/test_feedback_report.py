from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from unlimited_skills.cli import main
from unlimited_skills.feedback import assert_feedback_report_safe, build_feedback_report, format_feedback_markdown


FORBIDDEN_VALUES = (
    "Prompt:",
    "customer task text",
    "SECRET_TOKEN_XYZ123",
    "C:\\Users\\tedja\\customer",
    "SKILL.md",
    "inputSchema",
)


def block_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("feedback prepare must not contact hosted services")


def write_skill(root: Path) -> None:
    skill = root / "local" / "skills" / "private-customer-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: private-customer-skill\ndescription: private\n---\n\n"
        "Prompt: customer task text SECRET_TOKEN_XYZ123 C:\\Users\\tedja\\customer\n",
        encoding="utf-8",
    )


def write_events(root: Path) -> None:
    events = root / ".learning" / "events.jsonl"
    events.parent.mkdir(parents=True, exist_ok=True)
    events.write_text(
        "\n".join(
            [
                json.dumps({"type": "suggest", "payload": {"reason_code": "match_found", "latency_ms": 123, "top_3_skill_candidates": [{"name": "private-customer-skill"}], "task_summary_hash": "abc"}}),
                json.dumps({"type": "quickstart", "payload": {"steps": {"import": "ok"}, "first_search_hit_count": 1, "mcp_savings_present": True}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".learning" / "feedback.jsonl").write_text(
        json.dumps({"name": "private-customer-skill", "query": "customer task text", "verdict": "accepted", "notes": "Prompt:"}) + "\n",
        encoding="utf-8",
    )


def assert_forbidden_absent(value: object, root: Path) -> None:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    for item in FORBIDDEN_VALUES:
        assert item not in serialized
    assert str(root) not in serialized
    assert_feedback_report_safe(value)


def test_feedback_report_is_local_only_and_redacted(tmp_path: Path) -> None:
    root = tmp_path / "library"
    write_skill(root)
    write_events(root)

    with patch("urllib.request.urlopen", block_network):
        report = build_feedback_report(root, include_usage_snapshot=False, generated_at="2026-06-12T00:00:00Z")

    assert report["local_only"] is True
    assert report["network_calls"] is False
    assert report["upload_available"] is False
    assert report["quickstart"]["status"] == "seen"
    assert report["suggest_effectiveness"]["event_count"] == 1
    assert report["local_learning_feedback"]["local_feedback_count"] == 1
    assert report["local_learning_feedback"]["skill_names_included"] is False
    assert report["mcp_savings"]["included"] is False
    assert_forbidden_absent(report, root)


def test_feedback_prepare_cli_json_markdown_doctor_and_legacy_record(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "library"
    monkeypatch.setenv("UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC", "1")
    write_skill(root)
    write_events(root)

    assert main(["--root", str(root), "feedback", "prepare"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["report_type"] == "feedback-prepare-report"
    assert_forbidden_absent(report, root)

    out = tmp_path / "feedback.md"
    assert main(["--root", str(root), "feedback", "prepare", "--format", "markdown", "--out", str(out)]) == 0
    assert "Feedback report written" in capsys.readouterr().out
    markdown = out.read_text(encoding="utf-8")
    assert "Unlimited Skills feedback report" in markdown
    for item in FORBIDDEN_VALUES:
        assert item not in markdown

    assert main(["feedback", "doctor"]) == 0
    doctor = capsys.readouterr().out
    assert "Auto-upload: no" in doctor
    assert "Do not paste prompts" in doctor

    assert main(["--root", str(root), "feedback", "record", "github-ops", "--verdict", "accepted"]) == 0
    recorded = json.loads(capsys.readouterr().out)
    assert recorded["name"] == "github-ops"

    assert main(["--root", str(root), "feedback", "github-ops", "--verdict", "neutral"]) == 0
    legacy = json.loads(capsys.readouterr().out)
    assert legacy["verdict"] == "neutral"


def test_feedback_markdown_stays_safe(tmp_path: Path) -> None:
    root = tmp_path / "library"
    write_skill(root)
    write_events(root)
    markdown = format_feedback_markdown(build_feedback_report(root))
    assert "Unlimited Skills feedback report" in markdown
    for item in FORBIDDEN_VALUES:
        assert item not in markdown


def test_feedback_report_include_usage_snapshot_uses_redacted_mcp_counts(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    write_skill(root)
    write_events(root)

    monkeypatch.setattr("unlimited_skills.feedback.discover_mcp_servers", lambda: ["fake-server"])
    monkeypatch.setattr(
        "unlimited_skills.feedback.build_savings_report",
        lambda _servers: {
            "servers": [
                {
                    "name": "github",
                    "status": "ok",
                    "tools_count": 3,
                    "schema_bytes": 1200,
                    "est_tokens": 300,
                }
            ],
            "measured_servers": 1,
            "skipped_servers": 0,
            "total_bytes": 1200,
            "total_est_tokens": 300,
            "gateway_bytes": 100,
            "gateway_est_tokens": 25,
            "savings_bytes": 1100,
            "savings_pct": 91.7,
        },
    )

    report = build_feedback_report(root, include_usage_snapshot=True)

    assert report["mcp_savings"]["included"] is True
    assert report["mcp_savings"]["servers"] == [
        {
            "name": "github",
            "status": "ok",
            "tools_count": 3,
            "schema_bytes": 1200,
            "est_tokens": 300,
        }
    ]
    assert report["mcp_savings"]["schema_contents_included"] is False
    assert report["mcp_savings"]["commands_included"] is False
    assert report["mcp_savings"]["env_included"] is False
    assert report["usage_snapshot"]["included"] is True
    assert_forbidden_absent(report, root)
