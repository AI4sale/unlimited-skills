"""E16: MCP profile bundle rollout simulator and policy doctor.

Proves the contract of docs/mcp-profile-rollout.md against
``unlimited_skills.mcp.profile_rollout`` and the ``unlimited-skills mcp
profiles rollout-plan|doctor`` CLI:

- plan math: visible/hidden/callable/view-only/refused-by-policy counts over
  a fixture tool list and over the config's pre-declared tools, in open,
  enforced, and fail-closed modes;
- the inheritance summary narrows monotonically along the extends chain;
- upstreams that lose all visibility are reported as never-spawning;
- the trust verification summary is the REAL E14 ``resolve_bundle_state``
  run in dry-run (exact refusal codes per failing step), and the audit
  impact mirrors the gateway's ``profile_loaded`` row field-for-field;
- the doctor emits every distinct finding class with its severity and the
  documented exit codes (0 clean / 1 problems);
- ``--json`` plans validate against
  ``schemas/mcp-profile-rollout-plan.schema.json`` (the repo's
  self-contained validator pattern -- no jsonschema dependency), and the
  shipped example validates too;
- NO-SPAWN / read-only proof: planning never creates a subprocess and never
  writes a single file (no audit rows, no store mutations);
- CLI wiring through the cli facade (main(...) dispatch, --json shapes,
  exit codes) and dispatch parity with the gateway's own
  ``_resolve_gateway_profile_state``.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import re
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from unlimited_skills.cli import main
from unlimited_skills.commands.mcp import _resolve_gateway_profile_state
from unlimited_skills.mcp.bundles import (
    BUNDLE_AUDIENCE_MISMATCH,
    BUNDLE_EXPIRED,
    BUNDLE_KEY_MISSING,
    BUNDLE_REVOKED,
    BUNDLE_SIGNATURE_INVALID,
    SignatureBackend,
    canonical_bundle_bytes,
    _parse_timestamp,
)
from unlimited_skills.mcp.profiles import PROFILE_INVALID, PROFILE_NOT_FOUND
from unlimited_skills.mcp.profile_rollout import (
    doctor_rollout,
    format_rollout_doctor,
    format_rollout_plan,
    plan_rollout,
    read_tools_fixture,
    refusal_name,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "mcp-profile-rollout-plan.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "mcp" / "profile-rollout-plan.example.json"

KEY_ID = "test-team-profiles-2026"
NOW = _parse_timestamp("2026-07-01T00:00:00Z")  # inside the base validity window


# ---------------------------------------------------------------------------
# The repo's minimal self-contained JSON Schema validator (same stance as
# tests/test_mcp_profile_bundle_schema.py: no jsonschema dependency).

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _check_type(value: object, expected: str, path: str) -> list[str]:
    python_type = _TYPES[expected]
    if expected in ("number", "integer") and isinstance(value, bool):
        return [f"{path}: expected {expected}, got bool"]
    if not isinstance(value, python_type):
        return [f"{path}: expected {expected}, got {type(value).__name__}"]
    return []


def validate(value: object, schema: dict, path: str = "$") -> list[str]:
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']!r}")
    if "type" in schema:
        type_errors = _check_type(value, schema["type"], path)
        if type_errors:
            return errors + type_errors
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(validate(item, properties[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: additional property {key!r} not allowed")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(validate(item, schema["items"], f"{path}[{index}]"))
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    return errors


@pytest.fixture(scope="module")
def plan_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Builders: bundle/trusted-keys/CRL fixtures with a TEST-ONLY HMAC backend
# (the same pattern as tests/test_mcp_bundle_verification.py -- exercises
# the real verification ORDER without the optional cryptography package).


class FakeHmacBackend(SignatureBackend):
    name = "test-only-hmac"

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(hmac.new(public_key, message, "sha256").digest(), signature)


FAKE_PUBLIC = b"\x07" * 32


def sign_fake(document: dict, key_id: str = KEY_ID, public_key: bytes = FAKE_PUBLIC) -> dict:
    signature = hmac.new(public_key, canonical_bundle_bytes(document), "sha256").digest()
    document["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id,
        "value": base64.b64encode(signature).decode("ascii"),
    }
    return document


def base_bundle(key_id: str = KEY_ID) -> dict:
    return {
        "bundle_version": 1,
        "issuer": {"key_id": key_id, "display": "Test platform team"},
        "audience": ["team:test", "host:ci"],
        "issued_at": "2026-06-01T00:00:00Z",
        "expires_at": "2026-09-01T00:00:00Z",
        "allowed_upstream_namespaces": ["fake.*", "other.*"],
        "default_profile": "dev",
        "profiles": {
            "dev": {"visible": ["fake.*", "other.*"], "callable": ["fake.*", "other.*"]},
            "reviewer": {
                "extends": "dev",
                "visible": ["fake.echo", "fake.add"],
                "callable": ["fake.echo"],
            },
        },
    }


def write_json(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def trusted_keys_doc(entries: list[tuple[str, bytes, str | None]]) -> dict:
    keys = []
    for key_id, public, not_after in entries:
        entry: dict = {
            "key_id": key_id,
            "algorithm": "ed25519",
            "public_key": base64.b64encode(public).decode("ascii"),
        }
        if not_after:
            entry["not_after"] = not_after
        keys.append(entry)
    return {"schema_version": 1, "keys": keys}


PROFILES_DOC = {
    "schema_version": 1,
    "default_profile": "dev",
    "profiles": {
        "dev": {"visible": ["fake.*", "other.*"], "callable": ["fake.*", "other.*"]},
        "reviewer": {
            "extends": "dev",
            "visible": ["fake.echo", "fake.add"],
            "callable": ["fake.echo"],
        },
        "ci": {"extends": "reviewer", "visible": ["fake.echo"], "callable": ["fake.echo"]},
    },
}

FIXTURE_TOOLS = [
    {"upstream": "fake", "name": "echo", "description": "Echo a message"},
    {"upstream": "fake", "name": "add", "description": "Add two numbers"},
    {"upstream": "other", "name": "echo", "description": "Echo on another upstream"},
]

GATEWAY_CONFIG = {
    "schema_version": 1,
    "upstreams": [
        {
            "name": "fake",
            "command": "/abs/fake-upstream",
            "tools": [
                {"name": "echo", "description": "Echo a message"},
                {"name": "add", "description": "Add two numbers"},
            ],
        },
        {
            "name": "other",
            "command": "/abs/other-upstream",
            "audit_level": "minimal",
            "tools": [{"name": "echo", "description": "Echo on another upstream"}],
        },
        {
            "name": "off",
            "command": "/abs/off-upstream",
            "enabled": False,
            "tools": [{"name": "never", "description": "Pre-declared but disabled"}],
        },
    ],
}


def fixture_path(tmp_path: Path) -> Path:
    return write_json(tmp_path / "tools.json", FIXTURE_TOOLS)


def profiles_path(tmp_path: Path, document: dict | None = None) -> Path:
    return write_json(tmp_path / "profiles.json", document or PROFILES_DOC)


def config_path(tmp_path: Path, document: dict | None = None) -> Path:
    return write_json(tmp_path / "gateway.json", document or GATEWAY_CONFIG)


def bundle_env(tmp_path: Path, mutate=None, key_id: str = KEY_ID, not_after: str | None = None):
    document = base_bundle(key_id)
    if mutate is not None:
        mutate(document)
    sign_fake(document, key_id)
    bundle = write_json(tmp_path / "bundle.json", document)
    keys = write_json(tmp_path / "trusted-keys.json", trusted_keys_doc([(key_id, FAKE_PUBLIC, not_after)]))
    return bundle, keys, document


def plan(tmp_path: Path, **kwargs) -> dict:
    kwargs.setdefault("root", tmp_path / "library")
    kwargs.setdefault("env_name", "")
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("backend", FakeHmacBackend())
    return plan_rollout(**kwargs)


def doctor(tmp_path: Path, **kwargs) -> dict:
    kwargs.setdefault("root", tmp_path / "library")
    kwargs.setdefault("env_name", "")
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("backend", FakeHmacBackend())
    return doctor_rollout(**kwargs)


def finding_ids(report: dict, severity: str | None = None) -> list[str]:
    return [
        item["finding"]
        for item in report["findings"]
        if severity is None or item["severity"] == severity
    ]


# ---------------------------------------------------------------------------
# Plan math.


def test_plan_math_enforced_profile_over_fixture(tmp_path: Path, plan_schema: dict) -> None:
    result = plan(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path)),
        tools_fixture_path=str(fixture_path(tmp_path)),
        profile_name="reviewer",
    )
    assert validate(result, plan_schema) == []
    assert result["profile_state"]["mode"] == "enforced"
    assert result["profile_state"]["source"] == "raw_file"
    tools = result["tools"]
    assert tools["total"] == 3
    assert tools["visible"] == 2
    assert tools["hidden"] == 1
    assert tools["callable"] == 1
    assert tools["view_only"] == 1
    assert tools["refused_by_policy"] == 2  # hidden (-32011) + view-only (-32012)
    assert tools["visible_tools"] == ["fake.add", "fake.echo"]
    assert tools["hidden_tools"] == ["other.echo"]
    assert result["blockers"] == []


def test_plan_open_mode_everything_visible_and_callable(tmp_path: Path, plan_schema: dict) -> None:
    result = plan(tmp_path, tools_fixture_path=str(fixture_path(tmp_path)))
    assert validate(result, plan_schema) == []
    assert result["profile_state"]["mode"] == "open"
    assert result["tools"]["visible"] == 3
    assert result["tools"]["callable"] == 3
    assert result["tools"]["refused_by_policy"] == 0
    assert result["audit_impact"]["profile_loaded_row_recorded"] is False
    assert result["audit_impact"]["per_call_rows_carry_profile"] is False


def test_plan_config_tools_default_and_disabled_upstreams_excluded(
    tmp_path: Path, plan_schema: dict
) -> None:
    result = plan(
        tmp_path,
        config_path=str(config_path(tmp_path)),
        profiles_path=str(profiles_path(tmp_path)),
        profile_name="dev",
    )
    assert validate(result, plan_schema) == []
    assert result["inputs"]["tools_source"] == "config"
    # The disabled upstream's pre-declared tool never enters the plan.
    assert result["tools"]["total"] == 3
    assert all(not fq.startswith("off.") for fq in result["tools"]["visible_tools"])
    assert any("never spawned" in warning for warning in result["warnings"])
    rows = {row["name"]: row for row in result["upstreams"]}
    assert rows["off"]["spawnable"] is False
    assert rows["off"]["would_spawn"] is False
    assert rows["fake"]["would_spawn"] is True
    # Audit level effects come from the config.
    assert result["audit_impact"]["audit_levels"] == {"standard": 2, "minimal": 1}


def test_plan_fail_closed_raw_file(tmp_path: Path, plan_schema: dict) -> None:
    bad = write_json(tmp_path / "broken.json", {"schema_version": 1, "profiles": "nope"})
    result = plan(
        tmp_path,
        profiles_path=str(bad),
        tools_fixture_path=str(fixture_path(tmp_path)),
    )
    assert validate(result, plan_schema) == []
    state = result["profile_state"]
    assert state["mode"] == "fail_closed"
    assert state["refusal_code"] == PROFILE_INVALID
    assert state["refusal_name"] == "profile_invalid"
    assert result["tools"]["visible"] == 0
    assert result["tools"]["refused_by_policy"] == result["tools"]["total"] == 3
    assert any("FAIL CLOSED" in blocker for blocker in result["blockers"])
    # A raw-file fail-closed state records no profile_loaded startup row.
    assert result["audit_impact"]["profile_loaded_row_recorded"] is False
    assert result["audit_impact"]["per_call_rows_carry_profile"] is True


def test_plan_unknown_profile_name_fail_closed(tmp_path: Path) -> None:
    result = plan(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path)),
        profile_name="ghost",
        tools_fixture_path=str(fixture_path(tmp_path)),
    )
    assert result["profile_state"]["refusal_code"] == PROFILE_NOT_FOUND
    assert result["profile_state"]["profile"] == "ghost"


def test_plan_upstream_losing_all_visibility_never_spawns(tmp_path: Path) -> None:
    result = plan(
        tmp_path,
        config_path=str(config_path(tmp_path)),
        profiles_path=str(profiles_path(tmp_path)),
        profile_name="reviewer",  # visible: fake.echo, fake.add only
    )
    rows = {row["name"]: row for row in result["upstreams"]}
    assert rows["other"]["loses_all_visibility"] is True
    assert rows["other"]["would_spawn"] is False
    assert "never spawn" in rows["other"]["note"]
    assert rows["fake"]["loses_all_visibility"] is False
    assert rows["fake"]["would_spawn"] is True


def test_plan_inheritance_narrows_monotonically(tmp_path: Path) -> None:
    result = plan(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path)),
        tools_fixture_path=str(fixture_path(tmp_path)),
        profile_name="ci",
    )
    inheritance = result["inheritance"]
    assert inheritance["available"] is True
    assert inheritance["chain"] == ["ci", "reviewer", "dev"]
    assert inheritance["depth"] == 3
    steps = inheritance["steps"]
    assert [step["profile"] for step in steps] == ["dev", "reviewer", "ci"]
    visible_counts = [step["visible_tools_after_step"] for step in steps]
    callable_counts = [step["callable_tools_after_step"] for step in steps]
    assert visible_counts == [3, 2, 1]
    assert callable_counts == [3, 1, 1]
    # Restriction-only inheritance: counts never increase along the chain.
    assert visible_counts == sorted(visible_counts, reverse=True)
    assert callable_counts == sorted(callable_counts, reverse=True)


# ---------------------------------------------------------------------------
# Trust verification summary: the REAL E14 verification in dry-run.


def test_plan_verified_bundle_reports_provenance_and_audit_fields(
    tmp_path: Path, plan_schema: dict
) -> None:
    bundle, keys, document = bundle_env(tmp_path)
    result = plan(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
        tools_fixture_path=str(fixture_path(tmp_path)),
    )
    assert validate(result, plan_schema) == []
    verification = result["verification"]
    assert verification["attempted"] is True
    assert verification["ok"] is True
    assert verification["bundle_sha256"] == hashlib.sha256(
        (tmp_path / "bundle.json").read_bytes()
    ).hexdigest()
    assert verification["issuer_key_id"] == KEY_ID
    assert verification["audience"] == ["team:test", "host:ci"]
    assert verification["expires_at"] == "2026-09-01T00:00:00Z"
    # The audit impact mirrors the gateway's profile_loaded row fields.
    row = result["audit_impact"]["profile_loaded_row"]
    assert row["profile_source"] == "signed_bundle"
    assert row["verification"] == "verified"
    assert row["bundle_sha256"] == verification["bundle_sha256"]
    assert row["issuer_key_id"] == KEY_ID
    # No key material or signature values anywhere in the plan.
    dumped = json.dumps(result)
    assert document["signature"]["value"] not in dumped
    assert base64.b64encode(FAKE_PUBLIC).decode("ascii") not in dumped


def test_plan_bundle_narrowed_by_local_file(tmp_path: Path) -> None:
    bundle, keys, _ = bundle_env(tmp_path)
    local = write_json(
        tmp_path / "local.json",
        {
            "schema_version": 1,
            "profiles": {"dev": {"visible": ["fake.echo"], "callable": ["fake.echo"]}},
        },
    )
    result = plan(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        profiles_path=str(local),
        audience_ids=["team:test"],
        tools_fixture_path=str(fixture_path(tmp_path)),
    )
    assert result["profile_state"]["source"] == "signed_bundle_narrowed"
    assert result["inheritance"]["narrowed_by_local_file"] is True
    # The local file narrowed dev (fake.*/other.*) down to fake.echo only.
    assert result["tools"]["visible_tools"] == ["fake.echo"]
    assert result["audit_impact"]["profile_loaded_row"]["local_profile_sha256"]


@pytest.mark.parametrize(
    "mutate_kwargs, code, name, step",
    [
        (
            {"trusted_keys_path": ""},
            BUNDLE_KEY_MISSING,
            "bundle_key_missing",
            "key_lookup",
        ),
        (
            {"now": _parse_timestamp("2027-01-01T00:00:00Z")},
            BUNDLE_EXPIRED,
            "bundle_expired",
            "validity_window",
        ),
        (
            {"audience_ids": ["team:nope"]},
            BUNDLE_AUDIENCE_MISMATCH,
            "bundle_audience_mismatch",
            "audience",
        ),
    ],
)
def test_plan_verification_refusals_carry_exact_codes(
    tmp_path: Path, mutate_kwargs: dict, code: int, name: str, step: str
) -> None:
    bundle, keys, _ = bundle_env(tmp_path)
    kwargs = {
        "bundle_path": str(bundle),
        "trusted_keys_path": str(keys),
        "audience_ids": ["team:test"],
        "tools_fixture_path": str(fixture_path(tmp_path)),
    }
    kwargs.update(mutate_kwargs)
    result = plan(tmp_path, **kwargs)
    verification = result["verification"]
    assert verification["ok"] is False
    assert verification["refusal_code"] == code
    assert verification["refusal_name"] == name == refusal_name(code)
    assert verification["failed_step"] == step
    assert result["profile_state"]["mode"] == "fail_closed"
    assert result["tools"]["visible"] == 0


def test_plan_tampered_bundle_signature_invalid(tmp_path: Path) -> None:
    bundle, keys, document = bundle_env(tmp_path)
    tampered = copy.deepcopy(document)
    tampered["audience"] = ["team:attacker"]
    write_json(tmp_path / "bundle.json", tampered)  # signature now stale
    result = plan(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:attacker"],
        tools_fixture_path=str(fixture_path(tmp_path)),
    )
    assert result["verification"]["refusal_code"] == BUNDLE_SIGNATURE_INVALID
    assert result["verification"]["failed_step"] == "signature"


def test_plan_namespace_ceiling_violation_distinguished_from_audience(tmp_path: Path) -> None:
    def widen(document: dict) -> None:
        document["profiles"]["dev"]["visible"] = ["fake.*", "other.*", "payments.charge"]

    bundle, keys, _ = bundle_env(tmp_path, mutate=widen)
    result = plan(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
        tools_fixture_path=str(fixture_path(tmp_path)),
    )
    assert result["verification"]["refusal_code"] == BUNDLE_AUDIENCE_MISMATCH
    assert result["verification"]["failed_step"] == "namespace_ceiling"


def test_plan_managed_store_default_is_used(tmp_path: Path) -> None:
    bundle, _, _ = bundle_env(tmp_path)
    root = tmp_path / "library"
    store_keys = root / ".unlimited-skills-trust" / "trusted-keys.json"
    store_keys.parent.mkdir(parents=True)
    write_json(store_keys, trusted_keys_doc([(KEY_ID, FAKE_PUBLIC, None)]))
    result = plan(
        tmp_path,
        root=root,
        bundle_path=str(bundle),
        audience_ids=["team:test"],
        tools_fixture_path=str(fixture_path(tmp_path)),
    )
    assert result["inputs"]["trusted_keys_source"] == "managed"
    assert result["verification"]["ok"] is True


def test_plan_flag_combination_blockers(tmp_path: Path) -> None:
    keys = write_json(tmp_path / "keys.json", trusted_keys_doc([(KEY_ID, FAKE_PUBLIC, None)]))
    result = plan(tmp_path, trusted_keys_path=str(keys))
    assert result["profile_state"]["mode"] == "blocked"
    assert any("--trusted-keys requires --bundle" in blocker for blocker in result["blockers"])
    result = plan(tmp_path, audience_ids=["team:test"])
    assert any("--audience-id requires --bundle" in blocker for blocker in result["blockers"])
    result = plan(tmp_path, profile_name="dev")
    assert any("--profile requires" in blocker for blocker in result["blockers"])


def test_plan_require_signed_policy_refusal(tmp_path: Path) -> None:
    result = plan(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path)),
        require_signed=True,
        tools_fixture_path=str(fixture_path(tmp_path)),
    )
    assert result["profile_state"]["source"] == "policy_refusal"
    assert result["profile_state"]["refusal_code"] == BUNDLE_SIGNATURE_INVALID
    assert result["verification"]["failed_step"] == "policy"
    # The gateway records this refusal with source raw_file.
    assert result["audit_impact"]["profile_loaded_row"]["profile_source"] == "raw_file"


# ---------------------------------------------------------------------------
# Doctor findings: every class, with severities and exit codes.


def test_doctor_clean_rollout_exits_zero(tmp_path: Path) -> None:
    bundle, keys, _ = bundle_env(tmp_path)
    report = doctor(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
        tools_fixture_path=str(
            write_json(tmp_path / "tools2.json", [{"upstream": "fake", "name": "echo"}])
        ),
    )
    assert report["status"] == "ok"
    assert report["exit_code"] == 0
    assert finding_ids(report, "problem") == []


def test_doctor_missing_trust_store(tmp_path: Path) -> None:
    bundle, _, _ = bundle_env(tmp_path)
    report = doctor(tmp_path, bundle_path=str(bundle), audience_ids=["team:test"])
    assert "trust_store_missing" in finding_ids(report, "problem")
    assert "rollout_fail_closed" in finding_ids(report, "problem")
    assert report["exit_code"] == 1


def test_doctor_missing_explicit_trusted_keys_file(tmp_path: Path) -> None:
    bundle, _, _ = bundle_env(tmp_path)
    report = doctor(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(tmp_path / "nope.json"),
        audience_ids=["team:test"],
    )
    assert "trust_store_missing" in finding_ids(report, "problem")


def test_doctor_corrupt_trust_store(tmp_path: Path) -> None:
    bundle, keys, _ = bundle_env(tmp_path)
    keys.write_text("{not json", encoding="utf-8")
    report = doctor(
        tmp_path, bundle_path=str(bundle), trusted_keys_path=str(keys), audience_ids=["team:test"]
    )
    assert "trust_store_corrupt" in finding_ids(report, "problem")
    assert report["exit_code"] == 1


def test_doctor_expired_signing_key_is_a_problem(tmp_path: Path) -> None:
    bundle, keys, _ = bundle_env(tmp_path, not_after="2026-06-15T00:00:00Z")  # before NOW
    report = doctor(
        tmp_path, bundle_path=str(bundle), trusted_keys_path=str(keys), audience_ids=["team:test"]
    )
    problems = finding_ids(report, "problem")
    assert "key_expired" in problems
    assert "rollout_fail_closed" in problems
    assert report["exit_code"] == 1


def test_doctor_expired_bystander_key_is_a_warning(tmp_path: Path) -> None:
    bundle, _, _ = bundle_env(tmp_path)
    keys = write_json(
        tmp_path / "trusted-keys.json",
        trusted_keys_doc(
            [(KEY_ID, FAKE_PUBLIC, None), ("old-key", b"\x09" * 32, "2026-01-01T00:00:00Z")]
        ),
    )
    report = doctor(
        tmp_path, bundle_path=str(bundle), trusted_keys_path=str(keys), audience_ids=["team:test"]
    )
    assert "key_expired" in finding_ids(report, "warning")
    assert "key_expired" not in finding_ids(report, "problem")


def test_doctor_revoked_signing_key(tmp_path: Path) -> None:
    crl = write_json(
        tmp_path / "crl.json",
        {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": [KEY_ID]},
    )

    def declare_crl(document: dict) -> None:
        document["revocation"] = {"crl_path": str(crl)}

    bundle, keys, _ = bundle_env(tmp_path, mutate=declare_crl)
    report = doctor(
        tmp_path, bundle_path=str(bundle), trusted_keys_path=str(keys), audience_ids=["team:test"]
    )
    problems = finding_ids(report, "problem")
    assert "key_revoked" in problems
    assert "rollout_fail_closed" in problems
    fail_closed = [
        item for item in report["findings"] if item["finding"] == "rollout_fail_closed"
    ]
    assert f"({BUNDLE_REVOKED})" in fail_closed[0]["detail"]


def test_doctor_unknown_key_id(tmp_path: Path) -> None:
    bundle, _, _ = bundle_env(tmp_path)
    keys = write_json(
        tmp_path / "trusted-keys.json",
        trusted_keys_doc([("some-other-key", b"\x0a" * 32, None)]),
    )
    report = doctor(
        tmp_path, bundle_path=str(bundle), trusted_keys_path=str(keys), audience_ids=["team:test"]
    )
    assert "unknown_key_id" in finding_ids(report, "problem")


def test_doctor_wrong_audience(tmp_path: Path) -> None:
    bundle, keys, _ = bundle_env(tmp_path)
    report = doctor(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:somebody-else"],
    )
    assert "audience_mismatch" in finding_ids(report, "problem")


def test_doctor_issuer_scope_violation(tmp_path: Path) -> None:
    def widen(document: dict) -> None:
        document["profiles"]["dev"]["visible"] = ["fake.*", "other.*", "payments.charge"]

    bundle, keys, _ = bundle_env(tmp_path, mutate=widen)
    report = doctor(
        tmp_path, bundle_path=str(bundle), trusted_keys_path=str(keys), audience_ids=["team:test"]
    )
    scoped = [item for item in report["findings"] if item["finding"] == "issuer_scope_violation"]
    assert scoped and scoped[0]["severity"] == "problem"
    assert "payments.charge" in scoped[0]["detail"]


def test_doctor_bundle_outside_validity_window(tmp_path: Path) -> None:
    bundle, keys, _ = bundle_env(tmp_path)
    report = doctor(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
        now=_parse_timestamp("2027-01-01T00:00:00Z"),
    )
    assert "bundle_expired" in finding_ids(report, "problem")


def test_doctor_profile_hiding_all_tools(tmp_path: Path) -> None:
    document = {
        "schema_version": 1,
        "default_profile": "ghosts",
        "profiles": {"ghosts": {"visible": ["ghost.*"], "callable": ["ghost.*"]}},
    }
    report = doctor(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path, document)),
        tools_fixture_path=str(fixture_path(tmp_path)),
    )
    assert "profile_hides_all_tools" in finding_ids(report, "problem")
    assert report["exit_code"] == 1


def test_doctor_callable_not_covered_is_inert_rule_warning(tmp_path: Path) -> None:
    report = doctor(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path)),
        tools_fixture_path=str(fixture_path(tmp_path)),
        profile_name="ci",
    )
    # Under 'ci' nothing of 'other' can ever be visible, so dev's broad
    # callable rule for it is inert; a parent's NARROWED rule is not flagged.
    warnings = [item for item in report["findings"] if item["finding"] == "callable_not_covered"]
    assert warnings, report["findings"]
    assert all(item["severity"] == "warning" for item in warnings)
    assert any("other.*" in item["detail"] for item in warnings)
    assert report["exit_code"] == 0  # warnings alone stay clean


def test_doctor_shadowed_tool_names(tmp_path: Path) -> None:
    report = doctor(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path)),
        tools_fixture_path=str(fixture_path(tmp_path)),
        profile_name="dev",
    )
    shadowed = [item for item in report["findings"] if item["finding"] == "shadowed_tool_name"]
    assert shadowed and shadowed[0]["severity"] == "warning"
    assert "'echo'" in shadowed[0]["detail"]


def test_doctor_profile_chain_too_deep(tmp_path: Path) -> None:
    profiles = {"p0": {"visible": ["fake.*"], "callable": ["fake.*"]}}
    for index in range(1, 10):
        profiles[f"p{index}"] = {"extends": f"p{index - 1}"}
    document = {"schema_version": 1, "default_profile": "p9", "profiles": profiles}
    report = doctor(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path, document)),
        tools_fixture_path=str(fixture_path(tmp_path)),
    )
    problems = finding_ids(report, "problem")
    assert "profile_chain_too_deep" in problems
    assert "rollout_fail_closed" in problems  # the strict loader refuses -32014


def test_doctor_unsigned_under_signed_policy(tmp_path: Path) -> None:
    report = doctor(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path)),
        require_signed=True,
        tools_fixture_path=str(fixture_path(tmp_path)),
    )
    assert "unsigned_under_signed_policy" in finding_ids(report, "problem")
    assert report["exit_code"] == 1


def test_doctor_unsigned_local_narrowing_under_policy_is_a_warning(tmp_path: Path) -> None:
    bundle, keys, _ = bundle_env(tmp_path)
    local = write_json(
        tmp_path / "local.json",
        {
            "schema_version": 1,
            "profiles": {"dev": {"visible": ["fake.echo"], "callable": ["fake.echo"]}},
        },
    )
    report = doctor(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        profiles_path=str(local),
        audience_ids=["team:test"],
        require_signed=True,
        tools_fixture_path=str(
            write_json(tmp_path / "tools2.json", [{"upstream": "fake", "name": "echo"}])
        ),
    )
    assert "unsigned_local_narrowing" in finding_ids(report, "warning")
    assert "unsigned_under_signed_policy" not in finding_ids(report)
    assert report["exit_code"] == 0


def test_doctor_no_tools_warning(tmp_path: Path) -> None:
    report = doctor(tmp_path, profiles_path=str(profiles_path(tmp_path)))
    assert "no_tools" in finding_ids(report, "warning")


def test_doctor_managed_store_passthrough(tmp_path: Path) -> None:
    bundle, _, _ = bundle_env(tmp_path)
    root = tmp_path / "library"
    store_dir = root / ".unlimited-skills-trust"
    store_dir.mkdir(parents=True)
    write_json(store_dir / "trusted-keys.json", trusted_keys_doc([(KEY_ID, FAKE_PUBLIC, None)]))
    (store_dir / "crl.json").write_text("{broken", encoding="utf-8")
    report = doctor(
        tmp_path, root=root, bundle_path=str(bundle), audience_ids=["team:test"]
    )
    # The E15 store doctor's CRL problem passes through as a finding.
    passthrough = [item for item in report["findings"] if item["finding"] == "trust_store_doctor"]
    assert any(item["severity"] == "problem" for item in passthrough)


# ---------------------------------------------------------------------------
# Schema artifacts.


def test_plan_schema_is_draft_2020_12_and_strict(plan_schema: dict) -> None:
    assert plan_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert plan_schema["additionalProperties"] is False
    assert plan_schema["properties"]["schema_version"] == {"const": 1}
    for key in (
        "inputs",
        "profile_state",
        "tools",
        "upstreams",
        "inheritance",
        "verification",
        "audit_impact",
        "warnings",
        "blockers",
    ):
        assert key in plan_schema["required"], key


def test_shipped_example_validates_against_schema(plan_schema: dict) -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert validate(example, plan_schema) == []
    assert example["profile_state"]["mode"] == "enforced"
    assert example["tools"]["refused_by_policy"] == 1


def test_unknown_plan_key_rejected_by_schema(plan_schema: dict) -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    bad = copy.deepcopy(example)
    bad["applied"] = True  # a simulator never applies anything
    errors = validate(bad, plan_schema)
    assert any("additional property 'applied'" in error for error in errors)


def test_every_plan_variant_validates(tmp_path: Path, plan_schema: dict) -> None:
    bundle, keys, _ = bundle_env(tmp_path)
    variants = [
        plan(tmp_path, tools_fixture_path=str(fixture_path(tmp_path))),
        plan(
            tmp_path,
            bundle_path=str(bundle),
            trusted_keys_path=str(keys),
            audience_ids=["team:test"],
            tools_fixture_path=str(fixture_path(tmp_path)),
        ),
        plan(tmp_path, bundle_path=str(bundle), audience_ids=["team:nope"]),
        plan(tmp_path, require_signed=True),
        plan(tmp_path, trusted_keys_path=str(keys)),  # blocked
    ]
    for variant in variants:
        assert validate(variant, plan_schema) == [], variant["profile_state"]


# ---------------------------------------------------------------------------
# Read-only / no-spawn proof.


def test_planning_never_spawns_and_never_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):  # pragma: no cover - would mean a regression
        raise AssertionError("the rollout simulator must never create a subprocess")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    bundle, keys, _ = bundle_env(tmp_path)
    config = config_path(tmp_path)
    root = tmp_path / "library"
    root.mkdir()
    before = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*") if path.is_file()}
    plan(
        tmp_path,
        root=root,
        config_path=str(config),
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
    )
    doctor(
        tmp_path,
        root=root,
        config_path=str(config),
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
    )
    after = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before  # nothing created, nothing modified
    assert not (root / ".learning").exists()  # no audit rows


def test_fixture_reader_validates_shape(tmp_path: Path) -> None:
    tools, errors = read_tools_fixture(write_json(tmp_path / "f.json", [{"upstream": "a"}]))
    assert tools == []
    assert errors and "needs string 'upstream' and 'name'" in errors[0]
    tools, errors = read_tools_fixture(write_json(tmp_path / "g.json", {"not": "a list"}))
    assert errors
    missing_tools, missing_errors = read_tools_fixture(tmp_path / "absent.json")
    assert missing_tools == [] and missing_errors


# ---------------------------------------------------------------------------
# Dispatch parity with the gateway and CLI wiring.


def test_dispatch_parity_with_gateway_resolution(tmp_path: Path) -> None:
    """The simulator's profile-state dispatch must agree with the gateway's
    _resolve_gateway_profile_state on the refusal code for the same inputs."""
    bundle, keys, _ = bundle_env(tmp_path)
    args = Namespace(
        root=str(tmp_path / "library"),
        profiles="",
        profile="",
        profile_bundle=str(bundle),
        trusted_keys="",
        audience_id=["team:test"],
        require_signed_profiles=False,
    )
    gateway_state, _ = _resolve_gateway_profile_state(args)
    simulated = plan(tmp_path, bundle_path=str(bundle), audience_ids=["team:test"])
    # No trusted keys anywhere: both fail closed with bundle_key_missing.
    assert gateway_state.code == BUNDLE_KEY_MISSING
    assert simulated["profile_state"]["refusal_code"] == BUNDLE_KEY_MISSING


def run_cli(root: Path, *argv: str) -> int:
    return main(["--root", str(root), "mcp", "profiles", *argv])


def test_cli_rollout_plan_json_validates(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch,
    plan_schema: dict,
) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_AUDIENCE", raising=False)
    root = tmp_path / "library"
    root.mkdir()
    code = run_cli(
        root,
        "rollout-plan",
        "--profiles",
        str(profiles_path(tmp_path)),
        "--tools-fixture",
        str(fixture_path(tmp_path)),
        "--profile",
        "reviewer",
        "--json",
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert validate(payload, plan_schema) == []
    assert payload["profile_state"]["profile"] == "reviewer"
    assert payload["tools"]["visible"] == 2


def test_cli_rollout_plan_text_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    root = tmp_path / "library"
    root.mkdir()
    code = run_cli(
        root,
        "rollout-plan",
        "--profiles",
        str(profiles_path(tmp_path)),
        "--tools-fixture",
        str(fixture_path(tmp_path)),
        "--profile",
        "ci",
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "would NEVER spawn" in out
    assert "blockers: none" in out


def test_cli_doctor_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_AUDIENCE", raising=False)
    root = tmp_path / "library"
    root.mkdir()
    clean = run_cli(
        root,
        "doctor",
        "--profiles",
        str(profiles_path(tmp_path)),
        "--tools-fixture",
        str(fixture_path(tmp_path)),
        "--profile",
        "dev",
        "--json",
    )
    assert clean == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    broken = write_json(tmp_path / "broken.json", {"schema_version": 1, "profiles": []})
    failing = run_cli(root, "doctor", "--profiles", str(broken), "--json")
    assert failing == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "problems"
    assert "rollout_fail_closed" in [item["finding"] for item in report["findings"]]


def test_formatters_render_findings_and_plan(tmp_path: Path) -> None:
    report = doctor(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path)),
        tools_fixture_path=str(fixture_path(tmp_path)),
        profile_name="ci",
    )
    text = format_rollout_doctor(report)
    assert "MCP profile rollout doctor" in text
    assert "[warning]" in text
    result = plan(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path)),
        tools_fixture_path=str(fixture_path(tmp_path)),
        profile_name="reviewer",
    )
    text = format_rollout_plan(result)
    assert "inheritance: dev -> reviewer" in text
    assert "refused by policy" in text
