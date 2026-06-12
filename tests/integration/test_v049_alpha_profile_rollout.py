from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_smoke():
    path = ROOT / "scripts" / "run-v049-alpha-profile-rollout-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v049_alpha_profile_rollout_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v049_alpha_profile_rollout_smoke_contract() -> None:
    report = _load_smoke().collect_evidence()
    assert report["status"] == "passed"
    assert report["release"] == "v0.4.9-alpha"
    assert report["profile_activation"] is False
    assert report["trust_store_mutation"] is False
    assert report["hosted_trust_fetch"] is False
    assert report["registry_sync"] is False
    assert report["production_signing_keys"] is False
    proofs = report["proofs"]
    for key in (
        "raw_profile_rollout_plan",
        "signed_bundle_rollout_plan",
        "trust_store_backed_rollout_plan",
        "missing_trust_store",
        "corrupt_trust_store",
        "expired_key",
        "revoked_key",
        "wrong_audience",
        "namespace_violation",
        "hide_all_tools",
        "shadowed_tool",
        "signed_required_unsigned_source",
    ):
        assert proofs[key]["status"] == "passed"
    assert proofs["no_upstream_spawn"] is True
    assert proofs["no_network"] is True
    assert proofs["no_mutation"] is True
