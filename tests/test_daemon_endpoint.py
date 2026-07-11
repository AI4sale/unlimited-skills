from __future__ import annotations

from pathlib import Path

from unlimited_skills.daemon_endpoint import warm_daemon_url


def test_distinct_library_roots_get_distinct_loopback_ports(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_WARM_DAEMON_URL", raising=False)
    first = warm_daemon_url(tmp_path / "first" / "library")
    second = warm_daemon_url(tmp_path / "second" / "library")
    assert first.startswith("http://127.0.0.1:")
    assert second.startswith("http://127.0.0.1:")
    assert first != second


def test_explicit_endpoint_accepts_loopback_and_refuses_remote(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_WARM_DAEMON_URL", "http://localhost:19999")
    assert warm_daemon_url(tmp_path) == "http://localhost:19999"
    monkeypatch.setenv("UNLIMITED_SKILLS_WARM_DAEMON_URL", "https://remote.example:8765")
    assert warm_daemon_url(tmp_path) == ""
