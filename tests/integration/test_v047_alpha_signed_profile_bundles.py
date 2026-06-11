from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_smoke():
    path = ROOT / "scripts" / "run-v047-alpha-signed-profile-bundles-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v047_alpha_signed_profile_bundles_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v047_alpha_signed_profile_bundles_smoke_evidence() -> None:
    report = load_smoke().collect_evidence()
    assert report["status"] == "passed"
    assert report["release"] == "v0.4.7-alpha"
    assert report["production_hosted_calls"] is False
    assert report["hosted_trust_fetch"] is False
    assert report["registry_sync"] is False
    assert report["production_signing_keys"] is False
    assert report["raw_local_profiles_still_allowed_by_default"] is True
    assert report["registered_business_signed_required_future_gated"] is True
    proofs = report["proofs"]
    assert proofs["raw_local_profile_path"]["status"] == "passed"
    assert proofs["valid_signed_bundle"]["status"] == "passed"
    assert proofs["bad_signature_refusal"]["code"] == -32015
    assert proofs["unknown_key_refusal"]["code"] == -32019
    assert proofs["expired_bundle_refusal"]["code"] == -32016
    assert proofs["revoked_bundle_refusal"]["code"] == -32017
    assert proofs["wrong_audience_refusal"]["code"] == -32018
    assert proofs["namespace_violation_refusal"]["code"] == -32018
    assert proofs["audit_provenance"]["no_key_material_or_signature"] is True
