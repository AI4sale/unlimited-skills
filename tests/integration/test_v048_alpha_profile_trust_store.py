from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_smoke():
    path = ROOT / "scripts" / "run-v048-alpha-profile-trust-store-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v048_alpha_profile_trust_store_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v048_alpha_profile_trust_store_smoke_evidence() -> None:
    report = load_smoke().collect_evidence()
    assert report["status"] == "passed"
    assert report["release"] == "v0.4.8-alpha"
    assert report["production_hosted_calls"] is False
    assert report["hosted_trust_fetch"] is False
    assert report["registry_sync"] is False
    assert report["production_signing_keys"] is False
    assert report["private_key_storage"] is False
    proofs = report["proofs"]
    assert proofs["trust_status"]["status"] == "passed"
    assert proofs["trust_list"]["no_full_key_bytes"] is True
    assert proofs["trust_import"]["managed_trusted_keys_path"] == ".unlimited-skills-trust\\trusted-keys.json" or proofs["trust_import"]["managed_trusted_keys_path"] == ".unlimited-skills-trust/trusted-keys.json"
    assert proofs["trust_revoke"]["append_only_history"] is True
    assert proofs["trust_doctor"]["healthy_exit_code"] == 0
    assert proofs["trust_doctor"]["corrupt_exit_code"] == 1
    assert proofs["valid_trusted_key"]["profile"] == "dev"
    assert proofs["revoked_key_refusal"]["code"] == -32017
    assert proofs["missing_trust_store_refusal"]["code"] == -32019
    assert proofs["explicit_trusted_keys_override_refusal"]["code"] == -32019
    assert proofs["unreadable_crl_refusal"]["code"] == -32017
    assert proofs["private_key_import_refusal"]["wrote_nothing"] is True
    assert proofs["audit_provenance"]["no_key_material_or_signature"] is True
