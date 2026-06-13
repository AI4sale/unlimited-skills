"""Privacy-safe local feedback report preparation.

The module prepares copy/pasteable feedback for public GitHub issues. It is
local-only by design: no network, no upload, no prompt capture, no tool I/O
capture, and no skill body reads beyond aggregate counts.
"""

from __future__ import annotations

import json
import platform
import re
import sys
import time
from collections import Counter
from importlib import metadata
from pathlib import Path
from typing import Any

from . import __version__
from .mcp.savings import build_savings_report, discover_mcp_servers
from .registration import unlimited_skills_home
from .search_core import EVENT_LOG, INDEX_NAME, SkillHit, load_records, read_text
from .skillops_usage_snapshot import build_usage_snapshot

REPORT_SCHEMA_VERSION = 1
REPORT_TYPE = "feedback-prepare-report"

ISSUE_TEMPLATES = {
    "first_value": ".github/ISSUE_TEMPLATE/first-value-feedback.yml",
    "install_friction": ".github/ISSUE_TEMPLATE/install-friction.yml",
    "skill_not_invoked": ".github/ISSUE_TEMPLATE/skill-not-invoked.yml",
    "mcp_savings": ".github/ISSUE_TEMPLATE/mcp-savings-report.yml",
}

FORBIDDEN_FIELD_NAMES = {
    "args",
    "argument",
    "arguments",
    "authorization",
    "command",
    "cookie",
    "device_private_key",
    "env",
    "environment",
    "input",
    "inputSchema",
    "license_token",
    "output",
    "private_key",
    "prompt",
    "proof",
    "raw",
    "result",
    "schema",
    "secret",
    "skill_body",
    "stderr",
    "stdout",
    "task",
    "token",
    "tool_input",
    "tool_output",
}

FORBIDDEN_TEXT_RE = [
    re.compile(r"[A-Za-z]:\\[^\s\"']+", re.IGNORECASE),
    re.compile(r"/(?:Users|home|private|tmp|var|etc)/[^\s\"']+", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|glpat|xoxb|uls)_[A-Za-z0-9_\-]{8,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bAuthorization:\s*Bearer\b", re.IGNORECASE),
]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def os_family() -> str:
    system = platform.system().strip().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    if system == "linux":
        return "linux"
    return "other"


def python_family() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def detect_install_method() -> str:
    try:
        dist = metadata.distribution("unlimited-skills")
    except metadata.PackageNotFoundError:
        return "unknown"
    direct_url = dist.read_text("direct_url.json") or ""
    lowered = direct_url.lower()
    if '"editable": true' in lowered:
        return "editable"
    if '"vcs_info"' in lowered or "git+" in lowered:
        return "git"
    if direct_url:
        return "direct-url"
    return "pypi"


def _count_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    if count <= 10:
        return "1-10"
    if count <= 50:
        return "11-50"
    if count <= 250:
        return "51-250"
    if count <= 1000:
        return "251-1000"
    return "1000+"


def _records(root: Path) -> list[tuple[SkillHit, str]]:
    try:
        return load_records(root)
    except Exception:
        return []


def _library_summary(root: Path) -> dict[str, Any]:
    records = _records(root)
    collections = Counter(hit.collection for hit, _body in records)
    index_path = root / INDEX_NAME
    return {
        "root_present": root.is_dir(),
        "indexed_skill_count": len(records),
        "indexed_skill_count_bucket": _count_bucket(len(records)),
        "collection_count": len(collections),
        "collection_counts": dict(sorted(collections.items())),
        "index_present": index_path.is_file(),
        "skill_names_included": False,
        "skill_bodies_included": False,
        "local_paths_included": False,
    }


def _read_jsonl(path: Path, *, limit: int = 400) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines[-limit:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _event_rows(root: Path) -> list[dict[str, Any]]:
    return _read_jsonl(root / ".learning" / EVENT_LOG)


def _quickstart_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    quickstarts = [row for row in events if row.get("type") == "quickstart"]
    if not quickstarts:
        return {"status": "not_seen", "latest_run_present": False}
    payload = quickstarts[-1].get("payload") if isinstance(quickstarts[-1].get("payload"), dict) else {}
    steps = payload.get("steps") if isinstance(payload, dict) else {}
    return {
        "status": "seen",
        "latest_run_present": True,
        "step_count": len(steps) if isinstance(steps, dict) else 0,
        "had_search_result": bool(payload.get("first_search_hit_count")) if isinstance(payload, dict) else False,
        "had_mcp_savings": bool(payload.get("mcp_savings_present")) if isinstance(payload, dict) else False,
        "raw_output_included": False,
    }


def _suggest_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in events if row.get("type") == "suggest"]
    reason_counts: Counter[str] = Counter()
    delivery_counts: Counter[str] = Counter()
    latencies: list[int] = []
    for row in rows:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        reason = str(payload.get("reason_code") or "unknown")
        reason_counts[reason] += 1
        tier = payload.get("delivery_tier")
        if tier is not None:
            delivery_counts[str(tier)] += 1
        latency = payload.get("latency_ms")
        if isinstance(latency, (int, float)):
            latencies.append(int(latency))
    return {
        "local_run_available": bool(rows),
        "event_count": len(rows),
        "reason_counts": dict(sorted(reason_counts.items())),
        "delivery_tier_counts": dict(sorted(delivery_counts.items())),
        "latest_latency_ms": latencies[-1] if latencies else None,
        "queries_included": False,
        "skill_bodies_included": False,
        "local_paths_included": False,
    }


def _learning_feedback_summary(root: Path) -> dict[str, Any]:
    rows = _read_jsonl(root / ".learning" / "feedback.jsonl")
    verdicts: Counter[str] = Counter(str(row.get("verdict") or "unknown") for row in rows)
    return {
        "local_feedback_count": len(rows),
        "verdict_counts": dict(sorted(verdicts.items())),
        "notes_included": False,
        "queries_included": False,
        "skill_names_included": False,
    }


def _latest_error_categories(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in events:
        event_type = str(row.get("type") or "")
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        reason = str(payload.get("reason_code") or payload.get("status") or "")
        if reason in {"error", "failed", "refused"} or "error" in event_type:
            category = event_type or reason or "unknown"
            counts[category] += 1
    return [{"category": name, "count": count} for name, count in sorted(counts.items())[:8]]


def _mcp_savings_snapshot(include: bool) -> dict[str, Any]:
    if not include:
        return {
            "included": False,
            "reason": "run feedback prepare --include-usage-snapshot to include local MCP savings counts",
            "servers": [],
            "server_names_included": False,
            "schema_contents_included": False,
            "commands_included": False,
            "env_included": False,
        }
    report = build_savings_report(discover_mcp_servers())
    rows = [
        {
            "name": str(row.get("name") or ""),
            "status": str(row.get("status") or ""),
            "tools_count": int(row.get("tools_count") or 0),
            "schema_bytes": int(row.get("schema_bytes") or 0),
            "est_tokens": int(row.get("est_tokens") or 0),
        }
        for row in report.get("servers", [])
        if isinstance(row, dict)
    ]
    return {
        "included": True,
        "servers": rows,
        "measured_servers": int(report.get("measured_servers") or 0),
        "skipped_servers": int(report.get("skipped_servers") or 0),
        "total_bytes": int(report.get("total_bytes") or 0),
        "total_est_tokens": int(report.get("total_est_tokens") or 0),
        "gateway_bytes": int(report.get("gateway_bytes") or 0),
        "gateway_est_tokens": int(report.get("gateway_est_tokens") or 0),
        "savings_bytes": int(report.get("savings_bytes") or 0),
        "savings_pct": float(report.get("savings_pct") or 0.0),
        "server_names_included": True,
        "schema_contents_included": False,
        "commands_included": False,
        "env_included": False,
    }


def _claude_code_mcp_status() -> dict[str, Any]:
    try:
        from .mcp.claude_code import ClaudeCodeMcpOptions, claude_code_gateway_status

        report = claude_code_gateway_status(ClaudeCodeMcpOptions(scope="global"))
    except Exception:
        return {
            "status": "unknown",
            "configured": False,
            "raw_config_included": False,
            "local_paths_included": False,
        }
    return {
        "status": "configured" if report.get("configured") else "not_configured",
        "configured": bool(report.get("configured")),
        "scope": "global",
        "raw_config_included": False,
        "local_paths_included": False,
    }


def _usage_snapshot(root: Path, include: bool) -> dict[str, Any]:
    if not include:
        return {"included": False}
    snapshot = build_usage_snapshot(root, dry_run=True)
    return {
        "included": True,
        "snapshot_type": snapshot.get("snapshot_type"),
        "library": snapshot.get("library", {}),
        "recommendations": snapshot.get("recommendations", {}),
        "catalog_quality": snapshot.get("catalog_quality", {}),
        "maintainer_queue": snapshot.get("maintainer_queue", {}),
        "privacy": snapshot.get("privacy", {}),
    }


def _privacy_flags() -> dict[str, bool]:
    return {
        "telemetry": False,
        "auto_upload": False,
        "network_calls": False,
        "prompts_included": False,
        "tool_inputs_included": False,
        "tool_outputs_included": False,
        "skill_bodies_included": False,
        "mcp_schemas_included": False,
        "launch_commands_included": False,
        "env_names_included": False,
        "env_values_included": False,
        "tokens_included": False,
        "private_keys_included": False,
        "local_paths_included": False,
        "raw_mcp_json_included": False,
        "raw_claude_json_included": False,
    }


def build_feedback_report(
    root: Path,
    *,
    include_usage_snapshot: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = root.expanduser()
    events = _event_rows(root)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "generated_at": generated_at or now_iso(),
        "local_only": True,
        "network_calls": False,
        "hosted_calls": False,
        "upload_available": False,
        "client": {
            "name": "unlimited-skills",
            "version": __version__,
            "install_method": detect_install_method(),
        },
        "system": {
            "os_family": os_family(),
            "python_family": python_family(),
        },
        "library": _library_summary(root),
        "quickstart": _quickstart_summary(events),
        "suggest_effectiveness": _suggest_summary(events),
        "local_learning_feedback": _learning_feedback_summary(root),
        "mcp_savings": _mcp_savings_snapshot(include_usage_snapshot),
        "claude_code_mcp_installer": _claude_code_mcp_status(),
        "usage_snapshot": _usage_snapshot(root, include_usage_snapshot),
        "latest_error_categories": _latest_error_categories(events),
        "issue_template_mapping": [
            {
                "issue_type": "first_value",
                "template": ISSUE_TEMPLATES["first_value"],
                "use_for": "first five minutes worked, stalled, or never reached value",
            },
            {
                "issue_type": "install_friction",
                "template": ISSUE_TEMPLATES["install_friction"],
                "use_for": "install, setup, plugin, quickstart, or vector setup failures",
            },
            {
                "issue_type": "skill_not_invoked",
                "template": ISSUE_TEMPLATES["skill_not_invoked"],
                "use_for": "missing, wrong, or poorly ranked skill suggestions",
            },
            {
                "issue_type": "mcp_savings",
                "template": ISSUE_TEMPLATES["mcp_savings"],
                "use_for": "local MCP savings counts and byte/token estimates",
            },
        ],
        "paste_boundaries": {
            "safe_to_paste": [
                "this JSON report",
                "the Markdown report generated by feedback prepare",
                "unlimited-skills suggest output",
                "unlimited-skills mcp savings output",
            ],
            "do_not_paste": [
                "prompts",
                "tool inputs or outputs",
                "skill bodies",
                "MCP schemas",
                "launch commands",
                "environment names or values",
                "tokens, proofs, or private keys",
                "local absolute paths",
                "raw .mcp.json or .claude.json",
            ],
        },
        "privacy": _privacy_flags(),
    }
    assert_feedback_report_safe(report)
    return report


def assert_feedback_report_safe(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_FIELD_NAMES:
                raise RuntimeError(f"Feedback report contains forbidden field at {path}: {key}")
            if lowered.endswith("_included") and item is not False and lowered not in {"server_names_included"}:
                raise RuntimeError(f"Feedback report privacy flag must be false at {path}.{key}")
            assert_feedback_report_safe(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_feedback_report_safe(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        for pattern in FORBIDDEN_TEXT_RE:
            if pattern.search(value):
                raise RuntimeError(f"Feedback report contains forbidden text at {path}.")


def feedback_report_json(report: dict[str, Any]) -> str:
    assert_feedback_report_safe(report)
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def format_feedback_markdown(report: dict[str, Any]) -> str:
    assert_feedback_report_safe(report)
    lib = report["library"]
    suggest = report["suggest_effectiveness"]
    mcp = report["mcp_savings"]
    lines = [
        "# Unlimited Skills feedback report",
        "",
        "Local-only: yes",
        "Upload: no",
        "Telemetry: no",
        "",
        "## Environment",
        "",
        f"- Unlimited Skills: {report['client']['version']}",
        f"- Install method: {report['client']['install_method']}",
        f"- OS family: {report['system']['os_family']}",
        f"- Python: {report['system']['python_family']}",
        "",
        "## Library",
        "",
        f"- Indexed skills: {lib['indexed_skill_count']}",
        f"- Collections: {lib['collection_count']}",
        f"- Index present: {lib['index_present']}",
        "",
        "## Suggest",
        "",
        f"- Local suggest events: {suggest['event_count']}",
        f"- Reason counts: {json.dumps(suggest['reason_counts'], sort_keys=True)}",
        "",
        "## MCP Savings",
        "",
    ]
    if mcp["included"]:
        lines.extend(
            [
                f"- Measured servers: {mcp['measured_servers']}",
                f"- Skipped servers: {mcp['skipped_servers']}",
                f"- Total estimated tokens: {mcp['total_est_tokens']}",
                f"- Gateway estimated tokens: {mcp['gateway_est_tokens']}",
                f"- Savings percent: {mcp['savings_pct']}",
            ]
        )
    else:
        lines.append("- Not included. Rerun with `--include-usage-snapshot` for local counts.")
    lines.extend(
        [
            "",
            "## Issue Templates",
            "",
        ]
    )
    for item in report["issue_template_mapping"]:
        lines.append(f"- `{item['issue_type']}`: `{item['template']}`")
    lines.extend(
        [
            "",
            "## Privacy Boundary",
            "",
            "This report intentionally excludes prompts, tool inputs, tool outputs, skill bodies, MCP schemas, launch commands, environment names or values, tokens, proofs, private keys, local absolute paths, and raw MCP/Claude config files.",
        ]
    )
    return "\n".join(lines) + "\n"


def feedback_doctor_text() -> str:
    return "\n".join(
        [
            "Unlimited Skills feedback doctor",
            "Local-only: yes",
            "Telemetry: no",
            "Auto-upload: no",
            "",
            "Safe commands:",
            "  unlimited-skills feedback prepare",
            "  unlimited-skills feedback prepare --include-usage-snapshot",
            "",
            "Paste the generated JSON or Markdown into one of the GitHub issue templates.",
            "Do not paste prompts, tool inputs/outputs, skill bodies, MCP schemas, launch commands, env names/values, tokens, private keys, local paths, raw .mcp.json, or raw .claude.json.",
        ]
    )


def write_report(path: Path, text: str) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
