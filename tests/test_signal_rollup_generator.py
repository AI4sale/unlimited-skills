from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate-public-alpha-signal-rollup.py"


def run_generator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def test_fixture_mode_generates_reproducible_rollup_without_tracking(tmp_path: Path) -> None:
    output = tmp_path / "public-alpha-signal-rollup-002.md"

    result = run_generator("--fixture-mode", "--out", str(output))

    assert result.returncode == 0
    assert output.exists()
    text = output.read_text(encoding="utf-8").lower()

    for required in [
        "# public-alpha signal rollup 002",
        "unlimited-skills==0.5.3",
        "v0.5.3-alpha",
        "5 stars",
        "0 forks",
        "not_submitted",
        "marketplace state: not_submitted=3",
        "blocked_pending_owner_approval",
        "low_signal",
        "no_feedback_yet",
        "owner-provided manual social input: not provided",
        "parked pr #119",
        "permission_to_submit: yes",
    ]:
        assert required in text
    assert "unknown=19" not in text

    for privacy_boundary in [
        "no telemetry",
        "tracking pixels",
        "analytics sdk",
        "private user data",
        "prompt collection",
        "tool input collection",
        "tool output collection",
        "hosted query forwarding",
        "private social scraping",
    ]:
        assert privacy_boundary in text

    for forbidden_claim in [
        "paid cta",
        "payment links",
        "hosted/team/enterprise readiness claims",
        "external acceptance claims",
        "delivery promises",
    ]:
        assert forbidden_claim in text


def test_owner_social_json_is_optional_and_marked_as_manual_input(tmp_path: Path) -> None:
    output = tmp_path / "public-alpha-signal-rollup-003.md"
    social = tmp_path / "owner-social.json"
    social.write_text(
        json.dumps(
            {
                "source": "LinkedIn launch post",
                "date_checked": "2026-06-13",
                "public_url": "https://example.com/public-post",
                "summary": "Two public replies asked for install screenshots.",
                "metrics": {"public_replies": 2, "reported_installs": 0},
                "ignored_private_field": "must not be rendered",
            }
        ),
        encoding="utf-8",
    )

    run_generator("--fixture-mode", "--out", str(output), "--social-json", str(social))

    text = output.read_text(encoding="utf-8")
    lower = text.lower()
    assert "owner-provided manual social input: provided" in lower
    assert "source: LinkedIn launch post" in text
    assert "public_replies=2" in text
    assert "reported_installs=0" in text
    assert "ignored_private_field" not in text


def test_template_and_generator_document_public_manual_boundary() -> None:
    template = (ROOT / "docs" / "adoption" / "public-alpha-signal-rollup-template.md").read_text(encoding="utf-8").lower()
    script = SCRIPT.read_text(encoding="utf-8").lower()

    for required in [
        "--fixture-mode",
        "--social-json",
        "owner-provided",
        "public aggregate",
        "no telemetry",
        "no tracking pixels",
        "no analytics sdks",
        "private social scraping",
    ]:
        assert required in template

    for blocked in ["tracking pixel", "analytics sdk", "hosted query forwarding", "private social scraping"]:
        assert blocked in script
