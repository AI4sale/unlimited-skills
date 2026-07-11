from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_publication_verifier():
    path = ROOT / "scripts" / "verify-pypi-publication.py"
    spec = importlib.util.spec_from_file_location("verify_pypi_publication", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v067_versions_and_release_plan_are_aligned() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    runtime = (ROOT / "unlimited_skills" / "__init__.py").read_text(encoding="utf-8")
    plugin = json.loads((ROOT / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    plan = (ROOT / "docs" / "releases" / "v0.6.7-plan.md").read_text(encoding="utf-8")
    assert 'version = "0.6.7"' in pyproject
    assert '__version__ = "0.6.7"' in runtime
    assert plugin["version"] == "0.6.7"
    assert "public core never names or depends on a private knowledge system" in plan
    assert "reference data, not instructions" in plan
    assert "the Stop hook never submits prose" in plan
    assert "No deletion, replacement, or migration of `library/local`" in plan


def test_publication_verifier_requires_wheel_and_sdist(tmp_path: Path) -> None:
    verifier = load_publication_verifier()
    wheel = tmp_path / "unlimited_skills-0.6.6-py3-none-any.whl"
    sdist = tmp_path / "unlimited_skills-0.6.6.tar.gz"
    wheel.write_bytes(b"wheel-fixture")
    sdist.write_bytes(b"sdist-fixture")
    payload = {
        "info": {"name": "unlimited-skills", "version": "0.6.6"},
        "urls": [
            {
                "filename": wheel.name,
                "digests": {"sha256": verifier.sha256_file(wheel)},
            },
            {
                "filename": sdist.name,
                "digests": {"sha256": verifier.sha256_file(sdist)},
            },
        ],
    }
    result = verifier.validate_pypi_payload(payload, "0.6.6", dist_dir=tmp_path)
    assert result["version"] == "0.6.6"
    assert len(result["filenames"]) == 2
    assert result["local_artifact_digests_verified"] is True


def test_publication_verifier_retries_only_simple_index_propagation(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = load_publication_verifier()
    calls = []

    def fake_smoke(version: str):
        calls.append(version)
        if len(calls) == 1:
            raise verifier.PublicIndexPropagationPending("not visible yet")
        return {"version_output": f"unlimited-skills {version}"}

    monkeypatch.setattr(verifier, "clean_install_smoke", fake_smoke)
    monkeypatch.setattr(verifier.time, "sleep", lambda _seconds: None)
    result = verifier.wait_for_clean_install("0.6.7", wait_seconds=5, poll_seconds=0.1)
    assert result["version_output"] == "unlimited-skills 0.6.7"
    assert calls == ["0.6.7", "0.6.7"]


def test_publication_verifier_does_not_retry_real_smoke_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = load_publication_verifier()
    monkeypatch.setattr(verifier, "clean_install_smoke", lambda _version: (_ for _ in ()).throw(RuntimeError("broken wheel")))
    with pytest.raises(RuntimeError, match="broken wheel"):
        verifier.wait_for_clean_install("0.6.7", wait_seconds=5, poll_seconds=0.1)


def test_package_smoke_keeps_child_commands_on_the_invoking_python() -> None:
    source = (ROOT / "scripts" / "run-v065-alpha-package-smoke.py").read_text(encoding="utf-8")
    assert "sys.executable" in source
    assert 'run(["python"' not in source
    assert "baseline_quickstart_skill_count" in source
    assert "local_sentinel_preserved" in source
    assert "quickstart_index_refreshed" in source


def test_v066_package_smoke_accepts_explicit_rescue_but_not_silence() -> None:
    from scripts.run_v065_alpha_package_smoke import verify_report

    report = {
        "version": "0.6.6",
        "dist": {"wheel": "unlimited_skills-0.6.6-py3-none-any.whl"},
        "clean_install_retrieval_learning": {
            "version_output": "unlimited-skills 0.6.6",
            "suggest_reason_code": "match_found",
            "suggest_delivery_tier": 1,
            "suggest_candidate_names": [],
            "suggest_needs_english_query": True,
            "suggest_delivery_mode": "rescue",
            "search_candidate_names": ["social-publisher"],
            "search_candidate_sources_present": True,
            "learning_summary_has_effectiveness": True,
        },
        "source_release_gates": {
            "release_smoke_ok": True,
            "learning_loop_ok": True,
            "learning_loop_manual_no_query": True,
        },
        "upgrade_from_public_pypi": {
            "baseline_version_output": "unlimited-skills 0.6.4.post1",
            "upgraded_version_output": "unlimited-skills 0.6.6",
            "baseline_quickstart_skill_count": 267,
            "quickstart_skill_count": 268,
            "quickstart_index_refreshed": True,
            "local_sentinel_preserved": True,
            "doctor_index_current": True,
            "suggest_candidates": 1,
            "search_candidates": 1,
            "learning_effectiveness_present": True,
        },
    }

    assert verify_report(report, "0.6.6") == []
    report["clean_install_retrieval_learning"]["suggest_delivery_mode"] = "silence"
    assert any("explicit English-query rescue" in error for error in verify_report(report, "0.6.6"))
