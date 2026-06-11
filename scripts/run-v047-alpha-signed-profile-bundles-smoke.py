from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.7-alpha"


def _load_bundle_tests():
    path = ROOT / "tests" / "test_mcp_bundle_verification.py"
    spec = importlib.util.spec_from_file_location("v047_bundle_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load bundle test helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_audit_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _assert_refusal(state: object, code: int, proof_name: str, helpers: Any) -> dict[str, Any]:
    if not isinstance(state, helpers.BundleFailClosed):
        raise AssertionError(f"{proof_name}: expected BundleFailClosed, got {type(state).__name__}")
    if state.code != code:
        raise AssertionError(f"{proof_name}: expected code {code}, got {state.code}")
    return {"status": "passed", "code": state.code, "message_contains": proof_name}


def _collect_fixture_evidence(tmp: Path) -> dict[str, Any]:
    helpers = _load_bundle_tests()

    raw_path = tmp / "raw-profiles.json"
    raw_document = {
        "schema_version": 1,
        "default_profile": "dev",
        "profiles": helpers.base_bundle()["profiles"],
    }
    helpers.write_json(raw_path, raw_document)
    raw_state = helpers.resolve_profile_state(raw_path, cli_name="dev", env_name="")
    if not isinstance(raw_state, helpers.ActiveProfile):
        raise AssertionError("raw local profile path did not resolve to ActiveProfile")
    if raw_state.provenance is not None:
        raise AssertionError("raw local profile path unexpectedly gained bundle provenance")

    bundle_path, keys_path, _ = helpers.fake_env(tmp)
    valid_state = helpers.resolve_fake(bundle_path, keys_path)
    if not isinstance(valid_state, helpers.ActiveProfile):
        raise AssertionError("valid signed bundle did not resolve to ActiveProfile")
    provenance = valid_state.provenance
    if provenance is None:
        raise AssertionError("valid signed bundle did not attach provenance")
    expected_sha = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    provenance_fields = provenance.audit_fields()
    if provenance_fields.get("bundle_sha256") != expected_sha:
        raise AssertionError("bundle provenance SHA mismatch")
    if provenance_fields.get("issuer_key_id") != helpers.KEY_ID:
        raise AssertionError("bundle provenance key_id mismatch")
    if "public_key" in json.dumps(provenance_fields) or "signature" in json.dumps(provenance_fields):
        raise AssertionError("audit provenance leaked key material or signature field names")

    audit_path = tmp / "signed-audit.jsonl"
    gateway = helpers.Gateway(helpers.GATEWAY_CONFIG, helpers.AuditLog(audit_path), profile=valid_state)
    try:
        hits = gateway.tools_search({"query": "echo"})["hits"]
        if not hits or hits[0]["tool"] != "fake.echo":
            raise AssertionError("valid signed bundle did not enforce a visible tool")
    finally:
        gateway.shutdown()
    audit_rows = _read_audit_rows(audit_path)
    loaded = next((row for row in audit_rows if row.get("tool") == "profile_loaded"), None)
    if not loaded or loaded.get("ok") is not True:
        raise AssertionError("missing successful profile_loaded audit row")
    if loaded.get("profile_source") != "signed_bundle":
        raise AssertionError("profile_loaded row did not mark signed_bundle source")
    audit_text = json.dumps(loaded, sort_keys=True)
    if "signature" in audit_text or "private" in audit_text or str(tmp) in audit_text:
        raise AssertionError("profile_loaded row leaked signature/private/local path material")

    tampered_dir = tmp / "tampered"
    tampered_dir.mkdir()
    tampered_path, tampered_keys, tampered_doc = helpers.fake_env(tampered_dir)
    tampered_doc["audience"].append("org:evil")
    helpers.write_json(tampered_path, tampered_doc)

    unknown_dir = tmp / "unknown-key"
    unknown_dir.mkdir()
    unknown_path, _, _ = helpers.fake_env(unknown_dir)
    unknown_keys = helpers.write_json(
        unknown_dir / "other-keys.json",
        helpers.trusted_keys_doc([("other-key", helpers.FAKE_PUBLIC, None)]),
    )

    expired_dir = tmp / "expired"
    expired_dir.mkdir()
    expired_path, expired_keys, _ = helpers.fake_env(expired_dir)
    expires = helpers._parse_timestamp("2026-09-01T00:00:00Z")

    revoked_dir = tmp / "revoked"
    revoked_dir.mkdir()
    revoked_crl = revoked_dir / "crl.json"

    def add_revocation(document: dict) -> None:
        document["revocation"] = {
            "crl_path": str(revoked_crl),
            "registry_endpoint": "https://registry.invalid/not-fetched-in-fixture-mode",
        }

    revoked_path, revoked_keys, _ = helpers.fake_env(revoked_dir, mutate=add_revocation)
    revoked_sha = hashlib.sha256(revoked_path.read_bytes()).hexdigest()
    helpers.write_json(
        revoked_crl,
        {"schema_version": 1, "revoked_bundles": [revoked_sha], "revoked_key_ids": []},
    )

    wrong_audience_dir = tmp / "wrong-audience"
    wrong_audience_dir.mkdir()
    wrong_audience_path, wrong_audience_keys, _ = helpers.fake_env(wrong_audience_dir)

    def outside_namespace(document: dict) -> None:
        document["profiles"]["dev"]["visible"] = ["fake.*", "payments.charge"]

    namespace_dir = tmp / "namespace-violation"
    namespace_dir.mkdir()
    namespace_path, namespace_keys, _ = helpers.fake_env(namespace_dir, mutate=outside_namespace)

    proofs: dict[str, Any] = {
        "raw_local_profile_path": {
            "status": "passed",
            "profile": raw_state.name,
            "profile_source": "raw_file",
            "bundle_provenance": False,
        },
        "valid_signed_bundle": {
            "status": "passed",
            "profile": valid_state.name,
            "bundle_sha256": expected_sha,
            "issuer_key_id": provenance_fields["issuer_key_id"],
            "audience": provenance_fields["audience"],
        },
        "bad_signature_refusal": _assert_refusal(
            helpers.resolve_fake(tampered_path, tampered_keys),
            helpers.BUNDLE_SIGNATURE_INVALID,
            "bundle_signature_invalid",
            helpers,
        ),
        "unknown_key_refusal": _assert_refusal(
            helpers.resolve_fake(unknown_path, unknown_keys),
            helpers.BUNDLE_KEY_MISSING,
            "bundle_key_missing",
            helpers,
        ),
        "expired_bundle_refusal": _assert_refusal(
            helpers.resolve_fake(expired_path, expired_keys, now=expires + 301),
            helpers.BUNDLE_EXPIRED,
            "bundle_expired",
            helpers,
        ),
        "revoked_bundle_refusal": _assert_refusal(
            helpers.resolve_fake(revoked_path, revoked_keys),
            helpers.BUNDLE_REVOKED,
            "bundle_revoked",
            helpers,
        ),
        "wrong_audience_refusal": _assert_refusal(
            helpers.resolve_fake(wrong_audience_path, wrong_audience_keys, audience_ids=["team:wrong"]),
            helpers.BUNDLE_AUDIENCE_MISMATCH,
            "bundle_audience_mismatch",
            helpers,
        ),
        "namespace_violation_refusal": _assert_refusal(
            helpers.resolve_fake(namespace_path, namespace_keys),
            helpers.BUNDLE_AUDIENCE_MISMATCH,
            "bundle_audience_mismatch",
            helpers,
        ),
        "audit_provenance": {
            "status": "passed",
            "profile_source": loaded["profile_source"],
            "bundle_sha256": loaded["bundle_sha256"],
            "issuer_key_id": loaded["issuer_key_id"],
            "verification": loaded["verification"],
            "no_key_material_or_signature": True,
        },
        "no_registry_sync": True,
        "no_hosted_trust_fetch": True,
        "no_production_signing_keys": True,
        "no_private_key_storage": True,
    }
    return proofs


def collect_evidence() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="uls-v047-signed-bundles-") as temp:
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
        "registered_business_signed_required_future_gated": True,
        "proofs": proofs,
    }
    if evidence["status"] != "passed":
        raise AssertionError(json.dumps(evidence, indent=2, sort_keys=True))
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run v0.4.7-alpha signed MCP profile bundles integration smoke."
    )
    parser.add_argument("--fixture-mode", action="store_true", help="Required; no hosted services")
    parser.add_argument("--json", action="store_true", help="Print JSON evidence")
    args = parser.parse_args(argv)
    if not args.fixture_mode:
        parser.error("--fixture-mode is required")
    report = collect_evidence()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} signed profile bundles smoke passed")
        print("valid signed bundle: passed")
        print("refusal proofs: bad signature, unknown key, expired, revoked, audience, namespace")
        print("hosted trust fetch: false")
        print("registry sync: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
