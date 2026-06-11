"""E13 design artifacts: validate the profile-bundle example against its schema.

The repo deliberately has no `jsonschema` dependency (same stance as
``tests/test_mcp_tool_profile_schema.py`` and
``tests/test_mcp_upstream_config_schema.py``), so this test ships the same
minimal self-contained validator, extended with ``minItems``, covering
exactly the JSON Schema (draft 2020-12) keywords that
``schemas/mcp-profile-bundle.schema.json`` uses.

It also encodes, as executable documentation, the SEMANTIC load rules the
design (docs/mcp-signed-profile-bundles.md) requires beyond the schema:
``issued_at`` strictly before ``expires_at``, ``signature.key_id`` equal to
``issuer.key_id``, every ``visible``/``callable`` rule covered by the
bundle's ``allowed_upstream_namespaces``, plus the E09 profile checks
(``extends`` targets exist, no self-reference, no cycles, chain depth <= 8,
``default_profile`` exists, callable covered by visible).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "mcp-profile-bundle.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "mcp" / "profile-bundle.example.json"

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
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: not above exclusiveMinimum {schema['exclusiveMinimum']}")
    return errors


def _rule_covered(rule: str, covering: list[str]) -> bool:
    """Coverage per the design: an exact rule is covered by the same exact rule
    or by its upstream's '.*' rule; a '.*' rule only by the same '.*' rule."""
    if rule in covering:
        return True
    upstream, _, tool = rule.partition(".")
    if tool == "*":
        return False
    return f"{upstream}.*" in covering


def bundle_load_errors(document: dict) -> list[str]:
    """The semantic load rules the design requires beyond the schema.

    Mirrors docs/mcp-signed-profile-bundles.md "Verification algorithm"
    steps 2, 8, and 9 (the static, signature-free checks); any violation is
    a fail-closed state (-32014 profile_invalid for structural breaks,
    -32018 bundle_audience_mismatch for namespace-ceiling violations).
    """
    errors: list[str] = []
    profiles = document.get("profiles")
    if not isinstance(profiles, dict):
        return ["profiles must be an object"]
    issuer = document.get("issuer")
    signature = document.get("signature")
    if isinstance(issuer, dict) and isinstance(signature, dict):
        if issuer.get("key_id") != signature.get("key_id"):
            errors.append("signature.key_id must equal issuer.key_id")
    issued_at = document.get("issued_at")
    expires_at = document.get("expires_at")
    if isinstance(issued_at, str) and isinstance(expires_at, str) and not issued_at < expires_at:
        errors.append("issued_at must be strictly before expires_at")
    namespaces = document.get("allowed_upstream_namespaces")
    default = document.get("default_profile")
    if default is not None and default not in profiles:
        errors.append(f"default_profile {default!r} does not exist")
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            errors.append(f"profile {name!r} must be an object")
            continue
        # extends: single parent, exists IN THIS BUNDLE (self-contained),
        # no self-reference, no cycle, bounded depth.
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
        # Namespace ceiling: every rule must be covered by the bundle's
        # allowed_upstream_namespaces (decision 10, -32018 on violation).
        if isinstance(namespaces, list):
            for field in ("visible", "callable"):
                rules = profile.get(field)
                if not isinstance(rules, list):
                    continue
                for rule in rules:
                    if isinstance(rule, str) and not _rule_covered(rule, namespaces):
                        errors.append(
                            f"profile {name!r}: {field} rule {rule!r} is outside "
                            "allowed_upstream_namespaces"
                        )
    return errors


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def example() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def _profile_schema(schema: dict) -> dict:
    return next(iter(schema["properties"]["profiles"]["patternProperties"].values()))


def test_schema_is_valid_json_draft_2020_12(schema: dict) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["bundle_version"] == {"const": 1}
    # A bundle without a signature is not a bundle: signature is REQUIRED,
    # unlike the optional shape-only envelope of the E09 profile file.
    for key in ("issuer", "audience", "issued_at", "expires_at",
                "allowed_upstream_namespaces", "profiles", "signature"):
        assert key in schema["required"], key
    assert schema["properties"]["signature"]["additionalProperties"] is False
    assert schema["properties"]["issuer"]["additionalProperties"] is False
    profiles_schema = schema["properties"]["profiles"]
    assert profiles_schema["additionalProperties"] is False
    profile_schema = _profile_schema(schema)
    assert profile_schema["additionalProperties"] is False
    # The embedded profile shape duplicates the E09 rule grammar verbatim,
    # and the namespace ceiling uses the same grammar.
    rule_pattern = profile_schema["properties"]["visible"]["items"]["pattern"]
    assert profile_schema["properties"]["callable"]["items"]["pattern"] == rule_pattern
    assert schema["properties"]["allowed_upstream_namespaces"]["items"]["pattern"] == rule_pattern


def test_embedded_profiles_match_e09_schema_shape(schema: dict) -> None:
    """The bundle duplicates (not $refs) the E09 profile constraints; keep
    the duplication honest by comparing against the E09 schema file."""
    e09 = json.loads((ROOT / "schemas" / "mcp-tool-profile.schema.json").read_text(encoding="utf-8"))
    e09_profiles = e09["properties"]["profiles"]
    bundle_profiles = schema["properties"]["profiles"]
    e09_profile = next(iter(e09_profiles["patternProperties"].values()))
    bundle_profile = _profile_schema(schema)
    assert set(bundle_profiles["patternProperties"]) == set(e09_profiles["patternProperties"])
    assert bundle_profiles["minProperties"] == e09_profiles["minProperties"]
    assert bundle_profiles["maxProperties"] == e09_profiles["maxProperties"]
    assert set(bundle_profile["properties"]) == set(e09_profile["properties"])
    for field in ("visible", "callable"):
        for keyword in ("uniqueItems", "maxItems"):
            assert bundle_profile["properties"][field][keyword] == e09_profile["properties"][field][keyword]
        assert (bundle_profile["properties"][field]["items"]["pattern"]
                == e09_profile["properties"][field]["items"]["pattern"])
    assert bundle_profile["properties"]["extends"]["pattern"] == e09_profile["properties"]["extends"]["pattern"]
    # And the signature envelope keeps the E09 shape (constraints identical).
    for key in ("algorithm", "key_id", "value"):
        e09_sub = e09["properties"]["signature"]["properties"][key]
        bundle_sub = schema["properties"]["signature"]["properties"][key]
        for keyword in ("enum", "pattern", "minLength", "maxLength"):
            assert e09_sub.get(keyword) == bundle_sub.get(keyword), (key, keyword)


def test_example_validates_against_schema(schema: dict, example: dict) -> None:
    assert validate(example, schema) == []
    assert bundle_load_errors(example) == []
    assert example["default_profile"] in example["profiles"]
    assert example["signature"]["key_id"] == example["issuer"]["key_id"]
    # The example's signature is a clearly fake placeholder (zero bytes).
    assert set(example["signature"]["value"].rstrip("=")) == {"A"}
    # The example exercises inheritance: at least one profile extends another.
    assert any("extends" in profile for profile in example["profiles"].values())


def test_missing_signature_block_rejected(schema: dict, example: dict) -> None:
    bad = copy.deepcopy(example)
    del bad["signature"]
    errors = validate(bad, schema)
    assert any("missing required property 'signature'" in error for error in errors)


def test_unknown_algorithm_rejected(schema: dict, example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["signature"]["algorithm"] = "rsa-sha256"
    errors = validate(bad, schema)
    assert any("algorithm" in error and "enum" in error for error in errors)


def test_expired_before_issued_is_a_load_error(example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["issued_at"], bad["expires_at"] = bad["expires_at"], bad["issued_at"]
    errors = bundle_load_errors(bad)
    assert any("strictly before" in error for error in errors)
    # Equal timestamps are equally invalid (the window must be non-empty).
    bad["expires_at"] = bad["issued_at"]
    errors = bundle_load_errors(bad)
    assert any("strictly before" in error for error in errors)


def test_empty_audience_rejected(schema: dict, example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["audience"] = []
    errors = validate(bad, schema)
    assert any("audience" in error and "fewer than 1" in error for error in errors)


def test_audience_identifiers_require_a_known_scheme(schema: dict, example: dict) -> None:
    for identifier in ("core-ai4sale", "user:somebody", "team:", "team:bad name", "*"):
        bad = copy.deepcopy(example)
        bad["audience"] = [identifier]
        errors = validate(bad, schema)
        assert any("audience" in error and "pattern" in error for error in errors), identifier


def test_namespace_rule_with_regex_chars_rejected(schema: dict, example: dict) -> None:
    for rule in ("github.(create|delete)_issue", "github.[ct]ool", "github.create_*",
                 "*.read_file", "*.*", "github tool", "github"):
        bad = copy.deepcopy(example)
        bad["allowed_upstream_namespaces"] = [rule]
        errors = validate(bad, schema)
        assert any("allowed_upstream_namespaces" in error and "pattern" in error
                   for error in errors), rule


def test_unknown_top_level_key_rejected(schema: dict, example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["trust_everything"] = True  # no such switch exists in this format
    errors = validate(bad, schema)
    assert any("additional property 'trust_everything'" in error for error in errors)
    bad = copy.deepcopy(example)
    bad["revocation"]["url"] = "http://example.com/crl"  # only crl_path / registry_endpoint
    errors = validate(bad, schema)
    assert any("additional property 'url'" in error for error in errors)


def test_timestamp_format_is_strict(schema: dict, example: dict) -> None:
    for stamp in ("2026-06-01", "2026-06-01T00:00:00+02:00", "2026-06-01 00:00:00Z", "now"):
        bad = copy.deepcopy(example)
        bad["issued_at"] = stamp
        errors = validate(bad, schema)
        assert any("issued_at" in error and "pattern" in error for error in errors), stamp


def test_signature_key_id_must_match_issuer(example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["signature"]["key_id"] = "some-other-key"
    errors = bundle_load_errors(bad)
    assert any("issuer.key_id" in error for error in errors)


def test_rule_outside_namespace_ceiling_is_a_load_error(example: dict) -> None:
    # Decision 10: a profile may never reference an upstream outside the
    # bundle's allowed_upstream_namespaces (-32018 bundle_audience_mismatch).
    bad = copy.deepcopy(example)
    bad["profiles"]["dev-default"]["visible"] = ["github.*", "payments.charge_card"]
    errors = bundle_load_errors(bad)
    assert any("outside" in error and "payments.charge_card" in error for error in errors)
    # Narrowing the ceiling below what profiles use is the same violation.
    bad = copy.deepcopy(example)
    bad["allowed_upstream_namespaces"] = ["github.*"]
    errors = bundle_load_errors(bad)
    assert any("filesystem" in error and "outside" in error for error in errors)


def test_registry_endpoint_must_be_https(schema: dict, example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["revocation"]["registry_endpoint"] = "http://unlimited.ai4.sale/crl"
    errors = validate(bad, schema)
    assert any("registry_endpoint" in error and "pattern" in error for error in errors)
    good = copy.deepcopy(example)
    good["revocation"]["registry_endpoint"] = "https://unlimited.ai4.sale/api/profile-bundles/crl"
    assert validate(good, schema) == []


def test_e09_profile_semantics_still_hold_inside_a_bundle(example: dict) -> None:
    bad = copy.deepcopy(example)
    bad["profiles"]["dev-default"]["extends"] = "dev-default"
    assert any("cycle" in error for error in bundle_load_errors(bad))
    bad = copy.deepcopy(example)
    bad["profiles"]["reviewer"]["extends"] = "nonexistent"
    assert any("unknown profile" in error for error in bundle_load_errors(bad))
    bad = copy.deepcopy(example)
    bad["profiles"]["ci-minimal"]["callable"] = ["filesystem.read_file"]
    assert any("not covered by visible" in error for error in bundle_load_errors(bad))
    bad = copy.deepcopy(example)
    bad["default_profile"] = "ghost"
    assert any("default_profile" in error for error in bundle_load_errors(bad))
