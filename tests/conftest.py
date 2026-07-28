from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_local_business_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a developer-machine provider alter repository test contracts."""

    monkeypatch.setenv("UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT", "1")


@pytest.fixture(autouse=True)
def isolate_unlimited_skills_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Never let developer trust or registration state affect a test."""

    monkeypatch.setenv(
        "UNLIMITED_SKILLS_HOME",
        str(tmp_path / ".unlimited-skills"),
    )
