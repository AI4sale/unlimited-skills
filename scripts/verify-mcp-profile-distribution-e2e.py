"""E26: thin verifier over the distribution fixture E2E JSON report.

Checks ONE report produced by ``scripts/run-mcp-profile-distribution-fixture-e2e.py``:

1. the document is valid JSON and validates against
   ``schemas/mcp-distribution-e2e-report.schema.json`` (the repo's minimal
   self-contained validator -- no jsonschema dependency);
2. the run succeeded: ``exit_code`` 0, ``summary.all_ok`` true, every step
   ``ok``, every workflow step present (a prefix run is a FAILURE here --
   the verifier gates the FULL flow);
3. ABT coverage is non-empty, every id is well-formed, and the top-level
   ``abt_coverage`` equals the union of the per-step ``abt`` lists;
4. no forbidden field per the E24 decision-20 denylist (encoded LOCALLY
   below -- the private contract is never read) appears as a property name
   at any depth of the report;
5. leak-grep: every string in the report passes the audit writer's own
   ``looks_secret`` and local-path heuristics (no key material, no full
   hashes, no local paths).

Exit 0 when every check passes, 1 with the findings listed otherwise, 2 for
usage errors. Read-only and offline: the verifier reads the report and the
schema, writes nothing, and makes no network or hosted calls.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unlimited_skills.mcp.audit import _PATH_PATTERN, looks_secret  # noqa: E402

SCHEMA_PATH = ROOT / "schemas" / "mcp-distribution-e2e-report.schema.json"
EXPECTED_REPORT_TYPE = "mcp-distribution-e2e-report"
EXPECTED_STEPS = 23

# The E24 decision-20 forbidden-field denylist, encoded locally (same list
# as the harness; no leakage of anything beyond the public property names).
FORBIDDEN_FIELDS = frozenset(
    {
        "prompt",
        "prompts",
        "task_text",
        "query",
        "messages",
        "tool_arguments",
        "tool_args",
        "tool_input",
        "tool_inputs",
        "tool_output",
        "tool_outputs",
        "tool_results",
        "tool_calls",
        "profile_rules",
        "profile_body",
        "bundle_body",
        "skill_body",
        "skill_bodies",
        "audit_log",
        "usage",
        "telemetry",
        "activation_history",
        "private_key",
        "private_keys",
        "signing_key",
        "key_material",
        "license_token",
        "registration_token",
        "device_proof",
        "join_code",
        "team_token",
        "local_path",
        "local_paths",
        "env",
        "env_values",
        "secret",
        "secrets",
    }
)

ABT_ID_RE = re.compile(r"^ABT-[0-9]{2}[a-z]$")

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value: object, expected: str) -> bool:
    python_type = _TYPES.get(expected)
    if python_type is None:
        return True
    if expected in ("number", "integer") and isinstance(value, bool):
        return False
    return isinstance(value, python_type)


def validate_instance(
    value: object, schema: object, path: str = "$", root: dict | None = None
) -> list[str]:
    """Minimal self-contained JSON Schema check (the repo's test stance)."""
    if not isinstance(schema, dict):
        return []
    if root is None:
        root = schema
    if "$ref" in schema:
        target: object = root
        for part in str(schema["$ref"]).lstrip("#/").split("/"):
            if not isinstance(target, dict) or part not in target:
                return [f"{path}: unresolvable $ref {schema['$ref']!r}"]
            target = target[part]
        return validate_instance(value, target, path, root)
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _type_ok(value, expected_type):
        return errors + [f"{path}: expected {expected_type}, got {type(value).__name__}"]
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(validate_instance(item, properties[key], f"{path}.{key}", root))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: additional property {key!r} not allowed")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(
                    validate_instance(item, schema["items"], f"{path}[{index}]", root)
                )
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    return errors


def _forbidden_keys(value: object, at: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_FIELDS:
                found.append(f"{at}.{key}")
            found.extend(_forbidden_keys(item, f"{at}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_forbidden_keys(item, f"{at}[{index}]"))
    return found


def _iter_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


def verify_report_document(report: object, schema: dict) -> list[str]:
    """Every finding for one parsed report document (empty = verified)."""
    findings: list[str] = []
    if not isinstance(report, dict):
        return ["report is not a JSON object"]
    if report.get("report_type") != EXPECTED_REPORT_TYPE:
        findings.append(f"report_type is not {EXPECTED_REPORT_TYPE!r}")
    findings.extend(validate_instance(report, schema))
    if findings:
        return findings  # shape problems make the content checks misleading
    if report["exit_code"] != 0:
        findings.append(f"exit_code is {report['exit_code']}, expected 0")
    summary = report["summary"]
    if summary["all_ok"] is not True:
        findings.append("summary.all_ok is not true")
    steps = report["steps"]
    if len(steps) != EXPECTED_STEPS or summary["steps_selected"] != EXPECTED_STEPS:
        findings.append(
            f"the verifier gates the FULL workflow: expected {EXPECTED_STEPS} "
            f"steps, got {len(steps)} (selected {summary['steps_selected']})"
        )
    for entry in steps:
        if entry["ok"] is not True:
            findings.append(f"step {entry['name']} is not ok")
    coverage = report["abt_coverage"]
    if not coverage:
        findings.append("abt_coverage is empty (the abuse battery proved nothing)")
    for abt_id in coverage:
        if not ABT_ID_RE.match(abt_id):
            findings.append(f"malformed ABT id {abt_id!r}")
    claimed = sorted({abt_id for entry in steps for abt_id in entry["abt"]})
    if claimed != sorted(coverage):
        findings.append("abt_coverage does not equal the union of per-step abt lists")
    if summary["abt_claimed"] != len(coverage):
        findings.append("summary.abt_claimed does not match abt_coverage")
    for location in _forbidden_keys(report):
        findings.append(f"forbidden field (E24 decision-20 denylist) at {location}")
    for text in _iter_strings(report):
        if looks_secret(text):
            findings.append(f"secret-shaped string in the report: {text[:32]}...")
        if _PATH_PATTERN.search(text):
            findings.append(f"local path in the report: {text[:32]}...")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Thin read-only verifier over a distribution fixture E2E JSON "
            "report: schema validity, all 23 steps ok, non-empty ABT "
            "coverage consistent with the per-step claims, no forbidden "
            "fields, no secret-shaped strings or local paths. Offline; "
            "writes nothing."
        )
    )
    parser.add_argument("report", help="Path to distribution-e2e-report.json.")
    parser.add_argument("--json", action="store_true", help="Print the findings as JSON.")
    args = parser.parse_args(argv)
    report_path = Path(args.report)
    try:
        raw = report_path.read_text(encoding="utf-8")
    except OSError:
        print(f"report file {report_path.name} is missing or unreadable", file=sys.stderr)
        return 2
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"report file is not valid JSON (line {exc.lineno})", file=sys.stderr)
        return 2
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    findings = verify_report_document(report, schema)
    if args.json:
        print(
            json.dumps(
                {"verified": not findings, "findings": findings, "checked": report_path.name},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    elif findings:
        for finding in findings:
            print(f"FAIL: {finding}")
    else:
        print(
            f"verified: {report_path.name} -- all {EXPECTED_STEPS} steps ok, "
            "ABT coverage consistent, no forbidden fields, no leaks"
        )
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
