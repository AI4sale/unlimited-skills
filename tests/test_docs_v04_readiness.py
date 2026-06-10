from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def test_v04_readiness_verifier_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/verify-v0.4-readiness-rfc.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "v0.4 readiness RFC verification passed" in completed.stdout
    assert "go/no-go recommendation: NO-GO" in completed.stdout
    assert "runtime implementation authorized: false" in completed.stdout


def test_v04_rfc_preserves_security_privacy_boundaries() -> None:
    combined = "\n".join(
        read(path)
        for path in [
            "docs/releases/v0.4-readiness-audit.md",
            "docs/rfcs/v0.4-skillops-platform-rfc.md",
            "docs/rfcs/v0.4-risk-register.md",
            "docs/rfcs/v0.4-implementation-epics.md",
        ]
    ).lower()

    for phrase in [
        "no prompt upload",
        "no skill body upload",
        "no automatic hosted query forwarding",
        "no automatic skill rewriting",
        "no auto-publish",
        "no live billing",
        "must not gate the mit local core behind registration",
        "must not weaken signed hosted manifest requirements",
    ]:
        assert phrase in combined


def test_v04_docs_are_planning_only_with_blockers() -> None:
    audit = read("docs/releases/v0.4-readiness-audit.md")
    assert "Recommendation: **NO-GO" in audit
    assert "| B-01 |" in audit
    assert "| B-08 |" in audit
    assert "Required action" in audit
    assert "Fallback" in audit

    rfc = read("docs/rfcs/v0.4-skillops-platform-rfc.md")
    assert "## What v0.4 Is Not" in rfc
    assert "```mermaid" in rfc
