from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


def load_runner():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run-catalog-feedback-cross-repo-e2e.py"
    spec = importlib.util.spec_from_file_location("catalog_feedback_cross_repo_e2e", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_feedback_cross_repo_e2e() -> None:
    registry_repo = Path(os.environ.get("UNLIMITED_SKILLS_REGISTRY_REPO", r"D:\git\unlimited-skills-registry"))
    if not (registry_repo / "unlimited_registry" / "production_api.py").is_file():
        pytest.skip("private registry checkout is not available")
    runner = load_runner()
    payload = runner.run_fixture_e2e(registry_repo, temp_home=True)
    assert payload["status"] == "passed"
    assert payload["dry_run_sent"] is False
    assert payload["submitted_feedback_id_present"] is True
    assert payload["status_feedback_count"] == 1
    assert payload["server_feedback_count"] == 1
    assert payload["production_hosted_calls"] is False
