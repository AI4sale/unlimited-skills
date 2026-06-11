from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_smoke():
    path = ROOT / "scripts" / "run-v046-alpha-mcp-performance-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v046_alpha_mcp_performance_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v046_alpha_mcp_performance_smoke_evidence() -> None:
    report = load_smoke().collect_evidence(run_pytest=False)
    assert report["status"] == "passed"
    assert report["release"] == "v0.4.6-alpha"
    assert report["runtime_default_changes"] is False
    assert report["warm_start_implementation"] is False
    assert report["production_hosted_calls"] is False
    assert report["hosted_gateway"] is False
    proofs = report["benchmark"]["proofs"]
    assert proofs["schema_valid"] is True
    assert proofs["sections_present"] is True
    assert proofs["raw_samples_present"] is True
    assert proofs["spawn_slower_than_reuse"] is True
    assert proofs["context_bytes_consistent"] is True
    assert proofs["no_secret_or_local_path_leaks"] is True
