"""E07 design artifacts: validate the upstream config example against its schema.

The repo deliberately has no `jsonschema` dependency (existing schema tests
only assert valid JSON), so this test ships a minimal validator covering
exactly the JSON Schema (draft 2020-12) keywords that
``schemas/mcp-upstream-config.schema.json`` uses: type, const, enum,
required, properties, additionalProperties (false), items, pattern,
minLength, minimum, maximum, exclusiveMinimum, uniqueItems, maxItems.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "mcp-upstream-config.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "mcp" / "upstreams.example.json"

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
    if expected == "integer" and isinstance(value, float) and not float(value).is_integer():
        return [f"{path}: expected integer, got non-integral number"]
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
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: not above exclusiveMinimum {schema['exclusiveMinimum']}")
    return errors


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def example() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def test_schema_is_valid_json_draft_2020_12(schema: dict) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    upstream_schema = schema["properties"]["upstreams"]["items"]
    assert upstream_schema["additionalProperties"] is False
    assert set(upstream_schema["properties"]["trust_level"]["enum"]) == {
        "disabled",
        "local-trusted",
        "local-restricted",
        "future-remote-placeholder",
    }
    # Default is the most restrictive level that still runs a local upstream.
    assert upstream_schema["properties"]["trust_level"]["default"] == "local-restricted"
    # Env allowlist entries are variable NAMES; the pattern makes '*' unrepresentable.
    name_pattern = upstream_schema["properties"]["env_allowlist"]["items"]["pattern"]
    assert re.search(name_pattern, "GITHUB_PERSONAL_ACCESS_TOKEN")
    assert not re.search(name_pattern, "*")
    assert not re.search(name_pattern, "GITHUB_*")


def test_example_validates_against_schema(schema: dict, example: dict) -> None:
    assert validate(example, schema) == []
    names = [spec["name"] for spec in example["upstreams"]]
    assert len(names) == len(set(names))
    levels = {spec["trust_level"] for spec in example["upstreams"]}
    assert {"local-trusted", "local-restricted", "future-remote-placeholder"} <= levels


def test_unknown_trust_level_rejected(schema: dict, example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["upstreams"][0]["trust_level"] = "remote-oauth"
    errors = validate(bad, schema)
    assert any("trust_level" in error and "enum" in error for error in errors)


def test_env_wildcard_rejected(schema: dict, example: dict) -> None:
    for wildcard in ("*", "GITHUB_*", "AWS_*"):
        bad = copy.deepcopy(example)
        bad["upstreams"][0]["env_allowlist"] = [wildcard]
        errors = validate(bad, schema)
        assert any("env_allowlist" in error and "pattern" in error for error in errors), wildcard


def test_env_literal_value_map_rejected(schema: dict, example: dict) -> None:
    # The v1 'env' literal map does not exist in this format; unknown keys fail.
    bad = copy.deepcopy(example)
    bad["upstreams"][0]["env"] = {"GITHUB_PERSONAL_ACCESS_TOKEN": "%GITHUB_PERSONAL_ACCESS_TOKEN%"}
    errors = validate(bad, schema)
    assert any("additional property 'env'" in error for error in errors)


def test_oversize_limits_rejected(schema: dict, example: dict) -> None:
    oversize = {
        "max_schema_bytes": 1048576 + 1,
        "max_response_bytes": 8388608 + 1,
        "startup_timeout_seconds": 121,
        "request_timeout_seconds": 301,
    }
    for key, value in oversize.items():
        bad = copy.deepcopy(example)
        bad["upstreams"][0][key] = value
        errors = validate(bad, schema)
        assert any(key in error and "maximum" in error for error in errors), key


def test_zero_timeout_rejected(schema: dict, example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["request_timeout_seconds"] = 0
    errors = validate(bad, schema)
    assert any("exclusiveMinimum" in error for error in errors)


def test_validator_rejects_wrong_types_and_missing_required(schema: dict, example: dict) -> None:
    # Self-check of the minimal validator on shapes the schema must refuse.
    assert validate({"schema_version": 1}, schema)  # missing upstreams
    bad = copy.deepcopy(example)
    del bad["upstreams"][0]["command"]
    assert any("command" in error for error in validate(bad, schema))
    bad = copy.deepcopy(example)
    bad["upstreams"][0]["enabled"] = "yes"
    assert any("expected boolean" in error for error in validate(bad, schema))
    bad = copy.deepcopy(example)
    bad["upstreams"][0]["max_schema_bytes"] = True  # bool is not an integer here
    assert any("got bool" in error for error in validate(bad, schema))
