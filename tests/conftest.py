from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_local_business_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a developer-machine provider alter repository test contracts."""

    monkeypatch.setenv("UNLIMITED_SKILLS_NO_BUSINESS_CONTEXT", "1")

