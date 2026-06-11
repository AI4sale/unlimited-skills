"""E12: fast smoke of the MCP performance benchmark machinery.

Runs ``scripts/run-mcp-performance-benchmarks.py`` once at a tiny fixture
size (8 tools, K=2) and asserts that:

- the runner exits 0 in fixture mode and prints the JSON report;
- the JSON validates against ``schemas/mcp-perf-report.schema.json`` via a
  minimal self-contained validator (the
  ``tests/test_mcp_upstream_config_schema.py`` pattern, extended with
  ``$ref``/``$defs`` resolution and union types);
- the report contains every benchmark section with raw samples;
- neither the JSON nor the Markdown contains secret-shaped values or local
  absolute paths (reusing the ``looks_secret``/path patterns from audit.py);
- the context-bytes section is internally consistent (the full all-schemas
  dump dwarfs the gateway listing, search, and single-schema payloads);
- spawn vs reuse behaves as documented (first call is the expensive one).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from unlimited_skills.mcp.audit import _PATH_PATTERN, looks_secret

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "mcp-perf-report.schema.json"

SMOKE_SIZE = 8
SMOKE_REPEATS = 2

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _check_type(value: object, expected, path: str) -> list[str]:
    if isinstance(expected, list):
        for candidate in expected:
            if not _check_type(value, candidate, path):
                return []
        return [f"{path}: expected one of {expected}, got {type(value).__name__}"]
    python_type = _TYPES[expected]
    if expected in ("number", "integer") and isinstance(value, bool):
        return [f"{path}: expected {expected}, got bool"]
    if not isinstance(value, python_type):
        return [f"{path}: expected {expected}, got {type(value).__name__}"]
    if expected == "integer" and isinstance(value, float) and not float(value).is_integer():
        return [f"{path}: expected integer, got non-integral number"]
    return []


def validate(value: object, schema: dict, root: dict, path: str = "$") -> list[str]:
    """Return a list of violation strings (empty = valid)."""
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/"), f"unsupported $ref: {ref}"
        target: object = root
        for part in ref[2:].split("/"):
            target = target[part]  # type: ignore[index]
        return validate(value, target, root, path)  # type: ignore[arg-type]
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
                errors.extend(validate(item, properties[key], root, f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: additional property {key!r} not allowed")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(validate(item, schema["items"], root, f"{path}[{index}]"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "pattern" in schema:
            import re

            if not re.search(schema["pattern"], value):
                errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    return errors


@pytest.fixture(scope="module")
def perf_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, str, str]:
    out_dir = tmp_path_factory.mktemp("perf-out")
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run-mcp-performance-benchmarks.py",
            "--fixture-mode",
            "--json",
            "--sizes",
            str(SMOKE_SIZE),
            "--repeats",
            str(SMOKE_REPEATS),
            "--warmup",
            "1",
            "--out",
            str(out_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    json_text = (out_dir / "mcp-perf-report.json").read_text(encoding="utf-8")
    md_text = (out_dir / "mcp-perf-report.md").read_text(encoding="utf-8")
    return report, json_text, md_text


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_fixture_mode_flag_is_required() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run-mcp-performance-benchmarks.py", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode != 0
    assert "--fixture-mode" in completed.stderr


def test_schema_is_valid_json_draft_2020_12(schema: dict) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    size_schema = schema["$defs"]["sizeReport"]
    assert size_schema["additionalProperties"] is False
    stat_schema = schema["$defs"]["statMs"]
    assert stat_schema["properties"]["unit"]["const"] == "ms"
    assert set(stat_schema["required"]) == {"unit", "samples", "min", "median", "mean"}


def test_report_validates_against_schema(perf_run, schema: dict) -> None:
    report, json_text, _ = perf_run
    assert validate(report, schema, schema) == []
    # The written JSON file is the same report the runner printed to stdout.
    assert validate(json.loads(json_text), schema, schema) == []


def test_validator_rejects_broken_reports(perf_run, schema: dict) -> None:
    report, _, _ = perf_run
    broken = json.loads(json.dumps(report))
    del broken["sizes"][0]["cold_start"]
    assert any("cold_start" in error for error in validate(broken, schema, schema))
    broken = json.loads(json.dumps(report))
    broken["sizes"][0]["warm"]["first_schema"]["unit"] = "s"
    assert any("const" in error for error in validate(broken, schema, schema))
    broken = json.loads(json.dumps(report))
    broken["fixture_mode"] = False
    assert validate(broken, schema, schema)


def test_report_contains_all_sections_with_raw_samples(perf_run) -> None:
    report, _, _ = perf_run
    assert report["status"] == "passed"
    assert report["fixture_mode"] is True
    assert report["repeats"] == SMOKE_REPEATS
    assert len(report["sizes"]) == 1
    size = report["sizes"][0]
    assert size["tools_total"] == SMOKE_SIZE
    for section in (
        "cold_start",
        "warm",
        "search",
        "indexing",
        "audit_overhead",
        "context_bytes",
        "memory",
    ):
        assert section in size, f"missing benchmark section: {section}"
    assert len(size["cold_start"]["total"]["samples"]) == SMOKE_REPEATS
    assert len(size["warm"]["first_schema"]["samples"]) == SMOKE_REPEATS
    assert len(size["warm"]["reuse_schema"]["samples"]) >= SMOKE_REPEATS
    assert len(size["search"]["indexed_no_spawn"]["samples"]) >= SMOKE_REPEATS
    assert len(size["indexing"]["tools_list_and_index"]["samples"]) == SMOKE_REPEATS
    assert len(size["audit_overhead"]["audit_standard"]["samples"]) == SMOKE_REPEATS


def test_spawn_vs_reuse_first_call_is_the_expensive_one(perf_run) -> None:
    report, _, _ = perf_run
    warm = report["sizes"][0]["warm"]
    # The first tools_schema pays a full subprocess spawn + handshake + index;
    # a reused call is one stdio round-trip. Medians keep this robust.
    assert warm["first_schema"]["median"] > warm["reuse_schema"]["median"]
    assert warm["spawn_vs_reuse_ratio"] > 1.0


def test_context_bytes_section_is_consistent(perf_run) -> None:
    report, _, _ = perf_run
    context = report["sizes"][0]["context_bytes"]
    assert context["full_all_schemas_dump"] > context["tools_search_response"]
    assert context["full_all_schemas_dump"] > context["gateway_tools_list"]
    assert context["full_all_schemas_dump"] > context["tools_schema_response"]
    assert 0 < context["standing_cost_share"] < 1
    assert 0 < context["search_share"] < 1
    assert 0 < context["schema_share"] < 1


def _iter_strings(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, str):
        yield value


def test_no_secrets_and_no_local_absolute_paths(perf_run) -> None:
    report, json_text, md_text = perf_run
    for text in _iter_strings(report):
        assert not looks_secret(text), f"secret-shaped value in report: {text[:40]}..."
        assert not _PATH_PATTERN.search(text), f"local path in report: {text[:80]}"
    assert not _PATH_PATTERN.search(md_text), "local path leaked into the Markdown report"
    for line in md_text.splitlines():
        assert not looks_secret(line), f"secret-shaped Markdown line: {line[:60]}"
    # The temp fixture root must not leak in any form.
    assert "uls-mcp-perf" not in json_text
    assert "uls-mcp-perf" not in md_text


def test_memory_section_is_best_effort_and_clean(perf_run) -> None:
    report, _, _ = perf_run
    memory = report["sizes"][0]["memory"]
    if memory["available"]:
        assert isinstance(memory["gateway_peak_rss_bytes"], int)
        assert memory["gateway_peak_rss_bytes"] > 0
        assert memory["source"] in ("GetProcessMemoryInfo", "proc-status")
    else:
        assert memory["gateway_peak_rss_bytes"] is None
        assert memory["source"] == "unavailable"
