"""Read-only inspector for the redacted MCP audit JSONL log.

Pure, testable functions that turn the local audit log written by
:mod:`unlimited_skills.mcp.audit` (the active file plus rotated generations
``.1`` .. ``.N``) into actionable reports:

- **summary** -- call totals, ok/refused split, per-tool and per-upstream
  counts, duration percentiles, time range, rotation coverage;
- **refusals** -- breakdown by JSON-RPC refusal code (named ``-32001`` ..
  ``-32014``; anything else is reported as ``unknown``), per-upstream refusal
  counts, and the most recent refusals (timestamp + tool + upstream + code
  only -- never argument values);
- **upstreams** -- per-upstream health: calls, refusal rate, timeout /
  protocol-error / spawn-failure counts, average duration, with upstreams
  above a refusal-rate threshold flagged;
- **profiles** -- per-profile call counts, ``profile_loaded`` events with
  their file SHA-256, and profile-related refusals. Present only when the
  log actually carries E10 ``profile`` fields; logs written before profiles
  existed are read identically (the fields are accepted, never required);
- **redaction** -- a self-check that re-scans every audited string with the
  same secret-shape heuristics the writer uses (:func:`audit.looks_secret`)
  plus the local-path pattern, reporting PASS/FAIL with file + line numbers
  of suspects. Suspect VALUES are never printed -- only their location and
  a reason -- so the report itself cannot leak what redaction missed.

This module only READS audit files. It never writes, rotates, or mutates
them, and it never changes the audit write format.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import time
from pathlib import Path
from typing import Any, Iterable

from . import audit as _audit
from .audit import REDACTED, looks_secret

REPORT_TYPE = "mcp-audit-report"
REPORT_SCHEMA_VERSION = 1
DEFAULT_RECENT_REFUSALS = 10
DEFAULT_REFUSAL_RATE_THRESHOLD = 0.5

# Rows with this tool name are gateway lifecycle events (E10 tool profiles),
# not meta-tool calls; they are reported in the profiles section only.
PROFILE_EVENT_TOOL = "profile_loaded"

# Keys whose values are documented non-sensitive hashes (the profile file's
# SHA-256 pinned by the E10 ``profile_loaded`` row). They are hex blobs by
# nature, so the redaction self-check must not flag them as secrets.
KNOWN_HASH_KEYS = frozenset({"profile_sha256"})

# Gateway refusal codes -> (NAME, meaning). -32001..-32010 are the E07/E08
# upstream security model family (unlimited_skills/mcp/gateway.py);
# -32011..-32014 are the E09/E10 tool-profile family. The table is kept
# locally so the inspector reads logs from any gateway version without
# importing (or requiring) the profile machinery.
REFUSAL_CODES: dict[int, tuple[str, str]] = {
    -32001: (
        "UPSTREAM_START_FAILED",
        "upstream could not be spawned or failed its initialize handshake",
    ),
    -32002: (
        "UPSTREAM_TIMEOUT",
        "upstream did not answer within the deadline (it is terminated)",
    ),
    -32003: (
        "UPSTREAM_PROTOCOL_ERROR",
        "upstream wrote malformed/garbage output; nothing was relayed",
    ),
    -32004: ("UPSTREAM_FAILED", "upstream returned a JSON-RPC error or died mid-call"),
    -32005: ("UPSTREAM_DISABLED", "upstream is configured but disabled"),
    -32006: (
        "COMMAND_NOT_ALLOWED",
        "command violates the allowlist policy for its trust level",
    ),
    -32007: (
        "ENV_FORWARDING_DENIED",
        "environment forwarding beyond the names-only allowlist was attempted",
    ),
    -32008: (
        "SCHEMA_TOO_LARGE",
        "one tool's inputSchema exceeds max_schema_bytes; refused, never truncated",
    ),
    -32009: (
        "RESPONSE_TOO_LARGE",
        "a tools/call result exceeds max_response_bytes; dropped, never truncated",
    ),
    -32010: (
        "TRUST_LEVEL_VIOLATION",
        "operation not permitted at the upstream's trust level",
    ),
    -32011: (
        "TOOL_NOT_VISIBLE",
        "tool not in the profile's visible set (or nonexistent; never distinguished)",
    ),
    -32012: (
        "TOOL_NOT_CALLABLE",
        "tool visible under the profile but not callable (view-only)",
    ),
    -32013: ("PROFILE_NOT_FOUND", "profile file configured but no profile resolved"),
    -32014: (
        "PROFILE_INVALID",
        "profile file fails schema validation or a static load check",
    ),
}
PROFILE_REFUSAL_CODES = (-32011, -32012, -32013, -32014)
UNKNOWN_CODE_NAME = "unknown"
UNKNOWN_CODE_MEANING = "error not attributable to a known gateway refusal code"

# Audit rows carry a path-scrubbed ERROR STRING, not a numeric code, so the
# inspector classifies refusals by the distinctive phrases each gateway
# refusal message uses (gateway.py / profiles.py). Ordered: the first match
# wins, and wrapper messages ("failed to start: ... timed out ...") must hit
# their outer code first. A row that ever grows an explicit integer ``code``
# field is honored directly and skips this table.
_ERROR_TEXT_MARKERS: tuple[tuple[str, int], ...] = (
    ("failed to spawn upstream", -32001),
    ("failed to start", -32001),
    ("timed out on", -32002),
    ("malformed (non-json)", -32003),
    ("non-object json-rpc message", -32003),
    ("returned a non-object result", -32003),
    ("is disabled in the gateway config", -32005),
    ("command not allowed", -32006),
    ("env_allowlist", -32007),
    ("(tool_not_visible)", -32011),
    ("(tool_not_callable)", -32012),
    ("(profile_not_found)", -32013),
    ("(profile_invalid)", -32014),
    ("refused, never truncated", -32008),
    ("dropped, never truncated", -32009),
    ("all i/o is refused", -32010),
    ("stdin write failed", -32004),
    ("closed its stdio stream", -32004),
    ("is not running", -32004),
)
_UPSTREAM_JSONRPC_ERROR_RE = re.compile(r"upstream '[^']*' error ", re.IGNORECASE)

# Same local-path shape the writer scrubs (audit.scrub_paths); mirrored here
# as a fallback so the self-check works even if the private name moves.
_FALLBACK_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s'\"]+|\\\\[^\s'\"]+|~[\\/][^\s'\"]+"
    r"|/(?:home|Users|tmp|var|etc|opt)/[^\s'\"]+)"
)
_PATH_PATTERN = getattr(_audit, "_PATH_PATTERN", _FALLBACK_PATH_PATTERN)

REASON_SECRET = "secret-looking value"
REASON_PATH = "home-dir-like path"


def discover_audit_files(path: Path) -> list[Path]:
    """Active audit file plus rotated generations, oldest first.

    Rotation renames the active file to ``.1`` and shifts ``.1`` -> ``.2``
    etc. (audit.AuditLog._rotate_if_needed), so chronological order is the
    HIGHEST generation first (``.N`` .. ``.1``) and the active file last.
    """
    path = Path(path)
    generations: list[tuple[int, Path]] = []
    if path.parent.is_dir():
        prefix = path.name + "."
        for candidate in path.parent.iterdir():
            if not candidate.is_file() or not candidate.name.startswith(prefix):
                continue
            suffix = candidate.name[len(prefix):]
            if suffix.isdigit():
                generations.append((int(suffix), candidate))
    generations.sort(key=lambda item: -item[0])
    files = [candidate for _, candidate in generations]
    if path.is_file():
        files.append(path)
    return files


def load_audit_rows(path: Path) -> tuple[list[tuple[str, int, dict]], int, list[str]]:
    """Parse every audit file into ``(file_name, line_number, row)`` triples.

    Returns ``(rows, malformed_line_count, file_names_read)``. Malformed
    JSONL lines (broken JSON, non-object lines) are counted and skipped,
    never a crash. Raises :class:`FileNotFoundError` when neither the active
    file nor any rotated generation exists.
    """
    files = discover_audit_files(path)
    if not files:
        raise FileNotFoundError(str(path))
    rows: list[tuple[str, int, dict]] = []
    malformed = 0
    names: list[str] = []
    for file in files:
        names.append(file.name)
        text = file.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(row, dict):
                malformed += 1
                continue
            rows.append((file.name, line_number, row))
    return rows, malformed, names


def refusal_code_of(row: dict) -> int | None:
    """Best-effort JSON-RPC refusal code of one ``ok: false`` row.

    Prefers an explicit integer ``code`` field when a row carries one;
    otherwise classifies the path-scrubbed ``error`` string by the known
    gateway refusal phrases. ``None`` means unclassifiable ("unknown").
    """
    code = row.get("code")
    if isinstance(code, int) and not isinstance(code, bool):
        return code
    error = row.get("error")
    if not isinstance(error, str):
        return None
    lowered = error.lower()
    for marker, marker_code in _ERROR_TEXT_MARKERS:
        if marker in lowered:
            return marker_code
    if _UPSTREAM_JSONRPC_ERROR_RE.search(lowered):
        return -32004
    return None


def code_name(code: int | None) -> str:
    if code in REFUSAL_CODES:
        return REFUSAL_CODES[code][0]
    return UNKNOWN_CODE_NAME


def code_meaning(code: int | None) -> str:
    if code in REFUSAL_CODES:
        return REFUSAL_CODES[code][1]
    return UNKNOWN_CODE_MEANING


def percentile(values: Iterable[float], fraction: float) -> float | None:
    """Nearest-rank percentile (e.g. ``fraction=0.95`` for p95)."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = min(len(ordered), max(1, math.ceil(fraction * len(ordered))))
    return ordered[rank - 1]


def _is_call_row(row: dict) -> bool:
    return row.get("tool") != PROFILE_EVENT_TOOL


def _duration_of(row: dict) -> float | None:
    value = row.get("duration_ms")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def summarize(rows: list[tuple[str, int, dict]]) -> dict:
    """Summary section: counts, per-tool/per-upstream split, durations, range."""
    call_rows = [row for _, _, row in rows if _is_call_row(row)]
    per_tool: dict[str, dict[str, int]] = {}
    per_upstream: dict[str, dict[str, int]] = {}
    durations: dict[str, list[float]] = {}
    ok_calls = 0
    for row in call_rows:
        tool = str(row.get("tool") or "")
        upstream = str(row.get("upstream") or "")
        ok = row.get("ok") is True
        ok_calls += 1 if ok else 0
        for bucket, key in ((per_tool, tool), (per_upstream, upstream)):
            entry = bucket.setdefault(key, {"calls": 0, "ok": 0, "refused": 0})
            entry["calls"] += 1
            entry["ok" if ok else "refused"] += 1
        duration = _duration_of(row)
        if duration is not None:
            durations.setdefault(tool, []).append(duration)
    duration_stats = {
        tool: {
            "count": len(values),
            "min_ms": round(min(values), 3),
            "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(percentile(values, 0.95), 3),
            "max_ms": round(max(values), 3),
        }
        for tool, values in sorted(durations.items())
    }
    timestamps = [
        row["ts"]
        for _, _, row in rows
        if isinstance(row.get("ts"), (int, float)) and not isinstance(row.get("ts"), bool)
    ]
    return {
        "total_calls": len(call_rows),
        "ok_calls": ok_calls,
        "refused_calls": len(call_rows) - ok_calls,
        "per_tool": {key: per_tool[key] for key in sorted(per_tool)},
        "per_upstream": {key: per_upstream[key] for key in sorted(per_upstream)},
        "durations_ms": duration_stats,
        "first_ts": min(timestamps) if timestamps else None,
        "last_ts": max(timestamps) if timestamps else None,
    }


def refusals_report(
    rows: list[tuple[str, int, dict]], recent: int = DEFAULT_RECENT_REFUSALS
) -> dict:
    """Refusals section: by-code table, per-upstream counts, recent refusals.

    Recent entries carry timestamp, tool, upstream, and code only -- never
    argument values or error text.
    """
    refused = [row for _, _, row in rows if _is_call_row(row) and row.get("ok") is not True]
    by_code: dict[int | None, int] = {}
    per_upstream: dict[str, int] = {}
    for row in refused:
        code = refusal_code_of(row)
        by_code[code] = by_code.get(code, 0) + 1
        upstream = str(row.get("upstream") or "")
        per_upstream[upstream] = per_upstream.get(upstream, 0) + 1
    code_entries = [
        {
            "code": code,
            "name": code_name(code),
            "meaning": code_meaning(code),
            "count": count,
        }
        for code, count in by_code.items()
    ]
    code_entries.sort(key=lambda entry: (-entry["count"], entry["name"]))
    recent_entries = [
        {
            "ts": row.get("ts") if isinstance(row.get("ts"), (int, float)) else None,
            "tool": str(row.get("tool") or ""),
            "upstream": str(row.get("upstream") or ""),
            "code": refusal_code_of(row),
            "name": code_name(refusal_code_of(row)),
        }
        for row in refused[-max(0, int(recent)):]
    ]
    recent_entries.reverse()  # most recent first
    return {
        "total": len(refused),
        "by_code": code_entries,
        "per_upstream": {key: per_upstream[key] for key in sorted(per_upstream)},
        "recent": recent_entries,
    }


def upstream_health(
    rows: list[tuple[str, int, dict]],
    refusal_rate_threshold: float = DEFAULT_REFUSAL_RATE_THRESHOLD,
) -> dict:
    """Upstream health section: rates, failure-class counts, flagging."""
    grouped: dict[str, list[dict]] = {}
    for _, _, row in rows:
        if _is_call_row(row):
            grouped.setdefault(str(row.get("upstream") or ""), []).append(row)
    entries = []
    for upstream in sorted(grouped):
        group = grouped[upstream]
        refused = [row for row in group if row.get("ok") is not True]
        codes = [refusal_code_of(row) for row in refused]
        durations = [d for d in (_duration_of(row) for row in group) if d is not None]
        refusal_rate = len(refused) / len(group) if group else 0.0
        entries.append(
            {
                "upstream": upstream,
                "calls": len(group),
                "refusals": len(refused),
                "refusal_rate": round(refusal_rate, 4),
                "timeouts": codes.count(-32002),
                "protocol_errors": codes.count(-32003),
                "spawn_failures": codes.count(-32001),
                "avg_duration_ms": (
                    round(sum(durations) / len(durations), 3) if durations else None
                ),
                "flagged": bool(group) and refusal_rate >= refusal_rate_threshold,
            }
        )
    return {"refusal_rate_threshold": refusal_rate_threshold, "entries": entries}


def profile_report(rows: list[tuple[str, int, dict]]) -> dict | None:
    """Profiles section, or ``None`` when the log has no profile fields.

    The E10 gateway adds an optional ``profile`` field to call rows and one
    ``profile_loaded`` event row per session. Logs written without profiles
    produce no section at all -- the fields are accepted, never required.
    """
    has_profile_fields = any(
        "profile" in row or not _is_call_row(row) for _, _, row in rows
    )
    if not has_profile_fields:
        return None
    per_profile: dict[str, int] = {}
    loaded_events = []
    profile_refusals: dict[int, int] = {code: 0 for code in PROFILE_REFUSAL_CODES}
    for _, _, row in rows:
        if not _is_call_row(row):
            loaded_events.append(
                {
                    "ts": row.get("ts") if isinstance(row.get("ts"), (int, float)) else None,
                    "profile": str(row.get("profile") or ""),
                    "profile_sha256": (
                        str(row["profile_sha256"])
                        if isinstance(row.get("profile_sha256"), str)
                        else None
                    ),
                    "visible_rules": (
                        row["visible_rules"]
                        if isinstance(row.get("visible_rules"), int)
                        and not isinstance(row.get("visible_rules"), bool)
                        else None
                    ),
                    "callable_rules": (
                        row["callable_rules"]
                        if isinstance(row.get("callable_rules"), int)
                        and not isinstance(row.get("callable_rules"), bool)
                        else None
                    ),
                }
            )
            continue
        if "profile" in row:
            name = str(row.get("profile") or "")
            per_profile[name] = per_profile.get(name, 0) + 1
        if row.get("ok") is not True:
            code = refusal_code_of(row)
            if code in profile_refusals:
                profile_refusals[code] += 1
    return {
        "present": True,
        "per_profile": {key: per_profile[key] for key in sorted(per_profile)},
        "profile_loaded_events": loaded_events,
        "profile_refusals": [
            {
                "code": code,
                "name": code_name(code),
                "meaning": code_meaning(code),
                "count": profile_refusals[code],
            }
            for code in PROFILE_REFUSAL_CODES
        ],
    }


def _iter_strings(value: Any, field: str) -> Iterable[tuple[str, str]]:
    """Yield ``(field_path, string_value)`` for every string in a row value."""
    if isinstance(value, str):
        yield field, value
    elif isinstance(value, dict):
        for key, item in value.items():
            if str(key) in KNOWN_HASH_KEYS:
                continue  # documented non-sensitive hash (profile_loaded SHA-256)
            yield from _iter_strings(item, f"{field}.{key}" if field else str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _iter_strings(item, f"{field}[{index}]")


def redaction_self_check(rows: list[tuple[str, int, dict]]) -> dict:
    """Re-scan every audited string for secret shapes and local paths.

    Guards against future redaction regressions: the same ``looks_secret``
    heuristics the writer applies (Bearer/Basic headers, JWTs, PEM blocks,
    long hex/base64 blobs) plus the home-dir-like path pattern are applied
    to what actually landed on disk. Suspects are reported as file + line +
    field + reason ONLY; the suspect value itself is never included.
    """
    suspects = []
    strings_scanned = 0
    for file_name, line_number, row in rows:
        for field, text in _iter_strings(row, ""):
            strings_scanned += 1
            if text == REDACTED:
                continue
            reason = None
            if looks_secret(text):
                reason = REASON_SECRET
            elif _PATH_PATTERN.search(text):
                reason = REASON_PATH
            if reason:
                suspects.append(
                    {
                        "file": file_name,
                        "line": line_number,
                        "field": field,
                        "reason": reason,
                    }
                )
    return {
        "status": "FAIL" if suspects else "PASS",
        "strings_scanned": strings_scanned,
        "suspects": suspects,
    }


def build_report(
    path: Path,
    recent: int = DEFAULT_RECENT_REFUSALS,
    refusal_rate_threshold: float = DEFAULT_REFUSAL_RATE_THRESHOLD,
    now: float | None = None,
) -> dict:
    """Build the full report document for one audit log (plus rotations).

    Raises :class:`FileNotFoundError` when no audit file exists at ``path``.
    The document validates against ``schemas/mcp-audit-report.schema.json``;
    the ``profiles`` key is present only when the log carries profile fields.
    """
    rows, malformed, file_names = load_audit_rows(path)
    report: dict[str, Any] = {
        "report_type": REPORT_TYPE,
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _format_ts(now if now is not None else time.time()),
        "log": {
            "files_read": file_names,
            "rotated_files_read": sum(1 for name in file_names if name.rsplit(".", 1)[-1].isdigit()),
            "rows_total": len(rows),
            "malformed_lines": malformed,
        },
        "summary": summarize(rows),
        "refusals": refusals_report(rows, recent=recent),
        "upstreams": upstream_health(rows, refusal_rate_threshold=refusal_rate_threshold),
        "redaction": redaction_self_check(rows),
    }
    profiles = profile_report(rows)
    if profiles is not None:
        report["profiles"] = profiles
    return report


def _format_ts(value: float | None) -> str:
    if value is None:
        return "-"
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def _text_summary(report: dict) -> list[str]:
    log = report["log"]
    summary = report["summary"]
    lines = ["== Summary =="]
    lines.append(
        f"Audit files read: {len(log['files_read'])} "
        f"({log['rotated_files_read']} rotated): {', '.join(log['files_read'])}"
    )
    lines.append(
        f"Rows: {log['rows_total']} parsed, {log['malformed_lines']} malformed line(s) skipped"
    )
    lines.append(
        f"Time range: {_format_ts(summary['first_ts'])} .. {_format_ts(summary['last_ts'])}"
    )
    lines.append(
        f"Calls: {summary['total_calls']} total, {summary['ok_calls']} ok, "
        f"{summary['refused_calls']} refused"
    )
    if summary["per_tool"]:
        lines.append("Per tool:")
        for tool, entry in summary["per_tool"].items():
            lines.append(
                f"  {tool or '(none)':<14} {entry['calls']:>5} calls  "
                f"{entry['ok']:>5} ok  {entry['refused']:>5} refused"
            )
    if summary["per_upstream"]:
        lines.append("Per upstream:")
        for upstream, entry in summary["per_upstream"].items():
            lines.append(
                f"  {upstream or '(none)':<14} {entry['calls']:>5} calls  "
                f"{entry['ok']:>5} ok  {entry['refused']:>5} refused"
            )
    if summary["durations_ms"]:
        lines.append("Durations (ms):")
        for tool, stats in summary["durations_ms"].items():
            lines.append(
                f"  {tool or '(none)':<14} min {stats['min_ms']}  median {stats['median_ms']}  "
                f"p95 {stats['p95_ms']}  max {stats['max_ms']}  (n={stats['count']})"
            )
    return lines


def _text_refusals(report: dict) -> list[str]:
    refusals = report["refusals"]
    lines = ["== Refusals ==", f"Total refusals: {refusals['total']}"]
    if refusals["by_code"]:
        lines.append("By code:")
        for entry in refusals["by_code"]:
            code = entry["code"] if entry["code"] is not None else "?"
            lines.append(
                f"  {code!s:<8} {entry['name']:<24} {entry['count']:>5}  {entry['meaning']}"
            )
    if refusals["per_upstream"]:
        lines.append("Per upstream:")
        for upstream, count in refusals["per_upstream"].items():
            lines.append(f"  {upstream or '(none)':<14} {count:>5}")
    if refusals["recent"]:
        lines.append("Most recent (newest first; never argument values):")
        for entry in refusals["recent"]:
            code = entry["code"] if entry["code"] is not None else "?"
            lines.append(
                f"  {_format_ts(entry['ts'])}  {entry['tool']:<13} "
                f"{(entry['upstream'] or '(none)'):<14} {code!s:<8} {entry['name']}"
            )
    return lines


def _text_upstreams(report: dict) -> list[str]:
    upstreams = report["upstreams"]
    threshold = upstreams["refusal_rate_threshold"]
    lines = [
        "== Upstream health ==",
        f"Refusal-rate threshold: {threshold * 100:.0f}%",
    ]
    if not upstreams["entries"]:
        lines.append("No upstream calls recorded.")
    for entry in upstreams["entries"]:
        avg = entry["avg_duration_ms"]
        lines.append(
            f"  {entry['upstream'] or '(none)':<14} {entry['calls']:>5} calls  "
            f"{entry['refusals']:>4} refused ({entry['refusal_rate'] * 100:.1f}%)  "
            f"timeouts {entry['timeouts']}  protocol {entry['protocol_errors']}  "
            f"spawn-fail {entry['spawn_failures']}  "
            f"avg {avg if avg is not None else '-'} ms"
            + ("  [FLAGGED]" if entry["flagged"] else "")
        )
    return lines


def _text_profiles(report: dict) -> list[str]:
    profiles = report.get("profiles")
    if not profiles:
        return [
            "== Profiles ==",
            "No profile fields present in this audit log (pre-E10 log or no-profiles open mode).",
        ]
    lines = ["== Profiles =="]
    if profiles["per_profile"]:
        lines.append("Calls per profile:")
        for name, count in profiles["per_profile"].items():
            lines.append(f"  {name or '(unnamed)':<20} {count:>5}")
    if profiles["profile_loaded_events"]:
        lines.append("profile_loaded events:")
        for event in profiles["profile_loaded_events"]:
            lines.append(
                f"  {_format_ts(event['ts'])}  profile '{event['profile']}'  "
                f"sha256 {event['profile_sha256'] or '-'}  "
                f"visible_rules {event['visible_rules'] if event['visible_rules'] is not None else '-'}  "
                f"callable_rules {event['callable_rules'] if event['callable_rules'] is not None else '-'}"
            )
    lines.append("Profile-related refusals:")
    for entry in profiles["profile_refusals"]:
        lines.append(f"  {entry['code']}  {entry['name']:<18} {entry['count']:>5}")
    return lines


def _text_redaction(report: dict) -> list[str]:
    redaction = report["redaction"]
    lines = ["== Redaction self-check =="]
    if redaction["status"] == "PASS":
        lines.append(
            f"PASS: {redaction['strings_scanned']} audited string(s) scanned; "
            "no secret-looking values or home-dir-like paths found."
        )
    else:
        lines.append(
            f"FAIL: {len(redaction['suspects'])} suspect(s) in "
            f"{redaction['strings_scanned']} scanned string(s). "
            "Suspect values are never printed -- inspect the rows locally:"
        )
        for suspect in redaction["suspects"]:
            lines.append(
                f"  {suspect['file']} line {suspect['line']} "
                f"({suspect['field']}): {suspect['reason']}"
            )
    return lines


_SECTION_RENDERERS = {
    "summary": _text_summary,
    "refusals": _text_refusals,
    "upstreams": _text_upstreams,
    "profiles": _text_profiles,
    "redaction": _text_redaction,
}
SECTIONS = (*_SECTION_RENDERERS, "all")


def render_text(report: dict, section: str = "all") -> str:
    """Plain-text rendering of the report (one section, or all of them).

    The ``profiles`` section is rendered inside ``all`` only when the log
    carried profile fields; requesting ``--section profiles`` explicitly
    always answers (with a "not present" note when applicable).
    """
    if section != "all" and section not in _SECTION_RENDERERS:
        raise ValueError(f"Unknown section: {section}")
    parts: list[list[str]] = []
    for name, renderer in _SECTION_RENDERERS.items():
        if section == "all" and name == "profiles" and "profiles" not in report:
            continue
        if section in ("all", name):
            parts.append(renderer(report))
    return "\n\n".join("\n".join(lines) for lines in parts)
