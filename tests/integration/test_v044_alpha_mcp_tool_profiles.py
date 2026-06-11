from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_smoke():
    path = ROOT / "scripts" / "run-v044-alpha-mcp-tool-profiles-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v044_alpha_mcp_tool_profiles_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v044_alpha_profile_enforcement_smoke_evidence() -> None:
    report = load_smoke().collect_evidence(run_pytest=False)
    assert report["status"] == "passed"
    assert report["release"] == "v0.4.4-alpha"
    assert report["proofs"]["default_deny"]["code"] == -32011
    assert report["proofs"]["visible_only_search"]["hidden_hits"] == []
    assert report["proofs"]["non_callable_call_refusal"]["code"] == -32012
    assert report["proofs"]["fail_closed"]["missing_code"] == -32013
    assert report["proofs"]["fail_closed"]["invalid_code"] == -32014
    assert report["proofs"]["profile_audit"]["profile_loaded_row"] is True
    assert report["proofs"]["profile_audit"]["profile_sha256"] == report["proofs"]["profile_audit"]["profile_sha256_expected"]
    assert report["proofs"]["no_resources_or_prompts"] is True
    assert report["oauth"] is False
    assert report["hosted_gateway"] is False
    assert report["production_hosted_calls"] is False
