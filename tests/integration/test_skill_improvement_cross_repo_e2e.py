from __future__ import annotations

import importlib.util
from pathlib import Path


def load_runner():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run-skill-improvement-cross-repo-e2e.py"
    spec = importlib.util.spec_from_file_location("skill_improvement_cross_repo_e2e", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_improvement_cross_repo_fixture_e2e() -> None:
    runner = load_runner()

    payload = runner.run_cross_repo_e2e(runner.fixture_registry_outputs(), temp_home=True, mode="fixture")

    assert payload["status"] == "passed"
    assert payload["production_hosted_calls"] is False
    assert payload["registry"]["evals_ran"] is True
    assert payload["registry"]["feedback_created_issue"] is True
    assert payload["registry"]["backlog_generated"] is True
    assert payload["registry"]["maintainer_accepted_candidate"] is True
    assert payload["registry"]["fixed_pending_eval"] is True
    assert payload["registry"]["catalog_quality_report_has_improvements"] is True
    assert payload["public_client"]["improvement_status"]["fix_status"] == "fixed_pending_eval"
    assert payload["public_client"]["update_recommendations"]["preview_only"] is True
    assert payload["public_client"]["update_preview"]["will_update"] is False
    assert payload["public_client"]["deprecation_status"]["deprecated"] is True
    assert payload["support_bundle"]["summary_counts_only"] is True
    assert payload["privacy"]["skill_bodies_included"] is False
    assert payload["privacy"]["prompts_included"] is False
    assert payload["privacy"]["search_queries_included"] is False
    assert payload["privacy"]["local_paths_included"] is False
