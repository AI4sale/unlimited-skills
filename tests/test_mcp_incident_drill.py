"""E18: signed-bundle incident drill harness and recovery plan.

Proves the contract of docs/mcp-incident-runbook.md against
``scripts/run-mcp-bundle-incident-drill.py``:

- the fixture-mode drill runs every documented incident scenario, observes
  the expected fail-closed refusal code from the REAL E14 verification, and
  recovers through the documented operator steps (exit 0 only when ALL
  scenarios refuse correctly AND recover);
- the JSON report validates against
  ``schemas/mcp-incident-drill-report.schema.json`` (the repo's minimal
  self-contained validator pattern -- no jsonschema dependency) and the
  shipped generated example validates too and stays in sync;
- the scenario -> refusal-code mapping is exactly the E13/E14 reservation
  (-32015 tampering and rollback trigger, -32016 expiry, -32017 revocation
  and CRL outage, -32018 audience, -32019 unknown/expired key and store
  corruption);
- audit tie-in (E11): the inspector report over the drill's own audit log
  carries every expected refusal code and a passing redaction self-check;
- leak-grep: every string in the drill report is re-scanned with the audit
  writer's own ``looks_secret``/path heuristics -- no key material, no
  signature values, no hashes, no local paths;
- containment: with an explicit ``base_dir`` the drill never creates its
  own temp directory and never touches the repo's managed trust store or
  default audit log locations;
- CLI: ``--scenario`` filtering, ``--json`` output, ``--out`` files,
  unknown scenario exit 2;
- the runbook documents every scenario and every refusal code the drill
  exercises (docs and harness cannot drift apart silently).
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from unlimited_skills.mcp.audit import _PATH_PATTERN as PATH_PATTERN
from unlimited_skills.mcp.audit import looks_secret

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run-mcp-bundle-incident-drill.py"
SCHEMA_PATH = ROOT / "schemas" / "mcp-incident-drill-report.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "mcp" / "incident-drill-report.example.json"
RUNBOOK_PATH = ROOT / "docs" / "mcp-incident-runbook.md"

EXPECTED_CODES = {
    "bad_signature": -32015,
    "unknown_key": -32019,
    "expired_key": -32019,
    "expired_bundle": -32016,
    "revoked_bundle": -32017,
    "crl_outage": -32017,
    "wrong_audience": -32018,
    "operator_rollback": -32015,
    "trust_store_recovery": -32019,
}


def _load_drill_module():
    spec = importlib.util.spec_from_file_location("mcp_incident_drill", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def drill():
    return _load_drill_module()


@pytest.fixture(scope="module")
def report(drill, tmp_path_factory: pytest.TempPathFactory) -> dict:
    base = tmp_path_factory.mktemp("incident-drill")
    return drill.run_drill(base_dir=base)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The repo's minimal self-contained JSON Schema validator (same stance as
# tests/test_mcp_audit_replay.py: no jsonschema dependency), with $ref.

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
        for key, item in value.items():
            if key in properties:
                errors.extend(validate(item, properties[key], f"{path}.{key}", root))
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
                errors.extend(validate(item, schema["items"], f"{path}[{index}]", root))
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


# ---------------------------------------------------------------------------
# Full drill: every scenario refuses with the expected code AND recovers.


def test_drill_exits_zero_with_all_scenarios_ok(report: dict) -> None:
    assert report["exit_code"] == 0
    assert report["mode"] == "fixture"
    summary = report["summary"]
    assert summary["scenarios_total"] == len(EXPECTED_CODES)
    assert summary["refusals_ok"] == len(EXPECTED_CODES)
    assert summary["recoveries_ok"] == len(EXPECTED_CODES)
    assert summary["all_ok"] is True


def test_every_scenario_present_with_documented_code(report: dict) -> None:
    by_name = {entry["scenario"]: entry for entry in report["scenarios"]}
    assert set(by_name) == set(EXPECTED_CODES)
    for name, expected_code in EXPECTED_CODES.items():
        entry = by_name[name]
        assert entry["expected_code"] == expected_code, name
        assert entry["observed_code"] == expected_code, name
        assert entry["refusal_ok"] is True, name
        assert entry["fail_closed"] is True, name
        assert entry["recovered_ok"] is True, name
        assert entry["recovery_steps"], name
        assert entry["duration_ms"] >= 0, name


def test_scenario_order_is_deterministic(drill, report: dict) -> None:
    assert [entry["scenario"] for entry in report["scenarios"]] == list(drill.SCENARIOS)


# ---------------------------------------------------------------------------
# Audit tie-in (E11): the inspector saw the refusals, redaction passed.


def test_audit_section_carries_expected_codes_and_passes_redaction(report: dict) -> None:
    audit = report["audit"]
    assert audit["expected_codes_present"] is True
    assert audit["redaction_self_check"] == "PASS"
    assert set(audit["refusal_codes_observed"]) == set(EXPECTED_CODES.values())
    assert audit["refusal_rows"] == len(EXPECTED_CODES)
    assert audit["rows_total"] > audit["refusal_rows"], "at least one ok row exists"


# ---------------------------------------------------------------------------
# Schema: the live report and the shipped example both validate.


def test_report_validates_against_schema(report: dict, schema: dict) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert validate(report, schema) == []


def test_shipped_example_validates_and_stays_in_sync(schema: dict) -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert validate(example, schema) == []
    assert {entry["scenario"] for entry in example["scenarios"]} == set(EXPECTED_CODES)
    assert example["exit_code"] == 0
    assert example["summary"]["all_ok"] is True
    for entry in example["scenarios"]:
        assert entry["expected_code"] == EXPECTED_CODES[entry["scenario"]]


# ---------------------------------------------------------------------------
# Leak-grep: the report never carries secrets, key material, hashes, or
# local paths (the audit writer's own heuristics, reused verbatim).


def test_report_has_no_secret_looking_values_or_local_paths(report: dict) -> None:
    for text in _iter_strings(report):
        assert not looks_secret(text), f"secret-looking string in drill report: {text[:32]}..."
        assert not PATH_PATTERN.search(text), f"local path in drill report: {text[:32]}..."


def test_example_has_no_secret_looking_values_or_local_paths() -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    for text in _iter_strings(example):
        assert not looks_secret(text)
        assert not PATH_PATTERN.search(text)


# ---------------------------------------------------------------------------
# Containment: an explicit base_dir means no temp dir of its own and no
# writes anywhere near the real library root, store, or audit log.


def test_drill_stays_inside_its_base_dir(
    drill, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("the drill must not create temp dirs when base_dir is given")

    monkeypatch.setattr(drill.tempfile, "mkdtemp", forbidden)
    repo_store = ROOT / ".unlimited-skills-trust"
    repo_audit = ROOT / ".learning" / "mcp-audit.jsonl"
    store_before = repo_store.exists()
    audit_before = repo_audit.exists()
    base = tmp_path / "drill"
    result = drill.run_drill(["wrong_audience", "crl_outage"], base_dir=base)
    assert result["exit_code"] == 0
    assert [entry["scenario"] for entry in result["scenarios"]] == ["wrong_audience", "crl_outage"]
    assert (base / "audit" / "mcp-audit.jsonl").is_file()
    assert (base / "wrong_audience" / "trust-store" / "trusted-keys.json").is_file()
    assert repo_store.exists() == store_before
    assert repo_audit.exists() == audit_before


def test_unknown_scenario_is_a_value_error(drill, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown scenario"):
        drill.run_drill(["no_such_incident"], base_dir=tmp_path)


# ---------------------------------------------------------------------------
# CLI surface.


def test_cli_json_single_scenario(drill, capsys: pytest.CaptureFixture[str]) -> None:
    code = drill.main(["--json", "--scenario", "wrong_audience"])
    out = capsys.readouterr().out
    assert code == 0
    document = json.loads(out)
    assert document["report_type"] == "mcp-incident-drill-report"
    assert [entry["scenario"] for entry in document["scenarios"]] == ["wrong_audience"]
    assert document["summary"]["all_ok"] is True


def test_cli_out_writes_json_and_text(
    drill, tmp_path: Path, capsys: pytest.CaptureFixture[str], schema: dict
) -> None:
    out_dir = tmp_path / "out"
    code = drill.main(["--scenario", "expired_bundle", "--out", str(out_dir)])
    captured = capsys.readouterr().out
    assert code == 0
    document = json.loads((out_dir / "incident-drill-report.json").read_text(encoding="utf-8"))
    assert validate(document, schema) == []
    text = (out_dir / "incident-drill-report.txt").read_text(encoding="utf-8")
    assert "[expired_bundle]" in text and "ALL OK" in text
    assert "[expired_bundle]" in captured, "text mode prints the human report"


def test_cli_unknown_scenario_exits_two(drill, capsys: pytest.CaptureFixture[str]) -> None:
    assert drill.main(["--scenario", "nonsense"]) == 2
    assert "unknown scenario" in capsys.readouterr().err


def test_text_report_lists_every_scenario(drill, report: dict) -> None:
    text = drill.format_drill_report(report)
    for name in EXPECTED_CODES:
        assert f"[{name}]" in text
    assert "ALL OK" in text and "redaction self-check: PASS" in text


# ---------------------------------------------------------------------------
# Docs sync: the runbook documents every scenario and refusal code.


def test_runbook_documents_every_scenario_and_code(drill) -> None:
    text = RUNBOOK_PATH.read_text(encoding="utf-8")
    for name in EXPECTED_CODES:
        assert name in text, f"runbook missing scenario {name}"
    for code in sorted(set(EXPECTED_CODES.values())):
        assert str(code) in text, f"runbook missing refusal code {code}"
    assert "run-mcp-bundle-incident-drill.py" in text
    assert "trust doctor" in text and "trust import" in text and "trust revoke" in text
