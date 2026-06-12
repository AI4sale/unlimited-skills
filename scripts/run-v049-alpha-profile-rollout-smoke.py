from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4.9-alpha"


def _load_rollout_tests():
    path = ROOT / "tests" / "test_mcp_profile_rollout.py"
    spec = importlib.util.spec_from_file_location("v049_rollout_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load rollout helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _finding_ids(report: dict[str, Any], severity: str | None = None) -> list[str]:
    return [
        str(item["finding"])
        for item in report.get("findings", [])
        if severity is None or item.get("severity") == severity
    ]


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _file_snapshot(root: Path) -> dict[str, int]:
    return {str(path.relative_to(root)): path.stat().st_mtime_ns for path in root.rglob("*") if path.is_file()}


def _assert_doctor_finding(report: dict[str, Any], finding: str, severity: str) -> dict[str, Any]:
    ids = _finding_ids(report, severity)
    _expect(finding in ids, f"missing {severity} finding: {finding}; got {report.get('findings')}")
    return {"status": "passed", "finding": finding, "severity": severity, "exit_code": report["exit_code"]}


def _with_blocked_side_effects(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    old_popen = subprocess.Popen
    old_socket = socket.socket
    old_urlopen = urllib.request.urlopen

    def forbidden(*_args, **_kwargs):  # pragma: no cover - failure path
        raise AssertionError("v0.4.9 rollout smoke must not spawn, open sockets, or fetch URLs")

    subprocess.Popen = forbidden  # type: ignore[assignment]
    socket.socket = forbidden  # type: ignore[assignment]
    urllib.request.urlopen = forbidden  # type: ignore[assignment]
    try:
        return action()
    finally:
        subprocess.Popen = old_popen  # type: ignore[assignment]
        socket.socket = old_socket  # type: ignore[assignment]
        urllib.request.urlopen = old_urlopen  # type: ignore[assignment]


def _collect_fixture_evidence(tmp: Path) -> dict[str, Any]:
    helpers = _load_rollout_tests()

    raw_plan = helpers.plan(
        tmp,
        profiles_path=str(helpers.profiles_path(tmp)),
        tools_fixture_path=str(helpers.fixture_path(tmp)),
        profile_name="reviewer",
    )
    _expect(raw_plan["profile_state"]["mode"] == "enforced", "raw profile plan did not enforce reviewer")
    _expect(raw_plan["tools"]["visible"] == 2 and raw_plan["tools"]["callable"] == 1, "raw plan counts drifted")

    bundle, keys, _document = helpers.bundle_env(tmp)
    signed_plan = helpers.plan(
        tmp,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
        tools_fixture_path=str(helpers.fixture_path(tmp)),
    )
    _expect(signed_plan["verification"]["ok"] is True, "signed bundle rollout plan did not verify")
    _expect(signed_plan["profile_state"]["source"] == "signed_bundle", "signed plan source mismatch")

    managed_root = tmp / "managed-library"
    store_keys = managed_root / ".unlimited-skills-trust" / "trusted-keys.json"
    store_keys.parent.mkdir(parents=True)
    helpers.write_json(store_keys, helpers.trusted_keys_doc([(helpers.KEY_ID, helpers.FAKE_PUBLIC, None)]))
    managed_plan = helpers.plan(
        tmp,
        root=managed_root,
        bundle_path=str(bundle),
        audience_ids=["team:test"],
        tools_fixture_path=str(helpers.fixture_path(tmp)),
    )
    _expect(managed_plan["inputs"]["trusted_keys_source"] == "managed", "managed trust store was not used")
    _expect(managed_plan["verification"]["ok"] is True, "managed trust-store rollout did not verify")

    missing_store = helpers.doctor(tmp, bundle_path=str(bundle), audience_ids=["team:test"])

    corrupt_dir = tmp / "corrupt"
    corrupt_dir.mkdir()
    corrupt_bundle, corrupt_keys, _ = helpers.bundle_env(corrupt_dir)
    corrupt_keys.write_text("{not json", encoding="utf-8")
    corrupt_store = helpers.doctor(
        tmp, bundle_path=str(corrupt_bundle), trusted_keys_path=str(corrupt_keys), audience_ids=["team:test"]
    )

    expired_dir = tmp / "expired"
    expired_dir.mkdir()
    expired_bundle, expired_keys, _ = helpers.bundle_env(expired_dir, not_after="2026-06-15T00:00:00Z")
    expired_key = helpers.doctor(
        tmp, bundle_path=str(expired_bundle), trusted_keys_path=str(expired_keys), audience_ids=["team:test"]
    )

    revoked_dir = tmp / "revoked"
    revoked_dir.mkdir()
    crl = helpers.write_json(
        revoked_dir / "crl.json",
        {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": [helpers.KEY_ID]},
    )

    def declare_crl(document: dict) -> None:
        document["revocation"] = {"crl_path": str(crl)}

    revoked_bundle, revoked_keys, _ = helpers.bundle_env(revoked_dir, mutate=declare_crl)
    revoked_key = helpers.doctor(
        tmp, bundle_path=str(revoked_bundle), trusted_keys_path=str(revoked_keys), audience_ids=["team:test"]
    )

    wrong_audience = helpers.doctor(
        tmp, bundle_path=str(bundle), trusted_keys_path=str(keys), audience_ids=["team:somebody-else"]
    )

    def widen(document: dict) -> None:
        document["profiles"]["dev"]["visible"] = ["fake.*", "other.*", "payments.charge"]

    scope_dir = tmp / "scope"
    scope_dir.mkdir()
    scope_bundle, scope_keys, _ = helpers.bundle_env(scope_dir, mutate=widen)
    namespace_violation = helpers.doctor(
        tmp, bundle_path=str(scope_bundle), trusted_keys_path=str(scope_keys), audience_ids=["team:test"]
    )

    hide_all_doc = {
        "schema_version": 1,
        "default_profile": "ghosts",
        "profiles": {"ghosts": {"visible": ["ghost.*"], "callable": ["ghost.*"]}},
    }
    hide_all_dir = tmp / "hide-all"
    hide_all_dir.mkdir()
    hide_all = helpers.doctor(
        tmp,
        profiles_path=str(helpers.profiles_path(hide_all_dir, hide_all_doc)),
        tools_fixture_path=str(helpers.fixture_path(tmp)),
    )
    shadowed_dir = tmp / "shadowed"
    shadowed_dir.mkdir()
    shadowed = helpers.doctor(
        tmp,
        profiles_path=str(helpers.profiles_path(shadowed_dir)),
        tools_fixture_path=str(helpers.fixture_path(tmp)),
        profile_name="dev",
    )
    unsigned_dir = tmp / "unsigned"
    unsigned_dir.mkdir()
    unsigned_required = helpers.doctor(
        tmp,
        profiles_path=str(helpers.profiles_path(unsigned_dir)),
        require_signed=True,
        tools_fixture_path=str(helpers.fixture_path(tmp)),
    )

    readonly_dir = tmp / "readonly"
    readonly_dir.mkdir()
    readonly_root = readonly_dir / "library"
    readonly_root.mkdir()
    readonly_bundle, readonly_keys, _ = helpers.bundle_env(readonly_dir)
    readonly_config = helpers.config_path(readonly_dir)
    before = _file_snapshot(readonly_dir)

    def dryrun_action() -> dict[str, Any]:
        plan = helpers.plan(
            readonly_dir,
            root=readonly_root,
            config_path=str(readonly_config),
            bundle_path=str(readonly_bundle),
            trusted_keys_path=str(readonly_keys),
            audience_ids=["team:test"],
        )
        doctor = helpers.doctor(
            readonly_dir,
            root=readonly_root,
            config_path=str(readonly_config),
            bundle_path=str(readonly_bundle),
            trusted_keys_path=str(readonly_keys),
            audience_ids=["team:test"],
        )
        return {"plan": plan, "doctor": doctor}

    readonly = _with_blocked_side_effects(dryrun_action)
    after = _file_snapshot(readonly_dir)
    _expect(after == before, "rollout simulator mutated files")
    _expect(not (readonly_root / ".learning").exists(), "rollout simulator wrote audit rows")
    _expect(readonly["plan"]["verification"]["ok"] is True, "readonly plan verification failed")

    proofs = {
        "raw_profile_rollout_plan": {
            "status": "passed",
            "mode": raw_plan["profile_state"]["mode"],
            "visible": raw_plan["tools"]["visible"],
            "callable": raw_plan["tools"]["callable"],
            "refused_by_policy": raw_plan["tools"]["refused_by_policy"],
        },
        "signed_bundle_rollout_plan": {
            "status": "passed",
            "source": signed_plan["profile_state"]["source"],
            "verification_ok": signed_plan["verification"]["ok"],
            "audit_provenance": bool(signed_plan["audit_impact"]["profile_loaded_row"].get("bundle_sha256")),
        },
        "trust_store_backed_rollout_plan": {
            "status": "passed",
            "trusted_keys_source": managed_plan["inputs"]["trusted_keys_source"],
            "verification_ok": managed_plan["verification"]["ok"],
        },
        "missing_trust_store": _assert_doctor_finding(missing_store, "trust_store_missing", "problem"),
        "corrupt_trust_store": _assert_doctor_finding(corrupt_store, "trust_store_corrupt", "problem"),
        "expired_key": _assert_doctor_finding(expired_key, "key_expired", "problem"),
        "revoked_key": _assert_doctor_finding(revoked_key, "key_revoked", "problem"),
        "wrong_audience": _assert_doctor_finding(wrong_audience, "audience_mismatch", "problem"),
        "namespace_violation": _assert_doctor_finding(namespace_violation, "issuer_scope_violation", "problem"),
        "hide_all_tools": _assert_doctor_finding(hide_all, "profile_hides_all_tools", "problem"),
        "shadowed_tool": _assert_doctor_finding(shadowed, "shadowed_tool_name", "warning"),
        "signed_required_unsigned_source": _assert_doctor_finding(
            unsigned_required, "unsigned_under_signed_policy", "problem"
        ),
        "no_upstream_spawn": True,
        "no_network": True,
        "no_mutation": after == before and not (readonly_root / ".learning").exists(),
    }
    return proofs


def collect_evidence() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="uls-v049-profile-rollout-") as temp:
        proofs = _collect_fixture_evidence(Path(temp))
    return {
        "status": "passed",
        "release": RELEASE,
        "mode": "fixture",
        "production_hosted_calls": False,
        "hosted_trust_fetch": False,
        "registry_sync": False,
        "profile_activation": False,
        "trust_store_mutation": False,
        "oauth": False,
        "remote_upstreams": False,
        "mcp_resources": False,
        "mcp_prompts": False,
        "production_signing_keys": False,
        "private_key_storage": False,
        "telemetry": False,
        "proofs": proofs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run v0.4.9-alpha MCP profile rollout integration smoke.")
    parser.add_argument("--fixture-mode", action="store_true", help="Required; no hosted services")
    parser.add_argument("--json", action="store_true", help="Print JSON evidence")
    args = parser.parse_args(argv)
    if not args.fixture_mode:
        parser.error("--fixture-mode is required")
    report = collect_evidence()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{RELEASE} MCP profile rollout smoke passed")
        print("rollout-plan proofs: raw profile, signed bundle, managed trust store")
        print("doctor findings: missing/corrupt/expired/revoked/wrong-audience/namespace/hide-all/shadowed/signed-required")
        print("no upstream spawn: true")
        print("no network: true")
        print("no mutation: true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
