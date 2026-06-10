from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from unlimited_skills import __version__


ROOT = Path(__file__).resolve().parents[1]
OVERRIDE_REASON = "Release owner explicitly accepts blocked production registry signing as a v0.3.1-alpha known issue."
pytestmark = pytest.mark.skipif(__version__ != "0.3.1", reason="v0.3.1 publication gate is only active on the v0.3.1 release train")


def run_verifier(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/verify-v0.3.1-alpha-publication.py", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )


def test_v031_publication_blocks_without_production_registry_signing_or_override() -> None:
    completed = run_verifier()

    assert completed.returncode != 0
    assert "production-signed registry artifacts are not verified" in completed.stdout
    assert "PRIVATE KEY" not in completed.stdout


def test_v031_publication_allows_explicit_release_owner_blocked_signing_override() -> None:
    completed = run_verifier(
        "--allow-registry-signing-blocked",
        "--release-owner-override-reason",
        OVERRIDE_REASON,
    )

    assert completed.returncode == 0, completed.stdout
    assert "production registry signing: blocked override accepted" in completed.stdout
    assert "PRIVATE KEY" not in completed.stdout
