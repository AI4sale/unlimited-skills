#!/usr/bin/env python
"""Verify feedback report examples and command output stay paste-safe."""

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
]


def assert_safe(text: str, label: str) -> None:
    for pattern in FORBIDDEN:
        if pattern.search(text):
            raise SystemExit(f"{label} contains forbidden marker: {pattern.pattern}")


def main() -> int:
    example = (ROOT / "examples" / "feedback-report.example.json").read_text(encoding="utf-8")
    json.loads(example)
    assert_safe(example, "feedback example")
    with tempfile.TemporaryDirectory(prefix="uls-feedback-") as temp:
        root = Path(temp) / "library"
        root.mkdir()
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "unlimited_skills",
                "--root",
                str(root),
                "feedback",
                "prepare",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        if payload.get("network_calls") is not False or payload.get("upload_available") is not False:
            raise SystemExit("feedback prepare must not enable network or upload")
        assert_safe(proc.stdout, "feedback prepare output")
    print("feedback report boundary verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
