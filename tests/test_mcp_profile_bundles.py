from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_smoke():
    path = ROOT / "scripts" / "run-v047-alpha-signed-profile-bundles-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v047_alpha_signed_profile_bundles_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_signed_profile_bundle_gate_smoke() -> None:
    report = load_smoke().collect_evidence()
    assert report["status"] == "passed"
    assert report["proofs"]["valid_signed_bundle"]["status"] == "passed"
    assert report["proofs"]["audit_provenance"]["status"] == "passed"
    assert report["proofs"]["no_hosted_trust_fetch"] is True
    assert report["proofs"]["no_registry_sync"] is True
