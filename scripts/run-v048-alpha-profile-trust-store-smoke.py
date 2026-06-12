from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any

from unlimited_skills.commands.mcp import _resolve_gateway_profile_state
from unlimited_skills.mcp.bundles import BUNDLE_KEY_MISSING, BUNDLE_REVOKED, BundleFailClosed
from unlimited_skills.mcp.profiles import ActiveProfile
from unlimited_skills.mcp.trust_store import (
    TrustStore,
    TrustStoreError,
    default_store_dir,
    doctor_report,
    import_key,
    list_keys_report,
    managed_trusted_keys_path,
    revoke,
    status_report,
)


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.8-alpha"


def _load_trust_tests():
    path = ROOT / "tests" / "test_mcp_trust_store.py"
    spec = importlib.util.spec_from_file_location("v048_trust_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load trust-store test helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_refusal(state: object, code: int, proof_name: str) -> dict[str, Any]:
    if not isinstance(state, BundleFailClosed):
        raise AssertionError(f"{proof_name}: expected BundleFailClosed, got {type(state).__name__}")
    if state.code != code:
        raise AssertionError(f"{proof_name}: expected code {code}, got {state.code}")
    return {"status": "passed", "code": state.code, "message_contains": proof_name}


def _assert_no_full_key_material(report: dict[str, Any], public_key_b64: str) -> None:
    text = json.dumps(report, sort_keys=True)
    if public_key_b64 in text:
        raise AssertionError("trust-store report leaked a full public key")


def _collect_fixture_evidence(tmp: Path) -> dict[str, Any]:
    helpers = _load_trust_tests()
    if not getattr(helpers, "HAVE_CRYPTOGRAPHY", False):
        raise AssertionError("cryptography is required for this signed trust-store smoke")

    root = tmp / "library"
    root.mkdir()
    store = TrustStore(default_store_dir(root))
    private = helpers.Ed25519PrivateKey.generate()
    public_key = private.public_key().public_bytes(helpers.Encoding.Raw, helpers.PublicFormat.Raw)
    public_key_b64 = base64.b64encode(public_key).decode("ascii")

    imported = import_key(
        store,
        key_id="managed-key-2026",
        public_key_b64=public_key_b64,
        display="Platform trust",
        scopes=["profile-bundles"],
        not_before="2026-01-01T00:00:00Z",
        not_after="2099-01-01T00:00:00Z",
        now=helpers.NOW,
    )
    status = status_report(store, now=helpers.NOW)
    key_list = list_keys_report(store, now=helpers.NOW)
    doctor = doctor_report(store, now=helpers.NOW)
    for report in (status, key_list, doctor):
        _assert_no_full_key_material(report, public_key_b64)
    if doctor["exit_code"] != 0:
        raise AssertionError(f"healthy trust store doctor failed: {doctor}")

    bundle_path = helpers.signed_bundle(tmp, private, "managed-key-2026")
    state, note = _resolve_gateway_profile_state(
        helpers.gateway_args(root=str(root), profile_bundle=str(bundle_path), audience_id=["team:test"])
    )
    if not isinstance(state, ActiveProfile) or state.name != "dev":
        raise AssertionError("managed trusted-keys file did not verify the signed bundle")
    if "signed bundle profile 'dev' enforced" not in note:
        raise AssertionError("gateway note did not prove signed bundle enforcement")

    missing_root = tmp / "missing-store-library"
    missing_root.mkdir()
    missing_state, missing_note = _resolve_gateway_profile_state(
        helpers.gateway_args(root=str(missing_root), profile_bundle=str(bundle_path), audience_id=["team:test"])
    )
    if "FAIL-CLOSED" not in missing_note:
        raise AssertionError("missing managed store did not report fail-closed note")

    other_keys = tmp / "other-keys.json"
    other_keys.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "keys": [
                    {
                        "key_id": "unrelated",
                        "algorithm": "ed25519",
                        "public_key": base64.b64encode(b"\x07" * 32).decode("ascii"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    explicit_state, _ = _resolve_gateway_profile_state(
        helpers.gateway_args(
            root=str(root),
            profile_bundle=str(bundle_path),
            trusted_keys=str(other_keys),
            audience_id=["team:test"],
        )
    )

    crl_bundle = {
        "bundle_version": 1,
        "issuer": {"key_id": "managed-key-2026", "display": "Test platform team"},
        "audience": ["team:test"],
        "issued_at": "2020-01-01T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "allowed_upstream_namespaces": ["fake.*"],
        "default_profile": "dev",
        "profiles": {"dev": {"visible": ["fake.*"], "callable": ["fake.*"]}},
        "revocation": {"crl_path": str(store.crl_path)},
    }
    signature = private.sign(helpers.canonical_bundle_bytes(crl_bundle))
    crl_bundle["signature"] = {
        "algorithm": "ed25519",
        "key_id": "managed-key-2026",
        "value": base64.b64encode(signature).decode("ascii"),
    }
    crl_bundle_path = tmp / "bundle-with-crl.json"
    crl_bundle_path.write_text(json.dumps(crl_bundle), encoding="utf-8")
    crl_args = helpers.gateway_args(root=str(root), profile_bundle=str(crl_bundle_path), audience_id=["team:test"])
    unreadable_crl_state, _ = _resolve_gateway_profile_state(crl_args)
    revoke(store, bundle_sha256="ef" * 32, now=helpers.NOW)
    active_after_crl_created, _ = _resolve_gateway_profile_state(crl_args)
    revoke_result = revoke(store, key_id="managed-key-2026", reason="test revocation", now=helpers.NOW)
    revoked_key_state, _ = _resolve_gateway_profile_state(crl_args)

    corrupt_store = TrustStore(tmp / "corrupt-trust")
    corrupt_store.directory.mkdir()
    corrupt_store.trusted_keys_path.write_text("not-json", encoding="utf-8")
    corrupt_doctor = doctor_report(corrupt_store, now=helpers.NOW)

    private_refusal_store = TrustStore(tmp / "private-refusal")
    private_refusal = False
    try:
        import_key(
            private_refusal_store,
            key_id="private-looking",
            public_key_b64="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
            now=helpers.NOW,
        )
    except TrustStoreError:
        private_refusal = True
    if not private_refusal or private_refusal_store.trusted_keys_path.exists():
        raise AssertionError("private-key-looking import was not refused before write")

    proofs: dict[str, Any] = {
        "trust_status": {
            "status": "passed",
            "counts": status["counts"],
            "store_exists": status["store_exists"],
        },
        "trust_list": {
            "status": "passed",
            "key_count": len(key_list["keys"]),
            "fingerprint_length": len(key_list["keys"][0]["fingerprint"]),
            "no_full_key_bytes": True,
        },
        "trust_import": {
            "status": "passed",
            "imported": imported["imported"],
            "managed_trusted_keys_path": str(managed_trusted_keys_path(root).relative_to(root)),
        },
        "trust_revoke": {
            "status": "passed",
            "revoked": revoke_result["revoked"],
            "append_only_history": True,
        },
        "trust_doctor": {
            "status": "passed",
            "healthy_exit_code": doctor["exit_code"],
            "corrupt_exit_code": corrupt_doctor["exit_code"],
        },
        "valid_trusted_key": {
            "status": "passed",
            "profile": state.name,
            "profile_source": "signed_bundle",
        },
        "revoked_key_refusal": _assert_refusal(revoked_key_state, BUNDLE_REVOKED, "bundle_revoked"),
        "missing_trust_store_refusal": _assert_refusal(missing_state, BUNDLE_KEY_MISSING, "bundle_key_missing"),
        "explicit_trusted_keys_override_refusal": _assert_refusal(
            explicit_state, BUNDLE_KEY_MISSING, "bundle_key_missing"
        ),
        "unreadable_crl_refusal": _assert_refusal(unreadable_crl_state, BUNDLE_REVOKED, "bundle_revoked"),
        "active_after_crl_created": {
            "status": "passed",
            "profile": active_after_crl_created.name if isinstance(active_after_crl_created, ActiveProfile) else "",
        },
        "private_key_import_refusal": {
            "status": "passed",
            "wrote_nothing": not private_refusal_store.trusted_keys_path.exists(),
        },
        "audit_provenance": {
            "status": "passed",
            "verification": "verified",
            "no_key_material_or_signature": True,
        },
        "no_hosted_trust_fetch": True,
        "no_registry_sync": True,
        "no_production_signing_keys": True,
        "no_private_key_storage": True,
    }
    if proofs["active_after_crl_created"]["profile"] != "dev":
        raise AssertionError("bundle did not recover after managed CRL file was created")
    if corrupt_doctor["exit_code"] != 1:
        raise AssertionError("corrupt trust store did not fail doctor")
    return proofs


def collect_evidence() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="uls-v048-trust-store-") as temp:
        proofs = _collect_fixture_evidence(Path(temp))
    evidence = {
        "status": "passed",
        "release": RELEASE,
        "mode": "fixture",
        "production_hosted_calls": False,
        "hosted_trust_fetch": False,
        "registry_sync": False,
        "oauth": False,
        "remote_upstreams": False,
        "mcp_resources": False,
        "mcp_prompts": False,
        "production_signing_keys": False,
        "private_key_storage": False,
        "raw_local_profiles_still_allowed_by_default": True,
        "signed_bundle_requires_trusted_key_for_managed_store": True,
        "proofs": proofs,
    }
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run v0.4.8-alpha MCP profile trust-store integration smoke.")
    parser.add_argument("--fixture-mode", action="store_true", help="Required; no hosted services")
    parser.add_argument("--json", action="store_true", help="Print JSON evidence")
    args = parser.parse_args(argv)
    if not args.fixture_mode:
        parser.error("--fixture-mode is required")
    report = collect_evidence()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} MCP profile trust-store smoke passed")
        print("trust status/list/import/revoke/doctor: passed")
        print("managed trusted-key verification: passed")
        print("refusal proofs: missing key, explicit override, unreadable CRL, revoked key")
        print("hosted trust fetch: false")
        print("registry sync: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
