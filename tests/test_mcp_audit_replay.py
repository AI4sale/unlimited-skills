"""E17: MCP audit replay and policy impact simulator.

Proves the contract of docs/mcp-audit-replay.md against
``unlimited_skills.mcp.audit_replay`` and the ``unlimited-skills mcp
profiles replay-audit`` CLI:

- event classification over a fixture audit log written by the REAL
  ``AuditLog`` writer (rotated generations, malformed lines counted and
  skipped, ``profile_loaded`` lifecycle rows, ``skills_*``/other rows,
  minimal-level rows without a tool identity counted, never guessed);
- impact computation: every transition class (newly_denied / newly_allowed /
  unchanged_allowed / unchanged_denied) with the exact would-be refusal
  codes, against raw profile files, verified signed bundles (the REAL E14
  verification via the test-only HMAC backend), fail-closed states, and the
  config trust gates;
- breakdowns by tool / upstream / profile / refusal code / time bucket /
  call type;
- every detection finding class with its severity;
- the documented recommendation thresholds (blocked > 20% newly denied);
- determinism (same inputs -> same document; ``generated_at`` is the only
  wall-clock field);
- ``--json`` validates against ``schemas/mcp-audit-replay-report.schema.json``
  (the repo's self-contained validator pattern, extended with $ref and
  additionalProperties-as-schema) and the shipped example validates too;
- leak-grep: every string in the report is re-scanned with the audit
  writer's own ``looks_secret``/path heuristics (documented non-sensitive
  hashes exempt) and known sensitive markers never appear;
- NO-SPAWN / read-only proof: replaying never creates a subprocess and
  never writes a single file;
- CLI wiring (main(...) dispatch, --json shape, exit codes 0/1).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import re
import subprocess
from pathlib import Path

import pytest

from unlimited_skills.cli import main
from unlimited_skills.mcp.audit import AuditLog, looks_secret
from unlimited_skills.mcp.audit import _PATH_PATTERN as PATH_PATTERN
from unlimited_skills.mcp.audit_replay import (
    BLOCK_BREAKAGE_RATIO,
    POLICY_REFUSAL_CODES,
    call_type_of,
    evaluate_call,
    format_replay_report,
    historical_outcome_of,
    replay_audit,
    time_bucket_of,
    tool_identity_of,
    would_be_name,
)
from unlimited_skills.mcp.bundles import (
    BUNDLE_AUDIENCE_MISMATCH,
    BUNDLE_KEY_MISSING,
    BUNDLE_REVOKED,
    SignatureBackend,
    canonical_bundle_bytes,
    _parse_timestamp,
)
from unlimited_skills.mcp.profiles import (
    PROFILE_INVALID,
    TOOL_NOT_CALLABLE,
    TOOL_NOT_VISIBLE,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "mcp-audit-replay-report.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "mcp" / "audit-replay-report.example.json"

KEY_ID = "test-team-profiles-2026"
NOW = _parse_timestamp("2026-07-01T00:00:00Z")  # inside the base validity window


# ---------------------------------------------------------------------------
# The repo's minimal self-contained JSON Schema validator (same stance as
# tests/test_mcp_profile_rollout.py: no jsonschema dependency), extended with
# "$ref": "#/$defs/..." resolution and additionalProperties-as-schema.

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


def validate(value: object, schema: dict, path: str = "$", root: dict | None = None) -> list[str]:
    if root is None:
        root = schema
    if "$ref" in schema:
        target: object = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            target = target[part]  # type: ignore[index]
        return validate(value, target, path, root)  # type: ignore[arg-type]
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
        additional = schema.get("additionalProperties")
        for key, item in value.items():
            if key in properties:
                errors.extend(validate(item, properties[key], f"{path}.{key}", root))
            elif additional is False:
                errors.append(f"{path}: additional property {key!r} not allowed")
            elif isinstance(additional, dict):
                errors.extend(validate(item, additional, f"{path}.{key}", root))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(validate(item, schema["items"], f"{path}[{index}]", root))
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    return errors


@pytest.fixture(scope="module")
def replay_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Builders: the test-only HMAC backend (same pattern as
# tests/test_mcp_bundle_verification.py / test_mcp_profile_rollout.py --
# exercises the REAL verification order without the cryptography package),
# fixture audit logs written via the REAL AuditLog writer, and policies.


class FakeHmacBackend(SignatureBackend):
    name = "test-only-hmac"

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(hmac.new(public_key, message, "sha256").digest(), signature)


FAKE_PUBLIC = b"\x07" * 32


def sign_fake(document: dict, key_id: str = KEY_ID) -> dict:
    signature = hmac.new(FAKE_PUBLIC, canonical_bundle_bytes(document), "sha256").digest()
    document["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id,
        "value": base64.b64encode(signature).decode("ascii"),
    }
    return document


def base_bundle() -> dict:
    return {
        "bundle_version": 1,
        "issuer": {"key_id": KEY_ID, "display": "Test platform team"},
        "audience": ["team:test"],
        "issued_at": "2026-06-01T00:00:00Z",
        "expires_at": "2026-09-01T00:00:00Z",
        "allowed_upstream_namespaces": ["fake.*", "other.*"],
        "default_profile": "reviewer",
        "profiles": {
            "reviewer": {
                "visible": ["fake.echo", "fake.add"],
                "callable": ["fake.echo"],
            }
        },
    }


def write_json(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def trusted_keys_doc() -> dict:
    return {
        "schema_version": 1,
        "keys": [
            {
                "key_id": KEY_ID,
                "algorithm": "ed25519",
                "public_key": base64.b64encode(FAKE_PUBLIC).decode("ascii"),
            }
        ],
    }


def bundle_env(tmp_path: Path, mutate=None):
    document = base_bundle()
    if mutate is not None:
        mutate(document)
    sign_fake(document)
    bundle = write_json(tmp_path / "bundle.json", document)
    keys = write_json(tmp_path / "trusted-keys.json", trusted_keys_doc())
    return bundle, keys, document


PROFILES_DOC = {
    "schema_version": 1,
    "default_profile": "reviewer",
    "profiles": {
        "reviewer": {
            "visible": ["fake.echo", "fake.add"],
            "callable": ["fake.echo"],
        }
    },
}


def profiles_path(tmp_path: Path, document: dict | None = None) -> Path:
    return write_json(tmp_path / "profiles.json", document or PROFILES_DOC)


def write_history(tmp_path: Path) -> Path:
    """One fixture audit log via the REAL AuditLog writer.

    Historical world: profile 'dev' allowed everything. Replayed against
    PROFILES_DOC ('reviewer': fake.echo callable, fake.add view-only,
    other.* hidden) this produces every transition class:

    - fake.echo ok calls       -> unchanged_allowed
    - fake.add ok call         -> newly_denied (-32012 on tools_call)
    - other.echo ok call       -> newly_denied (-32011)
    - fake.echo old -32011 row -> newly_allowed
    - ghost.run old -32011 row -> unchanged_denied
    """
    log_path = tmp_path / "mcp-audit.jsonl"
    log = AuditLog(log_path)
    log.record(
        tool="profile_loaded",
        ok=True,
        profile="dev",
        extra={"profile_sha256": "e3" * 32, "visible_rules": 2, "callable_rules": 2},
    )
    log.record(tool="tools_search", ok=True, duration_ms=3.0, profile="dev", arguments={"query": "echo"})
    log.record(
        tool="tools_schema",
        upstream="fake",
        ok=True,
        profile="dev",
        arguments={"tool": "fake.add"},
    )
    for _ in range(2):
        log.record(
            tool="tools_call",
            upstream="fake",
            ok=True,
            duration_ms=11.0,
            profile="dev",
            arguments={"tool": "fake.echo", "arguments": {"message": "hello"}},
        )
    log.record(
        tool="tools_call",
        upstream="fake",
        ok=True,
        profile="dev",
        arguments={"tool": "fake.add", "arguments": {}},
    )
    log.record(
        tool="tools_call",
        upstream="other",
        ok=True,
        profile="dev",
        arguments={"tool": "other.echo", "arguments": {}},
    )
    log.record(
        tool="tools_call",
        upstream="fake",
        ok=False,
        profile="dev",
        arguments={"tool": "fake.echo"},
        error="Refused (tool_not_visible): tool not in the visible set.",
    )
    log.record(
        tool="tools_call",
        upstream="ghost",
        ok=False,
        profile="dev",
        arguments={"tool": "ghost.run"},
        error="Refused (tool_not_visible): tool not in the visible set.",
    )
    # A runtime refusal: the call PASSED policy historically.
    log.record(
        tool="tools_call",
        upstream="fake",
        ok=False,
        profile="dev",
        arguments={"tool": "fake.echo"},
        error="upstream 'fake' timed out on tools/call after 30s",
    )
    # Minimal audit level: no args shape -> no tool identity, never guessed.
    log.record(tool="tools_call", upstream="fake", ok=True, profile="dev")
    log.record(tool="skills_search", ok=True)
    log.record(tool="warm_start", ok=True)  # an 'other' lifecycle-ish row
    return log_path


def replay(tmp_path: Path, log_path: Path | None = None, **kwargs) -> dict:
    kwargs.setdefault("root", tmp_path / "library")
    kwargs.setdefault("env_name", "")
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("backend", FakeHmacBackend())
    return replay_audit(log_path or write_history(tmp_path), **kwargs)


def finding_ids(report: dict, severity: str | None = None) -> list[str]:
    return [
        item["finding"]
        for item in report["findings"]
        if severity is None or item["severity"] == severity
    ]


# ---------------------------------------------------------------------------
# Event classification.


def test_event_classification_and_counts(tmp_path: Path, replay_schema: dict) -> None:
    log_path = write_history(tmp_path)
    # A malformed JSONL line is counted and skipped, never a crash.
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("{this is not json\n")
        handle.write('"not an object"\n')
    report = replay(tmp_path, log_path=log_path)
    assert validate(report, replay_schema) == []
    assert report["log"]["malformed_lines"] == 2
    events = report["events"]
    assert events["by_call_type"] == {
        "tools_search": 1,
        "tools_schema": 1,
        "tools_call": 8,
        "skills": 1,
        "other": 1,
    }
    assert events["profile_loaded_events"] == 1
    assert events["missing_tool_identity"] == 1  # counted, never guessed
    assert events["replayed"] == 8  # schema+call rows WITH a tool identity
    assert events["calls_total"] == 12
    assert "missing_tool_identity" in finding_ids(report, "warning")
    assert "malformed_rows" in finding_ids(report, "warning")


def test_row_classifiers() -> None:
    assert call_type_of({"tool": "tools_call"}) == "tools_call"
    assert call_type_of({"tool": "skills_view"}) == "skills"
    assert call_type_of({"tool": "warm_start"}) == "other"
    assert historical_outcome_of({"ok": True}) == "ok"
    assert (
        historical_outcome_of({"ok": False, "error": "Refused (tool_not_callable): x"})
        == "profile_denied"
    )
    assert (
        historical_outcome_of({"ok": False, "error": "upstream 'a' timed out on call"})
        == "upstream_refusal"
    )
    assert tool_identity_of({"args": {"tool": "fake.echo"}}) == ("fake", "echo")
    assert tool_identity_of({"args": {"tool": "noseparator"}}) is None
    assert tool_identity_of({"upstream": "fake"}) is None  # never guessed
    assert time_bucket_of({"ts": _parse_timestamp("2026-07-01T13:45:59Z")}) == "2026-07-01T13:00Z"
    assert time_bucket_of({"ts": "soon"}) == "unknown"
    assert POLICY_REFUSAL_CODES == frozenset(range(-32019, -32010))


# ---------------------------------------------------------------------------
# Impact computation: every transition class, exact would-be codes.


def test_impact_all_four_transition_classes(tmp_path: Path, replay_schema: dict) -> None:
    report = replay(tmp_path, profiles_path=str(profiles_path(tmp_path)))
    assert validate(report, replay_schema) == []
    impact = report["impact"]
    assert impact["replayed"] == 8
    # fake.echo x2 ok calls + fake.add tools_schema (view-only is still
    # visible) + the timed-out fake.echo call (policy-allowed) would pass.
    assert impact["unchanged_allowed"] == 4
    # fake.add tools_call (-32012) + other.echo tools_call (-32011).
    assert impact["newly_denied"] == 2
    # The old -32011 refusal of fake.echo would now pass.
    assert impact["newly_allowed"] == 1
    # ghost.run stays hidden.
    assert impact["unchanged_denied"] == 1
    assert impact["would_allow"] == 5
    assert impact["would_deny"] == 3
    denied = {entry["tool"]: entry for entry in impact["newly_denied_tools"]}
    assert denied["fake.add"]["would_be_code"] == TOOL_NOT_CALLABLE
    assert denied["fake.add"]["would_be_name"] == "tool_not_callable"
    assert denied["other.echo"]["would_be_code"] == TOOL_NOT_VISIBLE
    assert denied["other.echo"]["would_be_name"] == "tool_not_visible"
    assert impact["newly_allowed_tools"] == [{"tool": "fake.echo", "calls": 1}]


def test_view_only_tool_schema_passes_but_call_refused(tmp_path: Path) -> None:
    report = replay(tmp_path, profiles_path=str(profiles_path(tmp_path)))
    by_tool = report["breakdowns"]["by_tool"]["fake.add"]
    # One tools_schema (visibility only: allowed) + one tools_call (refused).
    assert by_tool == {
        "replayed": 2,
        "would_allow": 1,
        "would_deny": 1,
        "newly_denied": 1,
        "newly_allowed": 0,
    }


def test_open_mode_everything_passes_and_is_safe(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    log = AuditLog(log_path)
    for _ in range(3):
        log.record(
            tool="tools_call",
            upstream="fake",
            ok=True,
            arguments={"tool": "fake.echo", "arguments": {}},
        )
    report = replay(tmp_path, log_path=log_path)
    assert report["policy"]["mode"] == "open"
    assert report["impact"]["would_deny"] == 0
    assert report["findings"] == []
    assert report["recommendation"]["status"] == "safe"


def test_fail_closed_policy_denies_every_replayed_call(tmp_path: Path) -> None:
    broken = write_json(tmp_path / "broken.json", {"schema_version": 1, "profiles": "nope"})
    report = replay(tmp_path, profiles_path=str(broken))
    assert report["policy"]["mode"] == "fail_closed"
    assert report["policy"]["refusal_code"] == PROFILE_INVALID
    assert report["impact"]["would_allow"] == 0
    assert report["impact"]["would_deny"] == report["impact"]["replayed"] == 8
    denied_names = {entry["would_be_name"] for entry in report["impact"]["newly_denied_tools"]}
    assert denied_names == {"profile_invalid"}
    assert "policy_fail_closed" in finding_ids(report, "problem")
    assert report["recommendation"]["status"] == "blocked"


def test_config_trust_gates(tmp_path: Path) -> None:
    config = write_json(
        tmp_path / "gateway.json",
        {
            "schema_version": 1,
            "upstreams": [
                {"name": "fake", "command": "/abs/fake-upstream"},
                {"name": "other", "command": "/abs/other-upstream", "enabled": False},
                {
                    "name": "ghost",
                    "command": "/abs/ghost-upstream",
                    "trust_level": "future-remote-placeholder",
                },
            ],
        },
    )
    log_path = write_history(tmp_path)
    report = replay(tmp_path, log_path=log_path, config_path=str(config))
    by_code = report["breakdowns"]["by_refusal_code"]
    assert by_code["upstream_disabled"]["replayed"] == 1  # other.echo
    assert by_code["trust_level_violation"]["replayed"] == 1  # ghost.run
    assert "allowed" in by_code  # fake.* passes (open profile mode)
    # An upstream the config does not know at all:
    config2 = write_json(
        tmp_path / "gateway2.json",
        {"schema_version": 1, "upstreams": [{"name": "fake", "command": "/abs/fake-upstream"}]},
    )
    report2 = replay(tmp_path, log_path=log_path, config_path=str(config2))
    assert report2["breakdowns"]["by_refusal_code"]["upstream_not_configured"]["replayed"] == 2


def test_evaluate_call_order_profile_before_trust_gate(tmp_path: Path) -> None:
    # A hidden tool on a disabled upstream is refused -32011, never -32005:
    # the gateway checks visibility before any upstream lookup.
    config = write_json(
        tmp_path / "gateway.json",
        {
            "schema_version": 1,
            "upstreams": [{"name": "other", "command": "/abs/x", "enabled": False}],
        },
    )
    report = replay(
        tmp_path,
        profiles_path=str(profiles_path(tmp_path)),
        config_path=str(config),
    )
    other = report["breakdowns"]["by_tool"]["other.echo"]
    assert other["would_deny"] == 1
    denied = {entry["tool"]: entry for entry in report["impact"]["newly_denied_tools"]}
    assert denied["other.echo"]["would_be_code"] == TOOL_NOT_VISIBLE


# ---------------------------------------------------------------------------
# Signed bundles: the REAL E14 verification in dry-run.


def test_verified_bundle_replay(tmp_path: Path, replay_schema: dict) -> None:
    bundle, keys, document = bundle_env(tmp_path)
    report = replay(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
    )
    assert validate(report, replay_schema) == []
    verification = report["verification"]
    assert verification["attempted"] is True and verification["ok"] is True
    assert verification["bundle_sha256"] == hashlib.sha256(
        (tmp_path / "bundle.json").read_bytes()
    ).hexdigest()
    assert verification["issuer_key_id"] == KEY_ID
    assert report["policy"]["source"] == "signed_bundle"
    # Same rules as PROFILES_DOC -> same impact math.
    assert report["impact"]["newly_denied"] == 2
    # No key material or signature values anywhere in the report.
    dumped = json.dumps(report)
    assert document["signature"]["value"] not in dumped
    assert base64.b64encode(FAKE_PUBLIC).decode("ascii") not in dumped


def test_bundle_verification_failure_finding(tmp_path: Path) -> None:
    bundle, _, _ = bundle_env(tmp_path)
    report = replay(tmp_path, bundle_path=str(bundle), audience_ids=["team:test"])
    assert report["verification"]["refusal_code"] == BUNDLE_KEY_MISSING
    assert report["verification"]["failed_step"] == "key_lookup"
    assert "bundle_verification_failure" in finding_ids(report, "problem")
    assert "policy_fail_closed" in finding_ids(report, "problem")
    assert report["recommendation"]["status"] == "blocked"


def test_revoked_issuer_finding(tmp_path: Path) -> None:
    crl = write_json(
        tmp_path / "crl.json",
        {"schema_version": 1, "revoked_bundles": [], "revoked_key_ids": [KEY_ID]},
    )

    def declare_crl(document: dict) -> None:
        document["revocation"] = {"crl_path": str(crl)}

    bundle, keys, _ = bundle_env(tmp_path, mutate=declare_crl)
    report = replay(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
    )
    assert report["verification"]["refusal_code"] == BUNDLE_REVOKED
    assert report["verification"]["failed_step"] == "revocation"
    assert "revoked_issuer" in finding_ids(report, "problem")
    assert report["recommendation"]["status"] == "blocked"


def test_namespace_mismatch_finding(tmp_path: Path) -> None:
    def widen(document: dict) -> None:
        document["profiles"]["reviewer"]["visible"] = ["fake.echo", "payments.charge"]

    bundle, keys, _ = bundle_env(tmp_path, mutate=widen)
    report = replay(
        tmp_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
    )
    assert report["verification"]["refusal_code"] == BUNDLE_AUDIENCE_MISMATCH
    assert report["verification"]["failed_step"] == "namespace_ceiling"
    assert "namespace_mismatch" in finding_ids(report, "problem")


def test_trust_store_dir_flag(tmp_path: Path) -> None:
    bundle, _, _ = bundle_env(tmp_path)
    store = tmp_path / "store"
    store.mkdir()
    write_json(store / "trusted-keys.json", trusted_keys_doc())
    report = replay(
        tmp_path,
        bundle_path=str(bundle),
        trust_store_dir=str(store),
        audience_ids=["team:test"],
    )
    assert report["inputs"]["trusted_keys_source"] == "store_dir"
    assert report["verification"]["ok"] is True


def test_managed_store_default(tmp_path: Path) -> None:
    bundle, _, _ = bundle_env(tmp_path)
    root = tmp_path / "library"
    store_keys = root / ".unlimited-skills-trust" / "trusted-keys.json"
    store_keys.parent.mkdir(parents=True)
    write_json(store_keys, trusted_keys_doc())
    report = replay(tmp_path, root=root, bundle_path=str(bundle), audience_ids=["team:test"])
    assert report["inputs"]["trusted_keys_source"] == "managed"
    assert report["verification"]["ok"] is True


# ---------------------------------------------------------------------------
# Detections over historical usage.


def test_policy_hides_used_tool_and_view_only_findings(tmp_path: Path) -> None:
    report = replay(tmp_path, profiles_path=str(profiles_path(tmp_path)))
    problems = finding_ids(report, "problem")
    assert "policy_hides_used_tool" in problems  # other.echo was actively used
    assert "tool_view_only_but_called" in problems  # fake.add was called ok
    details = " | ".join(item["detail"] for item in report["findings"])
    assert "other.echo" in details
    assert "fake.add" in details


def test_input_error_flags_block(tmp_path: Path) -> None:
    report = replay(tmp_path, audience_ids=["team:test"])  # audience without bundle
    assert "input_error" in finding_ids(report, "problem")
    assert report["policy"]["mode"] == "blocked"
    assert report["recommendation"]["status"] == "blocked"


def test_gateway_config_invalid_blocks(tmp_path: Path) -> None:
    bad = tmp_path / "bad-config.json"
    bad.write_text("{not json", encoding="utf-8")
    report = replay(tmp_path, config_path=str(bad))
    assert "gateway_config_invalid" in finding_ids(report, "problem")
    assert report["recommendation"]["status"] == "blocked"


def test_nothing_to_replay_warning(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    AuditLog(log_path).record(tool="skills_search", ok=True)
    report = replay(tmp_path, log_path=log_path)
    assert "nothing_to_replay" in finding_ids(report, "warning")
    assert report["impact"]["replayed"] == 0


# ---------------------------------------------------------------------------
# Breakdowns.


def test_breakdowns_cover_every_axis(tmp_path: Path) -> None:
    report = replay(tmp_path, profiles_path=str(profiles_path(tmp_path)))
    breakdowns = report["breakdowns"]
    assert set(breakdowns) == {
        "by_tool",
        "by_upstream",
        "by_profile",
        "by_refusal_code",
        "by_time_bucket",
        "by_call_type",
    }
    assert set(breakdowns["by_upstream"]) == {"fake", "other", "ghost"}
    assert set(breakdowns["by_profile"]) == {"dev"}
    assert set(breakdowns["by_call_type"]) == {"tools_schema", "tools_call"}
    assert set(breakdowns["by_refusal_code"]) == {
        "allowed",
        "tool_not_visible",
        "tool_not_callable",
    }
    for bucket in breakdowns["by_time_bucket"]:
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:00Z$", bucket), bucket
    # Every axis partitions the same replayed set.
    for axis, entries in breakdowns.items():
        assert sum(entry["replayed"] for entry in entries.values()) == 8, axis


# ---------------------------------------------------------------------------
# Recommendation thresholds (documented: blocked when > 20% newly denied).


def _threshold_log(tmp_path: Path, ok_echo: int, ok_hidden: int) -> Path:
    log_path = tmp_path / "audit.jsonl"
    log = AuditLog(log_path)
    for _ in range(ok_echo):
        log.record(
            tool="tools_call", upstream="fake", ok=True,
            arguments={"tool": "fake.echo", "arguments": {}},
        )
    for _ in range(ok_hidden):
        log.record(
            tool="tools_call", upstream="other", ok=True,
            arguments={"tool": "other.echo", "arguments": {}},
        )
    return log_path


def test_breakage_at_threshold_is_warning_not_blocked(tmp_path: Path) -> None:
    # 1 of 5 newly denied = 20% = NOT over the strict > threshold.
    log_path = _threshold_log(tmp_path, ok_echo=4, ok_hidden=1)
    report = replay(tmp_path, log_path=log_path, profiles_path=str(profiles_path(tmp_path)))
    assert report["impact"]["newly_denied"] == 1
    assert report["recommendation"]["status"] == "safe_with_warnings"
    assert report["recommendation"]["thresholds"]["block_breakage_ratio"] == BLOCK_BREAKAGE_RATIO


def test_breakage_over_threshold_blocks(tmp_path: Path) -> None:
    # 2 of 5 newly denied = 40% > 20%.
    log_path = _threshold_log(tmp_path, ok_echo=3, ok_hidden=2)
    report = replay(tmp_path, log_path=log_path, profiles_path=str(profiles_path(tmp_path)))
    assert report["recommendation"]["status"] == "blocked"
    assert any("block threshold" in reason for reason in report["recommendation"]["reasons"])


# ---------------------------------------------------------------------------
# Determinism and schema artifacts.


def test_report_is_deterministic(tmp_path: Path) -> None:
    log_path = write_history(tmp_path)
    profiles = profiles_path(tmp_path)
    first = replay(tmp_path, log_path=log_path, profiles_path=str(profiles))
    second = replay(tmp_path, log_path=log_path, profiles_path=str(profiles))
    assert first == second  # same inputs, same now -> byte-identical document
    third = replay(
        tmp_path, log_path=log_path, profiles_path=str(profiles), now=NOW + 3600.0
    )
    # generated_at is the ONLY wall-clock field in the body.
    assert third["generated_at"] != first["generated_at"]
    first.pop("generated_at")
    third.pop("generated_at")
    assert first == third


def test_schema_is_draft_2020_12_and_strict(replay_schema: dict) -> None:
    assert replay_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert replay_schema["additionalProperties"] is False
    assert replay_schema["properties"]["report_type"] == {"const": "mcp-audit-replay-report"}
    assert replay_schema["properties"]["schema_version"] == {"const": 1}
    for key in (
        "inputs",
        "log",
        "policy",
        "verification",
        "events",
        "impact",
        "breakdowns",
        "findings",
        "recommendation",
    ):
        assert key in replay_schema["required"], key


def test_shipped_example_validates(replay_schema: dict) -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert validate(example, replay_schema) == []
    assert example["recommendation"]["status"] == "safe_with_warnings"
    assert example["impact"]["newly_denied"] == 1
    assert example["impact"]["newly_allowed"] == 1


def test_unknown_report_key_rejected_by_schema(replay_schema: dict) -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    bad = copy.deepcopy(example)
    bad["applied"] = True  # a replay simulator never applies anything
    errors = validate(bad, replay_schema)
    assert any("additional property 'applied'" in error for error in errors)


def test_every_report_variant_validates(tmp_path: Path, replay_schema: dict) -> None:
    bundle, keys, _ = bundle_env(tmp_path)
    log_path = write_history(tmp_path)
    variants = [
        replay(tmp_path, log_path=log_path),
        replay(tmp_path, log_path=log_path, profiles_path=str(profiles_path(tmp_path))),
        replay(
            tmp_path,
            log_path=log_path,
            bundle_path=str(bundle),
            trusted_keys_path=str(keys),
            audience_ids=["team:test"],
        ),
        replay(tmp_path, log_path=log_path, bundle_path=str(bundle), audience_ids=["team:nope"]),
        replay(tmp_path, log_path=log_path, require_signed=True),
        replay(tmp_path, log_path=log_path, trusted_keys_path=str(keys)),  # blocked input
    ]
    for variant in variants:
        assert validate(variant, replay_schema) == [], variant["policy"]


def test_missing_audit_log_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        replay(tmp_path, log_path=tmp_path / "absent.jsonl")


def test_rotated_generations_are_read(tmp_path: Path) -> None:
    log_path = write_history(tmp_path)
    rotated = log_path.with_name(log_path.name + ".1")
    rotated.write_text(log_path.read_text(encoding="utf-8"), encoding="utf-8")
    report = replay(tmp_path, log_path=log_path)
    assert report["log"]["rotated_files_read"] == 1
    assert report["events"]["replayed"] == 16  # both generations replayed


# ---------------------------------------------------------------------------
# Privacy: leak-grep with the writer's own heuristics.

# Hashes the report documents as non-sensitive by design (bundle pinning).
KNOWN_HASH_KEYS = frozenset({"bundle_sha256"})

TOKEN_MARKER = "Bearer hunter2-secret-token-AAAABBBBCCCCDDDD"
PATH_MARKER = "/home/someone/secret-skills/library"


def _iter_strings(value, key=""):
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for item_key, item in value.items():
            if str(item_key) in KNOWN_HASH_KEYS:
                continue
            yield from _iter_strings(item, str(item_key))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item, key)


def test_leak_grep_report_never_carries_secrets_or_paths(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    log = AuditLog(log_path)
    # Hostile history: secret-shaped values and local paths in arguments and
    # error strings. The REAL writer redacts/scrubs them on the way in; the
    # replay report must not resurface anything even if a row slipped through.
    log.record(
        tool="tools_call",
        upstream="fake",
        ok=True,
        profile="dev",
        arguments={
            "tool": "fake.echo",
            "arguments": {"authorization": TOKEN_MARKER, "path": PATH_MARKER},
        },
    )
    log.record(
        tool="tools_call",
        upstream="other",
        ok=False,
        profile="dev",
        arguments={"tool": "other.echo"},
        error=f"failed to spawn upstream at {PATH_MARKER} with {TOKEN_MARKER}",
    )
    bundle, keys, _ = bundle_env(tmp_path)
    report = replay(
        tmp_path,
        log_path=log_path,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
        config_path=str(
            write_json(
                tmp_path / "gateway.json",
                {"schema_version": 1, "upstreams": [{"name": "fake", "command": "/abs/fake"}]},
            )
        ),
    )
    dumped = json.dumps(report, ensure_ascii=False)
    assert TOKEN_MARKER not in dumped
    assert PATH_MARKER not in dumped
    suspects = [
        (key, text)
        for key, text in _iter_strings(report)
        if looks_secret(text) or PATH_PATTERN.search(text)
    ]
    assert suspects == []
    # Inputs are basenames only -- never local paths.
    for value in report["inputs"].values():
        if isinstance(value, str):
            assert "/" not in value and "\\" not in value
    # The text rendering is exactly as clean.
    text = format_replay_report(report)
    assert TOKEN_MARKER not in text and PATH_MARKER not in text


# ---------------------------------------------------------------------------
# Read-only / no-spawn proof.


def test_replay_never_spawns_and_never_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):  # pragma: no cover - would mean a regression
        raise AssertionError("the audit replay simulator must never create a subprocess")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    log_path = write_history(tmp_path)
    bundle, keys, _ = bundle_env(tmp_path)
    config = write_json(
        tmp_path / "gateway.json",
        {"schema_version": 1, "upstreams": [{"name": "fake", "command": "/abs/fake"}]},
    )
    root = tmp_path / "library"
    root.mkdir()
    before = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*") if path.is_file()}
    replay(
        tmp_path,
        log_path=log_path,
        root=root,
        bundle_path=str(bundle),
        trusted_keys_path=str(keys),
        audience_ids=["team:test"],
        config_path=str(config),
    )
    after = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before  # nothing created, nothing modified
    assert not (root / ".learning").exists()  # no audit rows written


# ---------------------------------------------------------------------------
# CLI wiring.


def run_cli(root: Path, *argv: str) -> int:
    return main(["--root", str(root), "mcp", "profiles", "replay-audit", *argv])


def test_cli_replay_audit_json_validates(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch,
    replay_schema: dict,
) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_AUDIENCE", raising=False)
    root = tmp_path / "library"
    root.mkdir()
    log_path = _threshold_log(tmp_path, ok_echo=4, ok_hidden=1)
    code = run_cli(
        root,
        "--audit-log", str(log_path),
        "--profiles", str(profiles_path(tmp_path)),
        "--json",
    )
    assert code == 0  # safe_with_warnings exits 0
    payload = json.loads(capsys.readouterr().out)
    assert validate(payload, replay_schema) == []
    assert payload["recommendation"]["status"] == "safe_with_warnings"
    assert payload["policy"]["profile"] == "reviewer"


def test_cli_blocked_exits_one_and_text_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    root = tmp_path / "library"
    root.mkdir()
    log_path = _threshold_log(tmp_path, ok_echo=1, ok_hidden=4)
    code = run_cli(root, "--audit-log", str(log_path), "--profiles", str(profiles_path(tmp_path)))
    assert code == 1
    out = capsys.readouterr().out
    assert "read-only" in out
    assert "recommendation: BLOCKED" in out
    assert "newly denied" in out


def test_cli_missing_audit_log_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNLIMITED_SKILLS_MCP_PROFILE", raising=False)
    root = tmp_path / "library"
    root.mkdir()
    code = run_cli(root, "--audit-log", str(tmp_path / "absent.jsonl"))
    assert code == 1
    assert "Audit log not found" in capsys.readouterr().err


def test_would_be_name_table() -> None:
    assert would_be_name(TOOL_NOT_VISIBLE) == "tool_not_visible"
    assert would_be_name(TOOL_NOT_CALLABLE) == "tool_not_callable"
    assert would_be_name(-32005) == "upstream_disabled"
    assert would_be_name(-32010) == "trust_level_violation"
    assert would_be_name(-32017) == "bundle_revoked"
    assert would_be_name(-99999) == "unknown"


def test_evaluate_call_open_policy_allows() -> None:
    from unlimited_skills.mcp.audit_replay import _ProposedPolicy

    policy = _ProposedPolicy()
    assert evaluate_call(policy, "tools_call", "fake", "echo") == (True, 0, "")
