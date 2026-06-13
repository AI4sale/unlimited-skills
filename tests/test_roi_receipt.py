from __future__ import annotations

import json
import time
from pathlib import Path

from unlimited_skills import cli
from unlimited_skills.roi_receipt import REQUIRED_NOTICE, assert_roi_receipt_safe, build_roi_receipt, format_roi_receipt_markdown
from unlimited_skills.search_core import EVENT_LOG, save_index


FORBIDDEN_NEEDLES = (
    "customer secret query zz-needle",
    "private customer task yy-needle",
    "Prompt:",
    "SECRET_TOKEN_XYZ123",
    "C:\\Users\\tedja\\customer",
    "/home/customer/private",
    "inputSchema",
    "SKILL.md",
)


def write_skill(root: Path) -> None:
    skill = root / "local" / "skills" / "privacy-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: privacy-skill\ndescription: Privacy-safe workflow.\n---\n\n"
        "Prompt: SECRET_TOKEN_XYZ123 C:\\Users\\tedja\\customer\n",
        encoding="utf-8",
    )
    save_index(root)


def write_events(root: Path, *, now: float) -> None:
    events = root / ".learning" / EVENT_LOG
    events.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "ts": now - 60,
            "type": "suggest",
            "payload": {
                "delivery_tier": 3,
                "injected": True,
                "score_bucket": "high",
                "margin_bucket": "clear",
                "session_correlation_id": "safe-session-a",
            },
        },
        {"ts": now - 50, "type": "view", "payload": {"session_correlation_id": "safe-session-a"}},
        {"ts": now - 40, "type": "skill_used", "payload": {"session_correlation_id": "safe-session-a"}},
        {
            "ts": now - 30,
            "type": "quickstart",
            "payload": {
                "steps": {"import": "ok", "first_search": "ok"},
                "first_search_hit_count": 1,
                "mcp_savings_present": True,
            },
        },
        {
            "ts": now - 20,
            "type": "mcp_savings",
            "payload": {
                "servers": [{"name": "private-server-name", "status": "ok", "tools_count": 2, "schema_bytes": 4000}],
                "total_bytes": 4000,
                "total_est_tokens": 1000,
                "gateway_bytes": 100,
                "savings_bytes": 3900,
                "savings_pct": 97.5,
            },
        },
        {
            "ts": now - 10,
            "type": "suggest",
            "payload": {
                "query": "customer secret query zz-needle",
                "task": "private customer task yy-needle",
                "path": "C:\\Users\\tedja\\customer\\SKILL.md",
                "inputSchema": {"type": "object"},
            },
        },
        {"ts": now - 86400 * 9, "type": "suggest", "payload": {"delivery_tier": 1}},
    ]
    events.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    (root / ".learning" / "feedback.jsonl").write_text(
        json.dumps({"query": "customer secret query zz-needle", "notes": "Prompt:"}) + "\n",
        encoding="utf-8",
    )


def assert_forbidden_absent(text: str, root: Path) -> None:
    for needle in FORBIDDEN_NEEDLES:
        assert needle not in text
    assert str(root) not in text


def test_build_roi_receipt_is_aggregate_only_and_legacy_safe(tmp_path: Path) -> None:
    root = tmp_path / "library"
    now = time.time()
    write_skill(root)
    write_events(root, now=now)

    receipt = build_roi_receipt(root, since="7d", generated_at="2026-06-14T00:00:00Z", now=now)

    assert receipt["report_type"] == "local_roi_receipt"
    assert receipt["privacy_notice"] == REQUIRED_NOTICE
    assert receipt["window"]["requested"] == "7d"
    assert receipt["window"]["legacy_status"] == "unavailable_legacy_logs"
    assert receipt["window"]["unsafe_legacy_rows_skipped"] == 1
    assert receipt["library"]["skill_count"] == 1
    assert receipt["quickstart_status"]["status"] == "completed"
    assert receipt["mcp_savings_summary"]["source"] == "local_mcp_savings"
    assert receipt["mcp_savings_summary"]["server_names_included"] is False
    assert receipt["skill_routing"]["suggest_count"] == 1
    assert receipt["skill_routing"]["view_count"] == 1
    assert receipt["skill_routing"]["use_count"] == 1
    assert receipt["learning_summary_events"]["post_suggest_use_rate"] == 1.0
    assert receipt["feedback_prepare_status"]["available"] is True
    assert receipt["privacy"]["telemetry"] is False
    assert receipt["privacy"]["upload"] is False

    serialized = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    assert_forbidden_absent(serialized, root)
    assert_roi_receipt_safe(receipt)


def test_roi_receipt_cli_json_markdown_and_out_are_safe(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "library"
    now = time.time()
    monkeypatch.setenv("UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC", "1")
    write_skill(root)
    write_events(root, now=now)

    assert cli.main(["--root", str(root), "roi", "receipt", "--format", "json", "--since", "7d"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report_type"] == "local_roi_receipt"
    assert payload["privacy_notice"] == REQUIRED_NOTICE
    assert_forbidden_absent(json.dumps(payload, ensure_ascii=False), root)

    assert cli.main(["--root", str(root), "roi", "receipt", "--format", "markdown", "--since", "7d"]) == 0
    markdown = capsys.readouterr().out
    assert "# Unlimited Skills local ROI receipt" in markdown
    assert REQUIRED_NOTICE in markdown
    assert "Local-only: yes. Upload: no. Telemetry: no." in markdown
    assert_forbidden_absent(markdown, root)

    out = tmp_path / "roi-receipt.md"
    assert cli.main(["--root", str(root), "roi", "receipt", "--format", "markdown", "--out", str(out)]) == 0
    status = capsys.readouterr().out
    assert "ROI receipt written (markdown)." in status
    assert str(out) not in status
    assert REQUIRED_NOTICE in out.read_text(encoding="utf-8")


def test_roi_receipt_since_window_filters_old_safe_events(tmp_path: Path) -> None:
    root = tmp_path / "library"
    now = time.time()
    write_skill(root)
    write_events(root, now=now)

    receipt = build_roi_receipt(root, since="1h", now=now)

    assert receipt["skill_routing"]["suggest_count"] == 1
    assert receipt["window"]["legacy_status"] == "unavailable_legacy_logs"


def test_roi_receipt_invalid_since_refuses(tmp_path: Path, capsys) -> None:
    assert cli.main(["--root", str(tmp_path / "library"), "roi", "receipt", "--since", "yesterday"]) == 2
    assert "--since must be" in capsys.readouterr().err


def test_roi_markdown_formatter_stays_screenshot_friendly(tmp_path: Path) -> None:
    root = tmp_path / "library"
    write_skill(root)
    receipt = build_roi_receipt(root, generated_at="2026-06-14T00:00:00Z")
    markdown = format_roi_receipt_markdown(receipt)
    assert markdown.count("\n") < 30
    assert REQUIRED_NOTICE in markdown
    assert_forbidden_absent(markdown, root)
