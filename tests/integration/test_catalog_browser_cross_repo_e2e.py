from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


def load_runner():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run-catalog-browser-cross-repo-e2e.py"
    spec = importlib.util.spec_from_file_location("catalog_browser_cross_repo_e2e", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_browser_public_fixture_e2e_without_private_checkout() -> None:
    runner = load_runner()
    payload = runner.run_public_fixture_e2e(temp_home=True)
    assert payload["status"] == "passed"
    assert payload["private_registry_checkout_required"] is False
    assert payload["approved_only_visibility"] is True
    assert payload["signed_metadata_verified"] is True
    assert payload["metadata_only_preview"] is True
    assert payload["dry_run_install_verified"] is True
    assert payload["quality_status_verified"] is True
    assert payload["production_hosted_calls"] is False


def test_catalog_browser_local_registry_e2e_when_available() -> None:
    registry_repo = Path(os.environ.get("UNLIMITED_SKILLS_REGISTRY_REPO", r"D:\git\unlimited-skills-registry"))
    if not (registry_repo / "unlimited_registry" / "production_api.py").is_file():
        pytest.skip("private registry checkout is not available")
    runner = load_runner()
    payload = runner.run_local_registry_e2e(registry_repo, temp_home=True)
    assert payload["status"] == "passed"
    assert payload["mode"] == "local-registry"
    assert payload["approved_only_visibility"] is True
    assert payload["signed_metadata_verified"] is True
    assert payload["metadata_only_preview"] is True
    assert payload["dry_run_install_verified"] is payload["quality_status_api_available"]
    assert payload["production_hosted_calls"] is False
