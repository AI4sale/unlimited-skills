"""E23 design artifacts: validate the distribution examples against their schemas.

The repo deliberately has no ``jsonschema`` dependency (same stance as
``tests/test_mcp_profile_bundle_schema.py``), so this test ships the same
minimal self-contained validator covering exactly the JSON Schema
(draft 2020-12) keywords that ``schemas/mcp-bundle-channel.schema.json``
and ``schemas/mcp-bundle-assignment.schema.json`` use.

It also encodes, as executable documentation, the SEMANTIC load rules the
design (docs/mcp-bundle-distribution.md) requires beyond the schemas:

- channel: exactly one history record has status ``active`` and ``current``
  equals its ``bundle_sha256``; ``published_at`` is non-decreasing across
  the history; ``signature.key_id`` equals ``owner.key_id`` when signed.
- assignment: ``pin`` mode requires ``bundle_sha256`` and ``follow`` mode
  forbids it (exactly one artifact owns the pointer); ``issued_at``
  strictly before ``expires_at``; ``signature.key_id`` equals
  ``issuer.key_id`` when signed.

E23 is design-only: nothing here verifies signatures or implements any
distribution behavior -- these tests pin the FILE CONTRACTS.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHANNEL_SCHEMA_PATH = ROOT / "schemas" / "mcp-bundle-channel.schema.json"
ASSIGNMENT_SCHEMA_PATH = ROOT / "schemas" / "mcp-bundle-assignment.schema.json"
CHANNEL_EXAMPLE_PATH = ROOT / "examples" / "mcp" / "bundle-channel.example.json"
ASSIGNMENT_EXAMPLE_PATH = ROOT / "examples" / "mcp" / "bundle-assignment.example.json"
BUNDLE_SCHEMA_PATH = ROOT / "schemas" / "mcp-profile-bundle.schema.json"

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
    """Return a list of violation strings (empty = valid)."""
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']!r}")
    if "type" in schema:
        type_errors = _check_type(value, schema["type"], path)
        if type_errors:
            return errors + type_errors  # further keyword checks would mislead
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
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = [json.dumps(item, sort_keys=True) for item in value]
            if len(set(seen)) != len(seen):
                errors.append(f"{path}: items are not unique")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(validate(item, schema["items"], f"{path}[{index}]"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    return errors


def channel_load_errors(document: dict) -> list[str]:
    """The semantic load rules the design requires beyond the channel schema."""
    errors: list[str] = []
    history = document.get("history")
    if not isinstance(history, list):
        return ["history must be an array"]
    active = [
        record
        for record in history
        if isinstance(record, dict) and record.get("status") == "active"
    ]
    if len(active) != 1:
        errors.append(
            f"history must contain exactly one active record, found {len(active)}"
        )
    elif document.get("current") != active[0].get("bundle_sha256"):
        errors.append("current must equal the active record's bundle_sha256")
    stamps = [
        record.get("published_at")
        for record in history
        if isinstance(record, dict) and isinstance(record.get("published_at"), str)
    ]
    if any(later < earlier for earlier, later in zip(stamps, stamps[1:])):
        errors.append("history published_at must be non-decreasing")
    owner = document.get("owner")
    signature = document.get("signature")
    if isinstance(owner, dict) and isinstance(signature, dict):
        if signature.get("key_id") != owner.get("key_id"):
            errors.append("signature.key_id must equal owner.key_id")
    return errors


def assignment_load_errors(document: dict) -> list[str]:
    """The semantic load rules the design requires beyond the assignment schema."""
    errors: list[str] = []
    mode = document.get("mode")
    if mode == "pin" and "bundle_sha256" not in document:
        errors.append("pin mode requires bundle_sha256")
    if mode == "follow" and "bundle_sha256" in document:
        errors.append(
            "follow mode forbids bundle_sha256 (the channel owns the pointer)"
        )
    issued_at = document.get("issued_at")
    expires_at = document.get("expires_at")
    if (
        isinstance(issued_at, str)
        and isinstance(expires_at, str)
        and not issued_at < expires_at
    ):
        errors.append("issued_at must be strictly before expires_at")
    issuer = document.get("issuer")
    signature = document.get("signature")
    if isinstance(issuer, dict) and isinstance(signature, dict):
        if signature.get("key_id") != issuer.get("key_id"):
            errors.append("signature.key_id must equal issuer.key_id")
    return errors


@pytest.fixture(scope="module")
def channel_schema() -> dict:
    return json.loads(CHANNEL_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def assignment_schema() -> dict:
    return json.loads(ASSIGNMENT_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def channel() -> dict:
    return json.loads(CHANNEL_EXAMPLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def assignment() -> dict:
    return json.loads(ASSIGNMENT_EXAMPLE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Schema shape: draft 2020-12, strict keys, envelopes mirror E13.


def test_schemas_are_strict_draft_2020_12(
    channel_schema: dict, assignment_schema: dict
) -> None:
    for schema in (channel_schema, assignment_schema):
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False
    assert channel_schema["properties"]["channel_version"] == {"const": 1}
    assert assignment_schema["properties"]["assignment_version"] == {"const": 1}
    # The signature envelope is OPTIONAL in both formats (decision 1: MIT
    # core may distribute unsigned routing files; the registered tier
    # requires signatures by policy, not by schema).
    assert "signature" not in channel_schema["required"]
    assert "signature" not in assignment_schema["required"]
    # Validity is mandatory for assignments; channels deliberately carry no
    # validity window (freshness rides on bundle expiry plus revision).
    for key in ("issued_at", "expires_at", "revision", "audience", "channel", "mode"):
        assert key in assignment_schema["required"], key
    for key in ("name", "revision", "owner", "history", "current"):
        assert key in channel_schema["required"], key
    assert "issued_at" not in channel_schema["properties"]


def test_envelopes_and_grammars_mirror_the_bundle_schema(
    channel_schema: dict, assignment_schema: dict
) -> None:
    """Key ids, audience identifiers, timestamps, and signature envelopes
    reuse the exact E13 constraints from schemas/mcp-profile-bundle.schema.json
    -- keep the duplication honest by comparing against the bundle schema."""
    bundle = json.loads(BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
    bundle_signature = bundle["properties"]["signature"]
    for schema in (channel_schema, assignment_schema):
        signature = schema["properties"]["signature"]
        assert signature["required"] == bundle_signature["required"]
        for key in ("algorithm", "key_id", "value"):
            for keyword in ("enum", "pattern", "minLength", "maxLength"):
                assert signature["properties"][key].get(keyword) == bundle_signature[
                    "properties"
                ][key].get(keyword), (key, keyword)
    # Audience grammar is byte-identical to the bundle audience grammar.
    bundle_audience = bundle["properties"]["audience"]
    assignment_audience = assignment_schema["properties"]["audience"]
    for keyword in ("minItems", "maxItems", "uniqueItems"):
        assert assignment_audience[keyword] == bundle_audience[keyword]
    assert assignment_audience["items"]["pattern"] == bundle_audience["items"]["pattern"]
    # Key-id and timestamp grammars match the bundle issuer/timestamps.
    issuer_key = bundle["properties"]["issuer"]["properties"]["key_id"]
    assert (
        channel_schema["properties"]["owner"]["properties"]["key_id"]["pattern"]
        == issuer_key["pattern"]
    )
    assert (
        assignment_schema["properties"]["issuer"]["properties"]["key_id"]["pattern"]
        == issuer_key["pattern"]
    )
    timestamp_pattern = bundle["properties"]["issued_at"]["pattern"]
    assert assignment_schema["properties"]["issued_at"]["pattern"] == timestamp_pattern
    assert assignment_schema["properties"]["expires_at"]["pattern"] == timestamp_pattern
    history_items = channel_schema["properties"]["history"]["items"]
    assert history_items["properties"]["published_at"]["pattern"] == timestamp_pattern


# ---------------------------------------------------------------------------
# Positive: the shipped examples validate, structurally and semantically.


def test_channel_example_validates(channel_schema: dict, channel: dict) -> None:
    assert validate(channel, channel_schema) == []
    assert channel_load_errors(channel) == []
    # The example exercises rollback-by-superseding-record: the active
    # record re-publishes a sha that appears earlier in the history.
    shas = [record["bundle_sha256"] for record in channel["history"]]
    assert channel["current"] in shas[:-1]
    statuses = [record["status"] for record in channel["history"]]
    assert statuses.count("active") == 1
    assert "revoked" in statuses
    # The example's signature is a clearly fake placeholder (zero bytes).
    assert set(channel["signature"]["value"].rstrip("=")) == {"A"}


def test_assignment_example_validates(
    assignment_schema: dict, assignment: dict
) -> None:
    assert validate(assignment, assignment_schema) == []
    assert assignment_load_errors(assignment) == []
    assert assignment["mode"] == "pin"
    assert set(assignment["signature"]["value"].rstrip("=")) == {"A"}


def test_examples_are_cross_consistent(assignment: dict, channel: dict) -> None:
    """The shipped assignment pins the shipped channel's current bundle and
    names the channel by its full identity pair."""
    assert assignment["bundle_sha256"] == channel["current"]
    assert assignment["channel"]["name"] == channel["name"]
    assert assignment["channel"]["owner_key_id"] == channel["owner"]["key_id"]


def test_unsigned_documents_are_schema_valid(
    channel_schema: dict, assignment_schema: dict, channel: dict, assignment: dict
) -> None:
    """Decision 1: the MIT core may use unsigned routing files -- the
    signature member is optional in the FORMAT (the registered tier
    requires it by policy)."""
    unsigned_channel = copy.deepcopy(channel)
    del unsigned_channel["signature"]
    assert validate(unsigned_channel, channel_schema) == []
    assert channel_load_errors(unsigned_channel) == []
    unsigned_assignment = copy.deepcopy(assignment)
    del unsigned_assignment["signature"]
    assert validate(unsigned_assignment, assignment_schema) == []
    assert assignment_load_errors(unsigned_assignment) == []


def test_follow_mode_without_sha_is_valid(
    assignment_schema: dict, assignment: dict
) -> None:
    follow = copy.deepcopy(assignment)
    follow["mode"] = "follow"
    del follow["bundle_sha256"]
    assert validate(follow, assignment_schema) == []
    assert assignment_load_errors(follow) == []


# ---------------------------------------------------------------------------
# Negative: unknown keys, bad sha formats, empty history, semantic breaks.


def test_unknown_top_level_keys_rejected(
    channel_schema: dict, assignment_schema: dict, channel: dict, assignment: dict
) -> None:
    bad = copy.deepcopy(channel)
    bad["auto_trust"] = True  # no such switch exists in this format
    errors = validate(bad, channel_schema)
    assert any("additional property 'auto_trust'" in error for error in errors)
    bad = copy.deepcopy(assignment)
    bad["grace_days"] = 30  # no offline grace timer exists (decision 7)
    errors = validate(bad, assignment_schema)
    assert any("additional property 'grace_days'" in error for error in errors)
    bad = copy.deepcopy(channel)
    bad["history"][0]["url"] = "https://example.com/bundle"
    errors = validate(bad, channel_schema)
    assert any("additional property 'url'" in error for error in errors)


def test_bad_sha256_formats_rejected(
    channel_schema: dict, assignment_schema: dict, channel: dict, assignment: dict
) -> None:
    for bad_sha in (
        "1111",  # too short
        "1" * 63,  # one short of 64
        "1" * 65,  # one over
        "G" * 64,  # not hex
        "A" * 64,  # uppercase hex is not the content-address form
    ):
        bad = copy.deepcopy(channel)
        bad["current"] = bad_sha
        errors = validate(bad, channel_schema)
        assert any("current" in error and "pattern" in error for error in errors), bad_sha
        bad = copy.deepcopy(channel)
        bad["history"][0]["bundle_sha256"] = bad_sha
        errors = validate(bad, channel_schema)
        assert any("bundle_sha256" in error and "pattern" in error for error in errors), bad_sha
        bad = copy.deepcopy(assignment)
        bad["bundle_sha256"] = bad_sha
        errors = validate(bad, assignment_schema)
        assert any("bundle_sha256" in error and "pattern" in error for error in errors), bad_sha


def test_empty_channel_history_rejected(channel_schema: dict, channel: dict) -> None:
    bad = copy.deepcopy(channel)
    bad["history"] = []
    errors = validate(bad, channel_schema)
    assert any("history" in error and "fewer than 1" in error for error in errors)


def test_unknown_history_status_rejected(channel_schema: dict, channel: dict) -> None:
    bad = copy.deepcopy(channel)
    bad["history"][2]["status"] = "latest"  # only active/superseded/revoked
    errors = validate(bad, channel_schema)
    assert any("status" in error and "enum" in error for error in errors)


def test_unknown_mode_rejected(assignment_schema: dict, assignment: dict) -> None:
    bad = copy.deepcopy(assignment)
    bad["mode"] = "track"  # only follow/pin
    errors = validate(bad, assignment_schema)
    assert any("mode" in error and "enum" in error for error in errors)


def test_bad_audience_and_channel_names_rejected(
    channel_schema: dict, assignment_schema: dict, channel: dict, assignment: dict
) -> None:
    for identifier in ("core-ai4sale", "user:somebody", "team:", "*"):
        bad = copy.deepcopy(assignment)
        bad["audience"] = [identifier]
        errors = validate(bad, assignment_schema)
        assert any("audience" in error and "pattern" in error for error in errors), identifier
    for name in ("stable channel", "-stable", ""):
        bad = copy.deepcopy(channel)
        bad["name"] = name
        errors = validate(bad, channel_schema)
        assert any("name" in error for error in errors), name


def test_zero_revision_rejected(
    channel_schema: dict, assignment_schema: dict, channel: dict, assignment: dict
) -> None:
    bad = copy.deepcopy(channel)
    bad["revision"] = 0
    errors = validate(bad, channel_schema)
    assert any("revision" in error and "minimum" in error for error in errors)
    bad = copy.deepcopy(assignment)
    bad["revision"] = 0
    errors = validate(bad, assignment_schema)
    assert any("revision" in error and "minimum" in error for error in errors)


def test_timestamp_format_is_strict(assignment_schema: dict, assignment: dict) -> None:
    for stamp in ("2026-06-08", "2026-06-08T00:00:00+02:00", "now"):
        bad = copy.deepcopy(assignment)
        bad["issued_at"] = stamp
        errors = validate(bad, assignment_schema)
        assert any("issued_at" in error and "pattern" in error for error in errors), stamp


def test_pin_without_sha_is_a_load_error(assignment: dict) -> None:
    bad = copy.deepcopy(assignment)
    del bad["bundle_sha256"]  # mode stays "pin"
    errors = assignment_load_errors(bad)
    assert any("pin mode requires" in error for error in errors)


def test_follow_with_sha_is_a_load_error(assignment: dict) -> None:
    bad = copy.deepcopy(assignment)
    bad["mode"] = "follow"  # bundle_sha256 stays present
    errors = assignment_load_errors(bad)
    assert any("follow mode forbids" in error for error in errors)


def test_expired_before_issued_is_a_load_error(assignment: dict) -> None:
    bad = copy.deepcopy(assignment)
    bad["issued_at"], bad["expires_at"] = bad["expires_at"], bad["issued_at"]
    errors = assignment_load_errors(bad)
    assert any("strictly before" in error for error in errors)
    bad["expires_at"] = bad["issued_at"]  # an empty window is equally invalid
    errors = assignment_load_errors(bad)
    assert any("strictly before" in error for error in errors)


def test_current_must_match_the_single_active_record(channel: dict) -> None:
    bad = copy.deepcopy(channel)
    bad["current"] = bad["history"][1]["bundle_sha256"]  # the revoked sha
    errors = channel_load_errors(bad)
    assert any("active record" in error for error in errors)
    bad = copy.deepcopy(channel)
    bad["history"][0]["status"] = "active"  # two active records
    errors = channel_load_errors(bad)
    assert any("exactly one active" in error for error in errors)
    bad = copy.deepcopy(channel)
    bad["history"][2]["status"] = "superseded"  # zero active records
    errors = channel_load_errors(bad)
    assert any("exactly one active" in error for error in errors)


def test_history_timestamps_must_be_ordered(channel: dict) -> None:
    bad = copy.deepcopy(channel)
    bad["history"][2]["published_at"] = "2026-01-01T00:00:00Z"  # before record 1
    errors = channel_load_errors(bad)
    assert any("non-decreasing" in error for error in errors)


def test_signature_key_id_must_match_owner_and_issuer(
    channel: dict, assignment: dict
) -> None:
    bad = copy.deepcopy(channel)
    bad["signature"]["key_id"] = "some-other-key"
    errors = channel_load_errors(bad)
    assert any("owner.key_id" in error for error in errors)
    bad = copy.deepcopy(assignment)
    bad["signature"]["key_id"] = "some-other-key"
    errors = assignment_load_errors(bad)
    assert any("issuer.key_id" in error for error in errors)
