from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_smoke():
    path = ROOT / "scripts" / "run-v045-alpha-mcp-audit-inspector-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v045_alpha_mcp_audit_inspector_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v045_alpha_audit_inspector_smoke_evidence() -> None:
    report = load_smoke().collect_evidence(run_pytest=False)
    assert report["status"] == "passed"
    assert report["release"] == "v0.4.5-alpha"
    assert report["proofs"]["json_schema_valid"] is True
    assert report["proofs"]["recent_refusals_safe"]["payload_absent"] is True
    assert report["proofs"]["recent_refusals_safe"]["error_text_absent"] is True
    assert report["proofs"]["redaction_clean_pass"]["status"] == "PASS"
    assert report["proofs"]["redaction_injected_fail_safe"]["status"] == "FAIL"
    assert report["proofs"]["redaction_injected_fail_safe"]["secret_values_absent"] is True
    assert report["proofs"]["rotated_logs"]["oldest_first"] is True
    assert report["proofs"]["read_only"]["digest_unchanged"] is True
    assert report["proofs"]["read_only"]["mtime_unchanged"] is True
    assert report["production_hosted_calls"] is False
    assert report["hosted_gateway"] is False
