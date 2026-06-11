"""E11 MCP audit inspector: reports over the redacted audit JSONL log.

Fixture audit files are written through the real writer
(:class:`unlimited_skills.mcp.audit.AuditLog`) so the on-disk format is the
real one. Rows that only the not-yet-merged E10 gateway produces (``profile``
fields, ``profile_loaded`` events) and the deliberately-broken rows for the
redaction self-check are appended manually, bypassing ``redact()``.

The JSON report is validated against ``schemas/mcp-audit-report.schema.json``
with a self-contained minimal validator (same pattern as
``tests/test_mcp_upstream_config_schema.py``, extended with the keywords this
schema uses: type unions, additionalProperties-as-schema, and ``$ref`` into
``$defs``).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from unlimited_skills.cli import main
from unlimited_skills.mcp import audit_inspector as inspector
from unlimited_skills.mcp.audit import AuditLog

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "mcp-audit-report.schema.json"

SECRET_BEARER = "Bearer hunter2-very-secret-token-value"
SECRET_PATH = "boom while reading C:\\Users\\tedja\\private\\notes.txt"
PROFILE_SHA = hashlib.sha256(b"profile-file-bytes").hexdigest()

# ---------------------------------------------------------------------------
# Minimal JSON Schema validator (draft 2020-12 subset used by the report
# schema): type (incl. unions), const, enum, required, properties,
# additionalProperties (false or schema), items, pattern, minLength,
# minimum, maximum, uniqueItems, maxItems, $ref -> #/$defs/*.
# ---------------------------------------------------------------------------

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
    if expected in ("number", "integer") and isinstance(value, bool):
        return False
    if not isinstance(value, _TYPES[expected]):
        return False
    if expected == "integer" and isinstance(value, float) and not float(value).is_integer():
        return False
    return True


def validate(value: object, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    """Return a list of violation strings (empty = valid)."""
    root = root if root is not None else schema
    if "$ref" in schema:
        target: object = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]  # type: ignore[index]
        return validate(value, target, root, path)  # type: ignore[arg-type]
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']!r}")
    if "type" in schema:
        expected = schema["type"]
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, item) for item in allowed):
            errors.append(f"{path}: expected {allowed}, got {type(value).__name__}")
            return errors  # further keyword checks would mislead
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties")
        for key, item in value.items():
            if key in properties:
                errors.extend(validate(item, properties[key], root, f"{path}.{key}"))
            elif additional is False:
                errors.append(f"{path}: additional property {key!r} not allowed")
            elif isinstance(additional, dict):
                errors.extend(validate(item, additional, root, f"{path}.{key}"))
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = [json.dumps(item, sort_keys=True) for item in value]
            if len(set(seen)) != len(seen):
                errors.append(f"{path}: items are not unique")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(validate(item, schema["items"], root, f"{path}[{index}]"))
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
    return errors


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def audit_path(tmp_path: Path) -> Path:
    return tmp_path / ".learning" / "mcp-audit.jsonl"


def write_raw_row(path: Path, **fields: object) -> None:
    """Append one row manually (bypassing redact), same JSONL shape."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(fields, ensure_ascii=False, sort_keys=True) + "\n")


def build_basic_log(path: Path) -> AuditLog:
    """10 ok tools_call (durations 1..10), 2 refused (timeouts, duration 100),
    plus 3 ok tools_search rows without an upstream."""
    log = AuditLog(path)
    for duration in range(1, 11):
        log.record("tools_call", "github", float(duration), True, arguments={"tool": "github.create_issue"})
    for _ in range(2):
        log.record(
            "tools_call",
            "flaky",
            100.0,
            False,
            error="UpstreamError: Upstream 'flaky' timed out on 'tools/call'.",
        )
    for _ in range(3):
        log.record("tools_search", "", 2.0, True, arguments={"query": "issues"})
    return log


REFUSAL_ERRORS = {
    -32001: "UpstreamError: Failed to spawn upstream 'gh': OSError",
    -32002: "UpstreamError: Upstream 'gh' timed out on 'tools/call'.",
    -32003: "UpstreamError: Upstream 'gh' returned a malformed (non-JSON) response.",
    -32004: "UpstreamError: Upstream 'gh' error -32602: Invalid params",
    -32005: "UpstreamError: Upstream 'gh' is disabled in the gateway config; enable it to use it.",
    -32006: "UpstreamError: Upstream 'gh' command not allowed: an MCP upstream is never a shell.",
    -32007: "UpstreamError: Upstream 'gh' env_allowlist must be a list of at most 32 variable names.",
    -32008: "UpstreamError: Schema for 'gh.t' is 99999 bytes, over the 65536 byte limit for this upstream; refused, never truncated.",
    -32009: "UpstreamError: Result from 'gh.t' is 99999 bytes, over the 262144 byte limit for this upstream; dropped, never truncated.",
    -32010: "UpstreamError: Upstream 'gh' has trust level 'future-remote-placeholder': all I/O is refused until the OAuth/remote gate opens.",
    -32011: "UpstreamError: Tool 'gh.t' is not visible under profile 'review' or does not exist (tool_not_visible).",
    -32012: "UpstreamError: Tool 'gh.t' is visible under profile 'review' but not callable (tool_not_callable); select a wider profile to call it.",
    -32013: "UpstreamError: No profile selected and the profile file has no default_profile; every call is refused (profile_not_found).",
    -32014: "UpstreamError: The configured profile file is invalid: bad schema; every call is refused (profile_invalid).",
}


# ---------------------------------------------------------------------------
# Summary math
# ---------------------------------------------------------------------------


def test_summary_counts_and_duration_percentiles(tmp_path: Path) -> None:
    path = audit_path(tmp_path)
    build_basic_log(path)
    report = inspector.build_report(path)
    summary = report["summary"]
    assert summary["total_calls"] == 15
    assert summary["ok_calls"] == 13
    assert summary["refused_calls"] == 2
    assert summary["per_tool"]["tools_call"] == {"calls": 12, "ok": 10, "refused": 2}
    assert summary["per_tool"]["tools_search"] == {"calls": 3, "ok": 3, "refused": 0}
    assert summary["per_upstream"]["github"] == {"calls": 10, "ok": 10, "refused": 0}
    assert summary["per_upstream"]["flaky"] == {"calls": 2, "ok": 0, "refused": 2}
    assert summary["per_upstream"][""] == {"calls": 3, "ok": 3, "refused": 0}
    stats = summary["durations_ms"]["tools_call"]
    # durations: 1..10 plus 100, 100 -> n=12, median (6+7)/2, p95 nearest-rank = 12th value
    assert stats == {"count": 12, "min_ms": 1.0, "median_ms": 6.5, "p95_ms": 100.0, "max_ms": 100.0}
    assert summary["first_ts"] is not None and summary["last_ts"] is not None
    assert summary["first_ts"] <= summary["last_ts"]
    assert report["log"]["rows_total"] == 15
    assert report["log"]["malformed_lines"] == 0
    assert report["log"]["rotated_files_read"] == 0


def test_percentile_is_nearest_rank() -> None:
    assert inspector.percentile([], 0.95) is None
    assert inspector.percentile([7.0], 0.95) == 7.0
    assert inspector.percentile(list(range(1, 101)), 0.95) == 95
    assert inspector.percentile([1.0, 2.0], 0.5) == 1.0


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


def test_rotated_files_read_in_chronological_order(tmp_path: Path) -> None:
    path = audit_path(tmp_path)
    log = AuditLog(path, max_bytes=150, max_files=10)
    for index in range(12):
        log.record("tools_call", "github", float(index), True)
    rotated = sorted(path.parent.glob(path.name + ".*"))
    assert rotated, "fixture must actually rotate"
    report = inspector.build_report(path)
    assert report["log"]["rotated_files_read"] == len(rotated)
    assert report["log"]["files_read"][-1] == path.name
    # Oldest generation first: .N .. .1, then the active file.
    indices = [int(name.rsplit(".", 1)[-1]) for name in report["log"]["files_read"][:-1]]
    assert indices == sorted(indices, reverse=True)
    rows, malformed, _ = inspector.load_audit_rows(path)
    assert malformed == 0
    assert [row["duration_ms"] for _, _, row in rows] == [float(i) for i in range(12)]


# ---------------------------------------------------------------------------
# Refusal code naming
# ---------------------------------------------------------------------------


def test_refusal_codes_classified_and_named(tmp_path: Path) -> None:
    path = audit_path(tmp_path)
    log = AuditLog(path)
    for error in REFUSAL_ERRORS.values():
        log.record("tools_call", "gh", 1.0, False, error=error)
    log.record("tools_call", "gh", 1.0, False, error="ToolError: arguments must be an object.")
    write_raw_row(  # a row with an explicit (future) integer code field
        path, ts=9e9, tool="tools_call", upstream="gh", duration_ms=1.0, ok=False, code=-32099
    )
    report = inspector.build_report(path)
    by_code = {entry["code"]: entry for entry in report["refusals"]["by_code"]}
    for code in REFUSAL_ERRORS:
        assert by_code[code]["count"] == 1, code
        assert by_code[code]["name"] == inspector.REFUSAL_CODES[code][0]
        assert by_code[code]["meaning"] == inspector.REFUSAL_CODES[code][1]
    assert by_code[-32002]["name"] == "UPSTREAM_TIMEOUT"
    assert by_code[-32011]["name"] == "TOOL_NOT_VISIBLE"
    # Unclassifiable error -> code null, name 'unknown'; unknown explicit code keeps its number.
    assert by_code[None]["name"] == "unknown"
    assert by_code[None]["count"] == 1
    assert by_code[-32099]["name"] == "unknown"
    assert report["refusals"]["total"] == len(REFUSAL_ERRORS) + 2
    assert report["refusals"]["per_upstream"]["gh"] == len(REFUSAL_ERRORS) + 2


def test_recent_refusals_newest_first_without_argument_values(tmp_path: Path) -> None:
    path = audit_path(tmp_path)
    log = AuditLog(path)
    for index in range(5):
        log.record(
            "tools_call",
            f"up{index}",
            1.0,
            False,
            arguments={"tool": f"up{index}.t", "arguments": {"note": f"payload-{index}"}},
            error="UpstreamError: Upstream timed out on 'tools/call'.",
        )
    report = inspector.build_report(path, recent=3)
    recent = report["refusals"]["recent"]
    assert [entry["upstream"] for entry in recent] == ["up4", "up3", "up2"]
    for entry in recent:
        assert set(entry) == {"ts", "tool", "upstream", "code", "name"}
    assert "payload-4" not in json.dumps(report)


# ---------------------------------------------------------------------------
# Upstream health
# ---------------------------------------------------------------------------


def test_upstream_health_counts_and_flagging(tmp_path: Path) -> None:
    path = audit_path(tmp_path)
    log = AuditLog(path)
    for _ in range(9):
        log.record("tools_call", "good", 10.0, True)
    log.record("tools_call", "good", 30.0, False, error=REFUSAL_ERRORS[-32003])
    log.record("tools_call", "flaky", 50.0, False, error=REFUSAL_ERRORS[-32002])
    log.record("tools_call", "flaky", 50.0, False, error=REFUSAL_ERRORS[-32002])
    log.record("tools_call", "flaky", 10.0, False, error=REFUSAL_ERRORS[-32001])
    log.record("tools_call", "flaky", 10.0, True)
    report = inspector.build_report(path)
    entries = {entry["upstream"]: entry for entry in report["upstreams"]["entries"]}
    good = entries["good"]
    assert good["calls"] == 10 and good["refusals"] == 1
    assert good["refusal_rate"] == 0.1
    assert good["protocol_errors"] == 1 and good["timeouts"] == 0 and good["spawn_failures"] == 0
    assert good["avg_duration_ms"] == 12.0
    assert good["flagged"] is False
    flaky = entries["flaky"]
    assert flaky["calls"] == 4 and flaky["refusals"] == 3
    assert flaky["refusal_rate"] == 0.75
    assert flaky["timeouts"] == 2 and flaky["spawn_failures"] == 1 and flaky["protocol_errors"] == 0
    assert flaky["flagged"] is True
    assert report["upstreams"]["refusal_rate_threshold"] == 0.5


# ---------------------------------------------------------------------------
# Profiles (E10 fields accepted, never required)
# ---------------------------------------------------------------------------


def write_profile_rows(path: Path) -> None:
    write_raw_row(
        path,
        ts=1000.0,
        tool="profile_loaded",
        upstream="",
        duration_ms=0.0,
        ok=True,
        profile="review",
        profile_sha256=PROFILE_SHA,
        visible_rules=3,
        callable_rules=2,
    )
    write_raw_row(
        path, ts=1001.0, tool="tools_call", upstream="github", duration_ms=2.0, ok=True, profile="review"
    )
    write_raw_row(
        path,
        ts=1002.0,
        tool="tools_call",
        upstream="github",
        duration_ms=1.0,
        ok=False,
        profile="review",
        error="UpstreamError: Tool 'github.x' is not visible under profile 'review' or does not exist (tool_not_visible).",
    )


def test_profiles_section_absent_without_profile_fields(tmp_path: Path) -> None:
    path = audit_path(tmp_path)
    build_basic_log(path)
    report = inspector.build_report(path)
    assert "profiles" not in report
    assert "== Profiles ==" not in inspector.render_text(report, section="all")
    explicit = inspector.render_text(report, section="profiles")
    assert "No profile fields present" in explicit


def test_profiles_section_present_with_profile_fields(tmp_path: Path) -> None:
    path = audit_path(tmp_path)
    build_basic_log(path)
    write_profile_rows(path)
    report = inspector.build_report(path)
    profiles = report["profiles"]
    assert profiles["present"] is True
    assert profiles["per_profile"] == {"review": 2}
    events = profiles["profile_loaded_events"]
    assert len(events) == 1
    assert events[0]["profile"] == "review"
    assert events[0]["profile_sha256"] == PROFILE_SHA
    assert events[0]["visible_rules"] == 3 and events[0]["callable_rules"] == 2
    refusals = {entry["code"]: entry["count"] for entry in profiles["profile_refusals"]}
    assert refusals == {-32011: 1, -32012: 0, -32013: 0, -32014: 0}
    # profile_loaded events are gateway lifecycle rows, not calls.
    assert report["summary"]["total_calls"] == 17
    assert "tools_call" in report["summary"]["per_tool"]
    assert "profile_loaded" not in report["summary"]["per_tool"]
    # The documented SHA-256 hash must not trip the redaction self-check.
    assert report["redaction"]["status"] == "PASS"
    assert "== Profiles ==" in inspector.render_text(report, section="all")


# ---------------------------------------------------------------------------
# Redaction self-check
# ---------------------------------------------------------------------------


def test_redaction_self_check_passes_on_clean_log(tmp_path: Path) -> None:
    path = audit_path(tmp_path)
    log = build_basic_log(path)
    log.record(  # a representative secret-bearing call, written THROUGH redact
        "tools_call",
        "github",
        3.0,
        True,
        arguments={"tool": "github.create_issue", "arguments": {"token": "uls_secret_x", "title": SECRET_BEARER}},
    )
    report = inspector.build_report(path)
    assert report["redaction"]["status"] == "PASS"
    assert report["redaction"]["suspects"] == []
    assert report["redaction"]["strings_scanned"] > 0
    assert "uls_secret_x" not in json.dumps(report)
    assert SECRET_BEARER not in json.dumps(report)


def test_redaction_self_check_fails_with_row_numbers_on_injected_secret(tmp_path: Path) -> None:
    path = audit_path(tmp_path)
    log = AuditLog(path)
    log.record("tools_call", "github", 1.0, True)  # line 1: clean
    write_raw_row(  # line 2: secret-looking value, bypassing redact()
        path,
        ts=2000.0,
        tool="tools_call",
        upstream="github",
        duration_ms=1.0,
        ok=True,
        args={"arguments": {"note": SECRET_BEARER}},
    )
    write_raw_row(  # line 3: home-dir-like path in an error string
        path, ts=2001.0, tool="tools_call", upstream="github", duration_ms=1.0, ok=False, error=SECRET_PATH
    )
    report = inspector.build_report(path)
    redaction = report["redaction"]
    assert redaction["status"] == "FAIL"
    by_line = {suspect["line"]: suspect for suspect in redaction["suspects"]}
    assert set(by_line) == {2, 3}
    assert by_line[2]["reason"] == "secret-looking value"
    assert by_line[2]["file"] == path.name
    assert by_line[2]["field"] == "args.arguments.note"
    assert by_line[3]["reason"] == "home-dir-like path"
    # The suspect VALUES never appear anywhere in the report (JSON or text).
    dumped = json.dumps(report) + inspector.render_text(report, section="all")
    assert SECRET_BEARER not in dumped
    assert "C:\\Users\\tedja" not in dumped
    assert "FAIL" in inspector.render_text(report, section="redaction")


# ---------------------------------------------------------------------------
# Malformed lines, missing file
# ---------------------------------------------------------------------------


def test_malformed_lines_counted_and_skipped(tmp_path: Path) -> None:
    path = audit_path(tmp_path)
    log = AuditLog(path)
    log.record("tools_call", "github", 1.0, True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("this is not json\n")
        handle.write('["a", "json", "array", "is", "not", "a", "row"]\n')
        handle.write("\n")  # blank lines are ignored, not malformed
    log.record("tools_call", "github", 2.0, True)
    report = inspector.build_report(path)
    assert report["log"]["malformed_lines"] == 2
    assert report["log"]["rows_total"] == 2
    assert report["summary"]["total_calls"] == 2


def test_missing_audit_log_is_clear_message_and_exit_1(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "mcp", "audit-report"]) == 1
    err = capsys.readouterr().err
    assert "Audit log not found" in err
    missing = tmp_path / "nope.jsonl"
    assert main(["--root", str(tmp_path), "mcp", "audit-report", "--audit-log", str(missing)]) == 1
    assert "Audit log not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# JSON output validates against the schema
# ---------------------------------------------------------------------------


def test_json_output_validates_against_schema(tmp_path: Path, capsys) -> None:
    path = audit_path(tmp_path)
    build_basic_log(path)
    write_profile_rows(path)
    AuditLog(path).record("tools_call", "gh", 1.0, False, error="ToolError: nope")
    assert main(["--root", str(tmp_path), "mcp", "audit-report", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert validate(report, schema) == []
    assert report["report_type"] == "mcp-audit-report"
    assert report["schema_version"] == 1


def test_json_output_without_profiles_validates_too(tmp_path: Path, capsys) -> None:
    path = audit_path(tmp_path)
    build_basic_log(path)
    assert main(["--root", str(tmp_path), "mcp", "audit-report", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert validate(report, schema) == []
    assert "profiles" not in report


def test_schema_is_draft_2020_12_and_locked_down() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    recent_items = schema["properties"]["refusals"]["properties"]["recent"]["items"]
    # Argument values are structurally impossible in recent refusal entries.
    assert recent_items["additionalProperties"] is False
    assert set(recent_items["properties"]) == {"ts", "tool", "upstream", "code", "name"}
    suspect_items = schema["properties"]["redaction"]["properties"]["suspects"]["items"]
    assert suspect_items["additionalProperties"] is False
    assert "value" not in suspect_items["properties"]


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_cli_dispatches_to_audit_report_command(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake(args) -> int:
        captured.update(audit_log=args.audit_log, json=args.json, section=args.section, root=args.root)
        return 7

    monkeypatch.setattr("unlimited_skills.commands.mcp.cmd_mcp_audit_report", fake)
    assert main(["--root", str(tmp_path), "mcp", "audit-report"]) == 7
    assert captured == {"audit_log": "", "json": False, "section": "all", "root": str(tmp_path)}
    assert main(
        ["--root", str(tmp_path), "mcp", "audit-report", "--json", "--section", "refusals", "--audit-log", "x.jsonl"]
    ) == 7
    assert captured["json"] is True and captured["section"] == "refusals" and captured["audit_log"] == "x.jsonl"


def test_cli_facade_reexport() -> None:
    from unlimited_skills import cli

    from unlimited_skills.commands.mcp import cmd_mcp_audit_report

    assert cli.cmd_mcp_audit_report is cmd_mcp_audit_report


def test_cli_text_sections(tmp_path: Path, capsys) -> None:
    path = audit_path(tmp_path)
    build_basic_log(path)
    assert main(["--root", str(tmp_path), "mcp", "audit-report"]) == 0
    text = capsys.readouterr().out
    for header in ("== Summary ==", "== Refusals ==", "== Upstream health ==", "== Redaction self-check =="):
        assert header in text
    assert "== Profiles ==" not in text  # no profile fields in this log
    assert main(["--root", str(tmp_path), "mcp", "audit-report", "--section", "redaction"]) == 0
    redaction_only = capsys.readouterr().out
    assert "== Redaction self-check ==" in redaction_only
    assert "== Summary ==" not in redaction_only
    with pytest.raises(SystemExit):
        main(["--root", str(tmp_path), "mcp", "audit-report", "--section", "bogus"])
