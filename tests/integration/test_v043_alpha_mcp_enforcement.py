from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_smoke():
    path = ROOT / "scripts" / "run-v043-alpha-mcp-enforcement-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v043_alpha_mcp_enforcement_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v043_alpha_mcp_enforcement_evidence() -> None:
    report = _load_smoke().collect_evidence(run_pytest=False)

    assert report["status"] == "passed"
    assert report["release"] == "v0.4.3-alpha"
    assert report["mode"] == "fixture"
    assert report["production_hosted_calls"] is False
    assert report["hosted_gateway"] is False
    assert report["oauth"] is False
    assert report["remote_upstreams"] is False
    assert report["mcp_resources"] is False
    assert report["mcp_prompts"] is False
    assert report["arbitrary_shell_execution"] is False
    assert report["automatic_telemetry"] is False

    proofs = report["proofs"]
    assert proofs["disabled_refusal"]["code"] == -32005
    assert proofs["disabled_refusal"]["not_indexed"] is True
    assert proofs["disabled_refusal"]["not_spawned"] is True
    assert proofs["future_remote_refusal"]["code"] == -32010
    assert proofs["future_remote_refusal"]["not_indexed"] is True
    assert proofs["future_remote_refusal"]["not_spawned"] is True
    assert proofs["command_not_allowed"]["code"] == -32006
    assert proofs["env_forwarding_denied"]["code"] == -32007
    assert proofs["schema_too_large"]["code"] == -32008
    assert proofs["schema_too_large"]["no_schema_content"] is True
    assert proofs["response_too_large"]["code"] == -32009
    assert proofs["response_too_large"]["no_response_content"] is True
    assert proofs["timeout_hard_bound"]["request_timeout_seconds_max"] == 300
    assert proofs["audit_rotation"] is True
    assert proofs["audit_redaction"] is True
    assert proofs["no_resources_or_prompts"] is True
    assert proofs["no_shell_execution"] is True
