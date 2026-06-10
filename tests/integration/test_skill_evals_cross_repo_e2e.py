from __future__ import annotations

import importlib.util
from pathlib import Path


def load_runner():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run-skill-evals-cross-repo-e2e.py"
    spec = importlib.util.spec_from_file_location("skill_evals_cross_repo_e2e", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_evals_cross_repo_fixture_e2e() -> None:
    runner = load_runner()
    payload = runner.run_client_e2e(runner.fixture_eval_report(), temp_home=True)
    assert payload["status"] == "passed"
    assert payload["production_hosted_calls"] is False
    assert payload["quality_grade"] == "a"
    assert payload["low_score_warning"]
    assert payload["blocked_item_refused"] is True
    assert payload["high_quality_install_verified"] is True
    assert payload["privacy"]["automatic_telemetry"] is False
    assert payload["privacy"]["prompts_included"] is False
    assert payload["privacy"]["skill_bodies_included"] is False
