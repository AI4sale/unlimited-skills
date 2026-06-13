#!/usr/bin/env python
"""Verify local ROI receipt examples and command output stay paste-safe."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = [
    re.compile(r"[A-Za-z]:\\[^\s\"']+", re.IGNORECASE),
    re.compile(r"/(?:Users|home|private|tmp|var|etc)/[^\s\"']+", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|glpat|xoxb|uls)_[A-Za-z0-9_\-]{8,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(inputSchema|tool_input|tool_output|license_token|private_key)\b", re.IGNORECASE),
    re.compile(r"\b(customer secret query|private customer task|Prompt:)\b", re.IGNORECASE),
]


def assert_safe(text: str, label: str) -> None:
    for pattern in FORBIDDEN:
        if pattern.search(text):
            raise SystemExit(f"{label} contains forbidden marker: {pattern.pattern}")


def assert_schema_contract(payload: dict, schema: dict, label: str) -> None:
    missing = [key for key in schema.get("required", []) if key not in payload]
    if missing:
        raise SystemExit(f"{label} missing schema keys: {missing}")
    if payload.get("schema_version") != 1:
        raise SystemExit(f"{label} has wrong schema_version")
    if payload.get("report_type") != "local_roi_receipt":
        raise SystemExit(f"{label} has wrong report_type")
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    for key in ("local_only", "telemetry", "upload", "analytics", "tracking_pixel"):
        if key not in privacy:
            raise SystemExit(f"{label} missing privacy.{key}")
    if privacy.get("local_only") is not True:
        raise SystemExit(f"{label} must be local_only")
    for key in ("telemetry", "upload", "analytics", "tracking_pixel"):
        if privacy.get(key) is not False:
            raise SystemExit(f"{label} must keep privacy.{key}=false")


def _write_fixture(root: Path) -> None:
    skill = root / "local" / "skills" / "fixture" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "---\nname: fixture\ndescription: safe fixture\n---\n\nPrompt: customer secret query\n",
        encoding="utf-8",
    )
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    (learning / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"ts": 1, "type": "suggest", "payload": {"delivery_tier": 3, "session_correlation_id": "abc"}}),
                json.dumps({"ts": 2, "type": "skill_used", "payload": {"session_correlation_id": "abc"}}),
                json.dumps({"ts": 3, "type": "suggest", "payload": {"query": "customer secret query", "inputSchema": {"type": "object"}}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "unlimited_skills", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def main() -> int:
    schema = json.loads((ROOT / "schemas" / "roi-receipt.schema.json").read_text(encoding="utf-8"))
    example = (ROOT / "examples" / "roi-receipt.example.json").read_text(encoding="utf-8")
    payload = json.loads(example)
    assert_schema_contract(payload, schema, "ROI receipt example")
    assert_safe(example, "ROI receipt example")
    with tempfile.TemporaryDirectory(prefix="uls-roi-") as temp:
        root = Path(temp) / "library"
        _write_fixture(root)
        json_proc = _run(["--root", str(root), "roi", "receipt", "--format", "json"], ROOT)
        if json_proc.returncode != 0:
            raise SystemExit(json_proc.stderr or json_proc.stdout)
        receipt = json.loads(json_proc.stdout)
        assert_schema_contract(receipt, schema, "ROI receipt JSON")
        if receipt.get("privacy", {}).get("telemetry") is not False or receipt.get("privacy", {}).get("upload") is not False:
            raise SystemExit("roi receipt must not enable telemetry or upload")
        if receipt.get("window", {}).get("legacy_status") != "unavailable_legacy_logs":
            raise SystemExit("roi receipt must mark unsafe legacy rows unavailable")
        assert_safe(json_proc.stdout, "ROI receipt JSON")
        md_proc = _run(["--root", str(root), "roi", "receipt", "--format", "markdown"], ROOT)
        if md_proc.returncode != 0:
            raise SystemExit(md_proc.stderr or md_proc.stdout)
        assert_safe(md_proc.stdout, "ROI receipt Markdown")
    print("ROI receipt boundary verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
