from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills.daemon_endpoint import RUNTIME_CONTRACT_VERSION, warm_daemon_url, warm_daemon_urls


def test_distinct_library_roots_get_distinct_loopback_ports(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_WARM_DAEMON_URL", raising=False)
    first = warm_daemon_url(tmp_path / "first" / "library")
    second = warm_daemon_url(tmp_path / "second" / "library")
    assert first.startswith("http://127.0.0.1:")
    assert second.startswith("http://127.0.0.1:")
    assert first != second
    assert len(warm_daemon_urls(tmp_path / "first" / "library")) == 2
    assert RUNTIME_CONTRACT_VERSION == 2


def test_explicit_endpoint_accepts_loopback_and_refuses_remote(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNLIMITED_SKILLS_WARM_DAEMON_URL", "http://localhost:19999")
    assert warm_daemon_url(tmp_path) == "http://localhost:19999"
    monkeypatch.setenv("UNLIMITED_SKILLS_WARM_DAEMON_URL", "https://remote.example:8765")
    assert warm_daemon_url(tmp_path) == ""
    assert warm_daemon_urls(tmp_path) == []


def test_health_exposes_versioned_runtime_identity() -> None:
    from unlimited_skills import __version__
    from unlimited_skills.server import health

    payload = health()
    assert payload["runtime_contract_version"] == RUNTIME_CONTRACT_VERSION
    assert payload["package_version"] == __version__


def test_warm_start_repairs_stale_sidecar_without_touching_legacy_chroma(
    tmp_path: Path, monkeypatch
) -> None:
    from unlimited_skills import server
    from unlimited_skills.search_core import SkillHit

    writes: dict[str, dict] = {}
    vector_calls: list[str] = []
    hit = SkillHit("security-review", "Security review", "local", "local/security-review/SKILL.md", 0.0)
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "vector_sidecar_status", lambda *args: {"ready": False})
    monkeypatch.setattr(server, "load_records", lambda root: [(hit, "body")])
    monkeypatch.setattr(server, "embed_texts", lambda texts, model: [[0.1, 0.2]])
    monkeypatch.setattr(server, "library_generation_hash", lambda root: "generation")
    monkeypatch.setattr(
        server,
        "atomic_write_text",
        lambda path, text: writes.__setitem__(Path(path).name, json.loads(text)),
    )
    monkeypatch.setattr(server, "vector_search", lambda root, query, limit, model: vector_calls.append(query))

    server.warm_start()

    assert writes[".unlimited-skills-vectors.json"]["schema_version"] == 2
    assert writes[".unlimited-skills-vectors.json"]["complete"] is True
    assert vector_calls == ["__warm_start__"]
