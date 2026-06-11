"""E09 design artifacts: validate the tool-profile example against its schema.

The repo deliberately has no `jsonschema` dependency (same stance as
``tests/test_mcp_upstream_config_schema.py``), so this test ships a minimal
validator covering exactly the JSON Schema (draft 2020-12) keywords that
``schemas/mcp-tool-profile.schema.json`` uses: type, const, enum, required,
properties, patternProperties, additionalProperties (false), items, pattern,
minLength, maxLength, minimum, maximum, exclusiveMinimum, uniqueItems,
maxItems, minProperties, maxProperties.

It also encodes, as executable documentation, the SEMANTIC load rules the
design (docs/mcp-permissioned-tool-profiles.md) requires beyond the schema:
``extends`` targets exist, no self-reference, no cycles, chain depth <= 8,
``default_profile`` exists, and every ``callable`` rule is covered by a
``visible`` rule (callable is always a subset of visible).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "mcp-tool-profile.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "mcp" / "tool-profile.example.json"

MAX_EXTENDS_DEPTH = 8

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
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            errors.append(f"{path}: fewer than {schema['minProperties']} properties")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errors.append(f"{path}: more than {schema['maxProperties']} properties")
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        pattern_properties = schema.get("patternProperties", {})
        for key, item in value.items():
            matched = False
            if key in properties:
                matched = True
                errors.extend(validate(item, properties[key], f"{path}.{key}"))
            for key_pattern, sub_schema in pattern_properties.items():
                if re.search(key_pattern, key):
                    matched = True
                    errors.extend(validate(item, sub_schema, f"{path}.{key}"))
            if not matched and schema.get("additionalProperties") is False:
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
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength {schema['maxLength']}")
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


def _rule_covered(rule: str, visible: list[str]) -> bool:
    """Coverage per the design: exact rules are covered by the same exact rule
    or by their upstream's '.*' rule; a '.*' rule only by the same '.*' rule."""
    if rule in visible:
        return True
    upstream, _, tool = rule.partition(".")
    if tool == "*":
        return False
    return f"{upstream}.*" in visible


def profile_load_errors(document: dict) -> list[str]:
    """The semantic load rules the design requires beyond the schema.

    Mirrors docs/mcp-permissioned-tool-profiles.md "Static load checks";
    any violation is a profile_invalid (-32014) fail-closed state.
    """
    errors: list[str] = []
    profiles = document.get("profiles")
    if not isinstance(profiles, dict):
        return ["profiles must be an object"]
    default = document.get("default_profile")
    if default is not None and default not in profiles:
        errors.append(f"default_profile {default!r} does not exist")
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            errors.append(f"profile {name!r} must be an object")
            continue
        # extends: single parent, exists, no self-reference, no cycle, bounded depth.
        chain = [name]
        current = profile
        while "extends" in current:
            parent = current["extends"]
            if parent == chain[-1] or parent in chain:
                errors.append(f"profile {name!r}: extends cycle via {parent!r}")
                break
            if parent not in profiles:
                errors.append(f"profile {name!r}: extends unknown profile {parent!r}")
                break
            chain.append(parent)
            if len(chain) > MAX_EXTENDS_DEPTH:
                errors.append(f"profile {name!r}: extends chain deeper than {MAX_EXTENDS_DEPTH}")
                break
            current = profiles[parent]
            if not isinstance(current, dict):
                break
        # Callable coverage: callable is always a subset of visible.
        visible = profile.get("visible")
        callable_rules = profile.get("callable")
        if isinstance(visible, list) and isinstance(callable_rules, list):
            for rule in callable_rules:
                if not _rule_covered(rule, visible):
                    errors.append(
                        f"profile {name!r}: callable rule {rule!r} is not covered by visible"
                    )
    return errors


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def example() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def _rule_pattern(schema: dict) -> str:
    profile_schema = next(iter(schema["properties"]["profiles"]["patternProperties"].values()))
    return profile_schema["properties"]["visible"]["items"]["pattern"]


def test_schema_is_valid_json_draft_2020_12(schema: dict) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"] == {"const": 1}
    profiles_schema = schema["properties"]["profiles"]
    assert profiles_schema["additionalProperties"] is False
    profile_schema = next(iter(profiles_schema["patternProperties"].values()))
    assert profile_schema["additionalProperties"] is False
    assert schema["properties"]["signature"]["additionalProperties"] is False
    # Visibility and callability share one bounded rule grammar.
    pattern = _rule_pattern(schema)
    assert profile_schema["properties"]["callable"]["items"]["pattern"] == pattern


def test_rule_grammar_is_bounded(schema: dict) -> None:
    pattern = _rule_pattern(schema)
    # Exactly two rule forms: exact '<upstream>.<tool>' and '<upstream>.*'.
    for allowed in ("github.create_issue", "github.*", "filesystem.read_file", "a.b.c"):
        assert re.search(pattern, allowed), allowed
    rejected = [
        "github.create_*",  # partial glob
        "*.create_issue",  # wildcard upstream segment
        "*.*",  # wildcard everything
        "github create_issue",  # whitespace
        "github.(create|delete)_issue",  # regex alternation
        "github.[ct]ool",  # regex character class
        "github.tool+",  # regex quantifier
        "github",  # no tool segment
        "github.",  # empty tool segment
        "github..tool",  # tool segment starting with '.'
        ".tool",  # empty upstream segment
    ]
    for rule in rejected:
        assert not re.search(pattern, rule), rule


def test_example_validates_against_schema(schema: dict, example: dict) -> None:
    assert validate(example, schema) == []
    assert profile_load_errors(example) == []
    assert example["default_profile"] in example["profiles"]
    # The example exercises inheritance: at least one profile extends another.
    assert any("extends" in profile for profile in example["profiles"].values())


def test_signature_envelope_shape(schema: dict, example: dict) -> None:
    signed = copy.deepcopy(example)
    signed["signature"] = {
        "algorithm": "ed25519",
        "key_id": "team-profiles-2026",
        "value": "c2lnbmF0dXJlLWJ5dGVz",
    }
    assert validate(signed, schema) == []
    bad = copy.deepcopy(signed)
    bad["signature"]["algorithm"] = "md5"
    assert any("algorithm" in error and "enum" in error for error in validate(bad, schema))
    bad = copy.deepcopy(signed)
    del bad["signature"]["key_id"]
    assert any("key_id" in error for error in validate(bad, schema))
    bad = copy.deepcopy(signed)
    bad["signature"]["value"] = "not base64!!"
    assert any("value" in error and "pattern" in error for error in validate(bad, schema))


def test_unknown_keys_rejected(schema: dict, example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["deny"] = ["github.*"]  # no deny lists exist in this format
    errors = validate(bad, schema)
    assert any("additional property 'deny'" in error for error in errors)
    bad = copy.deepcopy(example)
    bad["profiles"]["dev-default"]["visble"] = ["github.*"]  # typo must fail loudly
    errors = validate(bad, schema)
    assert any("additional property 'visble'" in error for error in errors)


def test_invalid_rule_strings_rejected(schema: dict, example: dict) -> None:
    for rule in ("github.create_*", "*.read_file", "github tool", "github.(a|b)", "github"):
        bad = copy.deepcopy(example)
        bad["profiles"]["dev-default"]["visible"] = [rule]
        errors = validate(bad, schema)
        assert any("visible" in error and "pattern" in error for error in errors), rule


def test_invalid_profile_names_rejected(schema: dict, example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["profiles"]["bad name"] = {"visible": ["github.*"]}
    errors = validate(bad, schema)
    assert any("additional property 'bad name'" in error for error in errors)
    bad = copy.deepcopy(example)
    bad["profiles"] = {}
    errors = validate(bad, schema)
    assert any("minProperties" in error or "fewer than" in error for error in errors)


def test_wrong_types_rejected(schema: dict, example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["schema_version"] = 2
    assert any("const" in error for error in validate(bad, schema))
    bad = copy.deepcopy(example)
    bad["profiles"] = []
    assert any("expected object" in error for error in validate(bad, schema))
    bad = copy.deepcopy(example)
    bad["profiles"]["dev-default"]["visible"] = "github.*"
    assert any("expected array" in error for error in validate(bad, schema))
    bad = copy.deepcopy(example)
    bad["profiles"]["dev-default"]["extends"] = 7
    assert any("expected string" in error for error in validate(bad, schema))


def test_duplicate_rules_rejected(schema: dict, example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["profiles"]["dev-default"]["visible"] = ["github.*", "github.*"]
    assert any("not unique" in error for error in validate(bad, schema))


def test_self_extends_is_a_load_error(example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["profiles"]["dev-default"]["extends"] = "dev-default"
    errors = profile_load_errors(bad)
    assert any("cycle" in error for error in errors)


def test_extends_cycle_and_unknown_parent_are_load_errors(example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["profiles"]["dev-default"]["extends"] = "ci-minimal"  # ci-minimal -> reviewer -> dev-default
    errors = profile_load_errors(bad)
    assert any("cycle" in error for error in errors)
    bad = copy.deepcopy(example)
    bad["profiles"]["reviewer"]["extends"] = "nonexistent"
    errors = profile_load_errors(bad)
    assert any("unknown profile" in error for error in errors)


def test_uncovered_callable_rule_is_a_load_error(example: dict) -> None:
    # Callable is always a subset of visible: a callable rule wider than the
    # visible rules (or outside them) must be refused at load.
    bad = copy.deepcopy(example)
    bad["profiles"]["ci-minimal"]["callable"] = ["github.*"]
    errors = profile_load_errors(bad)
    assert any("not covered by visible" in error for error in errors)
    bad = copy.deepcopy(example)
    bad["profiles"]["ci-minimal"]["callable"] = ["filesystem.read_file"]
    errors = profile_load_errors(bad)
    assert any("not covered by visible" in error for error in errors)


def test_missing_default_profile_is_a_load_error(example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["default_profile"] = "ghost"
    errors = profile_load_errors(bad)
    assert any("default_profile" in error for error in errors)
