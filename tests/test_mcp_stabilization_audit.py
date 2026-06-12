"""E22: MCP profile stack stabilization audit (consistency map).

Proves the contract of docs/mcp-stabilization-audit.md against
``scripts/run-mcp-profile-stack-stabilization-audit.py``:

- the audit runs clean over the CURRENT tree: zero problem-severity
  findings, exit 0 (warnings allowed), all six dimensions present and in
  order, every dimension actually ran checks;
- the JSON report validates against
  ``schemas/mcp-stabilization-audit-report.schema.json`` (the repo's
  minimal self-contained validator pattern) and the shipped generated
  example validates and stays in sync;
- injected inconsistencies in a temp copy of the tree are detected as
  problems: a duplicated reserved refusal code, a renamed code in a docs
  table, a corrupted schema example, a removed boundary phrase;
- the stabilization fixes this epic shipped stay fixed: the inspector
  names the whole reserved code range -32001..-32019, knows the E12B cache
  event rows, and exempts every documented ``*_sha256`` audit field from
  the redaction self-check;
- leak-grep: every string in the report and in both CLI output modes is
  re-scanned with the audit writer's own ``looks_secret``/path heuristics;
- ``--out`` writes exactly the JSON and text reports and nothing else;
  without ``--out`` the audit writes nothing at all.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

from unlimited_skills.mcp import audit_inspector
from unlimited_skills.mcp.audit import _PATH_PATTERN as PATH_PATTERN
from unlimited_skills.mcp.audit import looks_secret

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run-mcp-profile-stack-stabilization-audit.py"
SCHEMA_PATH = ROOT / "schemas" / "mcp-stabilization-audit-report.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "mcp" / "stabilization-audit-report.example.json"
DOC_PATH = ROOT / "docs" / "mcp-stabilization-audit.md"

DIMENSION_NAMES = (
    "refusal_codes",
    "cli_taxonomy",
    "schemas",
    "docs_map",
    "audit_fields",
    "security_boundaries",
)


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("mcp_stabilization_audit", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit():
    return _load_audit_module()


@pytest.fixture(scope="module")
def report(audit) -> dict:
    return audit.run_audit(fixture_mode=True)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The repo's minimal self-contained JSON Schema validator (same stance as
# tests/test_mcp_operator_acceptance.py: no jsonschema dependency).

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


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
        expected = schema["type"]
        python_type = _TYPES[expected]
        if expected in ("number", "integer") and isinstance(value, bool):
            return errors + [f"{path}: expected {expected}, got bool"]
        if not isinstance(value, python_type):
            return errors + [f"{path}: expected {expected}, got {type(value).__name__}"]
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
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(validate(item, schema["items"], f"{path}[{index}]", root))
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
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


def _copy_tree(destination: Path, *parts: str) -> Path:
    """Copy selected repo parts into a temp root for injection tests."""
    for part in parts:
        source = ROOT / part
        if source.is_dir():
            shutil.copytree(
                source,
                destination / part,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        else:
            (destination / part).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination / part)
    return destination


def _findings(report_or_findings, dimension: str | None = None) -> list[dict]:
    if isinstance(report_or_findings, dict):
        for entry in report_or_findings["dimensions"]:
            if entry["name"] == dimension:
                return entry["findings"]
        raise AssertionError(f"dimension {dimension!r} missing")
    return report_or_findings


# ---------------------------------------------------------------------------
# The audit runs clean on the current tree (THE stabilization statement).


def test_current_tree_has_zero_problems(report: dict) -> None:
    assert report["summary"]["problem"] == 0, [
        finding
        for dimension in report["dimensions"]
        for finding in dimension["findings"]
        if finding["severity"] == "problem"
    ]
    assert report["summary"]["ok"] is True
    assert report["exit_code"] == 0


def test_all_six_dimensions_ran(report: dict) -> None:
    assert tuple(entry["name"] for entry in report["dimensions"]) == DIMENSION_NAMES
    for entry in report["dimensions"]:
        assert entry["checks"] >= 1, entry["name"]
        counts = entry["counts"]
        assert counts["problem"] == 0, entry["name"]
        assert sum(counts.values()) == len(entry["findings"]), entry["name"]
    summary = report["summary"]
    assert summary["dimensions"] == 6
    assert summary["checks_total"] == sum(e["checks"] for e in report["dimensions"])
    assert summary["findings_total"] == sum(
        len(e["findings"]) for e in report["dimensions"]
    )


def test_findings_sorted_problems_first(report: dict) -> None:
    rank = {"problem": 0, "warning": 1, "info": 2}
    for entry in report["dimensions"]:
        severities = [rank[f["severity"]] for f in entry["findings"]]
        assert severities == sorted(severities), entry["name"]


# ---------------------------------------------------------------------------
# Schema: the live report and the shipped generated example both validate.


def test_live_report_validates_against_schema(report: dict, schema: dict) -> None:
    assert validate(report, schema) == []


def test_shipped_example_validates_and_stays_in_sync(schema: dict, audit) -> None:
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert validate(example, schema) == []
    assert example["report_type"] == audit.REPORT_TYPE
    assert example["schema_version"] == audit.REPORT_SCHEMA_VERSION
    assert example["mode"] == "fixture"
    assert tuple(entry["name"] for entry in example["dimensions"]) == DIMENSION_NAMES
    assert example["summary"]["problem"] == 0
    assert example["exit_code"] == 0


def test_schema_is_draft_2020_12(schema: dict) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


# ---------------------------------------------------------------------------
# CLI behavior.


def test_cli_json_mode_prints_valid_report(audit, schema: dict, capsys) -> None:
    exit_code = audit.main(["--fixture-mode", "--json"])
    out = capsys.readouterr().out
    assert exit_code == 0
    parsed = json.loads(out)
    assert validate(parsed, schema) == []
    assert parsed["mode"] == "fixture"


def test_cli_out_dir_writes_exactly_the_two_reports(
    audit, tmp_path: Path, capsys
) -> None:
    out_dir = tmp_path / "audit-out"
    exit_code = audit.main(["--fixture-mode", "--out", str(out_dir)])
    capsys.readouterr()
    assert exit_code == 0
    written = sorted(path.name for path in out_dir.iterdir())
    assert written == [
        "stabilization-audit-report.json",
        "stabilization-audit-report.txt",
    ]
    parsed = json.loads(
        (out_dir / "stabilization-audit-report.json").read_text(encoding="utf-8")
    )
    assert parsed["summary"]["ok"] is True
    text = (out_dir / "stabilization-audit-report.txt").read_text(encoding="utf-8")
    assert "OK (no problems)" in text


def test_text_mode_renders_summary_line(audit, capsys) -> None:
    exit_code = audit.main(["--fixture-mode"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "MCP profile stack stabilization audit" in out
    assert "OK (no problems)" in out
    for name in DIMENSION_NAMES:
        assert f"[{name}]" in out


# ---------------------------------------------------------------------------
# Injected inconsistencies in a temp tree are detected as problems.


def test_injected_duplicate_refusal_code_is_a_problem(audit, tmp_path: Path) -> None:
    tree = _copy_tree(tmp_path / "dup", "unlimited_skills", "docs")
    profiles = tree / "unlimited_skills" / "mcp" / "profiles.py"
    profiles.write_text(
        profiles.read_text(encoding="utf-8")
        + "\nTOOL_NOT_VISIBLE_COPY = -32012  # injected duplicate\n",
        encoding="utf-8",
    )
    _, findings = audit.audit_refusal_codes(tree)
    duplicates = [
        f for f in findings if f["check"] == "duplicate_code" and f["subject"] == "-32012"
    ]
    assert duplicates and all(f["severity"] == "problem" for f in duplicates)


def test_injected_docs_table_rename_is_a_problem(audit, tmp_path: Path) -> None:
    tree = _copy_tree(tmp_path / "rename", "unlimited_skills", "docs")
    doc = tree / "docs" / "mcp-permissioned-tool-profiles.md"
    text = doc.read_text(encoding="utf-8")
    assert "`tool_not_visible`" in text
    doc.write_text(
        text.replace("`tool_not_visible`", "`tool_invisible_renamed`", 1),
        encoding="utf-8",
    )
    _, findings = audit.audit_refusal_codes(tree)
    drifts = [f for f in findings if f["check"] == "docs_name_drift"]
    assert drifts and all(f["severity"] == "problem" for f in drifts)
    assert any("tool_invisible_renamed" in f["message"] for f in drifts)


def test_injected_corrupt_example_is_a_problem(audit, tmp_path: Path) -> None:
    tree = _copy_tree(tmp_path / "corrupt", "schemas", "examples", "docs")
    example = tree / "examples" / "mcp" / "tool-profile.example.json"
    example.write_text("{ this is not json", encoding="utf-8")
    _, findings = audit.audit_schemas(tree)
    broken = [
        f
        for f in findings
        if f["check"] == "example_valid_json"
        and f["subject"] == "examples/mcp/tool-profile.example.json"
    ]
    assert broken and broken[0]["severity"] == "problem"


def test_injected_example_schema_violation_is_a_problem(audit, tmp_path: Path) -> None:
    tree = _copy_tree(tmp_path / "violate", "schemas", "examples", "docs")
    example = tree / "examples" / "mcp" / "tool-profile.example.json"
    document = json.loads(example.read_text(encoding="utf-8"))
    document["injected_unknown_key"] = True
    example.write_text(json.dumps(document), encoding="utf-8")
    _, findings = audit.audit_schemas(tree)
    failed = [f for f in findings if f["check"] == "example_validates"]
    assert failed and failed[0]["severity"] == "problem"


def test_injected_missing_boundary_phrase_is_a_problem(audit, tmp_path: Path) -> None:
    tree = _copy_tree(tmp_path / "boundary", "unlimited_skills", "docs")
    doc = tree / "docs" / "unlimited-tools.md"
    text = doc.read_text(encoding="utf-8")
    assert "No automatic telemetry" in text
    doc.write_text(text.replace("No automatic telemetry", "telemetry: see notes"), encoding="utf-8")
    _, findings = audit.audit_docs_map(tree)
    failures = [f for f in findings if f["check"] == "boundary_phrases"]
    assert failures and all(f["severity"] == "problem" for f in failures)


def test_injected_network_import_is_a_problem(audit, tmp_path: Path) -> None:
    tree = _copy_tree(tmp_path / "net", "unlimited_skills", "docs")
    module = tree / "unlimited_skills" / "mcp" / "protocol.py"
    module.write_text(
        "import socket  # injected\n" + module.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _, findings = audit.audit_security_boundaries(tree)
    hits = [f for f in findings if f["check"] == "network_imports"]
    assert hits and hits[0]["severity"] == "problem"
    assert "socket" in hits[0]["message"]


# ---------------------------------------------------------------------------
# The stabilization fixes this epic shipped stay fixed (regression pins).


def test_inspector_names_the_whole_reserved_range() -> None:
    for code in range(-32019, -32000):
        assert code in audit_inspector.REFUSAL_CODES, code
        name, meaning = audit_inspector.REFUSAL_CODES[code]
        assert name and meaning
    assert audit_inspector.code_name(-32017) == "BUNDLE_REVOKED"
    assert audit_inspector.code_name(-32099) == "unknown"


def test_inspector_knows_the_cache_event_rows() -> None:
    assert "cache_loaded" in audit_inspector.EVENT_TOOLS
    assert "cache_refresh" in audit_inspector.EVENT_TOOLS
    assert audit_inspector.PROFILE_EVENT_TOOL in audit_inspector.EVENT_TOOLS
    rows = [
        ("mcp-audit.jsonl", 1, {"ts": 1.0, "tool": "cache_loaded", "ok": True}),
        ("mcp-audit.jsonl", 2, {"ts": 2.0, "tool": "tools_call", "upstream": "fake", "ok": True}),
    ]
    summary = audit_inspector.summarize(rows)
    assert summary["total_calls"] == 1
    assert "cache_loaded" not in summary["per_tool"]


def test_inspector_classifies_bundle_refusal_error_text() -> None:
    row = {
        "ok": False,
        "error": "Signed profile bundle refused (bundle_revoked): withdrawn",
    }
    assert audit_inspector.refusal_code_of(row) == -32017


def test_inspector_exempts_documented_hash_fields() -> None:
    for field in ("profile_sha256", "bundle_sha256", "local_profile_sha256", "cache_sha256"):
        assert field in audit_inspector.KNOWN_HASH_KEYS, field
    rows = [
        (
            "mcp-audit.jsonl",
            1,
            {
                "ts": 1.0,
                "tool": "profile_loaded",
                "ok": True,
                "bundle_sha256": "a" * 64,
                "cache_sha256": "b" * 64,
            },
        )
    ]
    check = audit_inspector.redaction_self_check(rows)
    assert check["status"] == "PASS", check


# ---------------------------------------------------------------------------
# Leak-grep: report and CLI output stay free of secrets and local paths.


def test_report_strings_pass_the_writer_leak_heuristics(report: dict) -> None:
    for text in _iter_strings(report):
        assert not looks_secret(text), text
        assert not PATH_PATTERN.search(text), text


def test_cli_output_passes_the_writer_leak_heuristics(audit, capsys) -> None:
    audit.main(["--fixture-mode", "--json"])
    json_out = capsys.readouterr().out
    audit.main(["--fixture-mode"])
    text_out = capsys.readouterr().out
    for line in (json_out + "\n" + text_out).splitlines():
        assert not looks_secret(line), line
        assert not PATH_PATTERN.search(line), line


# ---------------------------------------------------------------------------
# Docs stay in sync with the implementation.


def test_doc_names_every_dimension_and_artifact() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    for name in DIMENSION_NAMES:
        assert f"`{name}`" in text, name
    assert "run-mcp-profile-stack-stabilization-audit.py" in text
    assert "mcp-stabilization-audit-report.schema.json" in text
    assert "stabilization-audit-report.example.json" in text
    assert "release-gate candidate" in text
