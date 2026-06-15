"""Privacy-safe local Money Saved Meter measurement.

This module implements the first pull surface for v0.6.4. It is read-only by
default: no nudge, no state file, no upload, and no release/publish behavior.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import __version__
from .feedback import assert_feedback_report_safe
from .mcp.audit import default_audit_path
from .mcp.savings import TOKEN_BYTES
from .roi_receipt import REQUIRED_NOTICE
from .search_core import EVENT_LOG, read_router_metrics

REPORT_SCHEMA_VERSION = 1
REPORT_TYPE = "money_saved_meter"
DEFAULT_TARGET_CALL_COUNT = 100

ALLOWED_CLAIMS = [
    "Unlimited Skills estimates local context savings from routed skill/tool usage.",
    "Bytes may be measured when local artifacts expose sizes.",
    "Tokens and dollars are estimates.",
]

FORBIDDEN_CLAIMS = [
    "exact tokens saved",
    "exact money saved",
    "bill reduction guaranteed",
    "hosted telemetry-backed savings",
    "all skill-body savings measured exactly",
    "provider billing reconciliation",
]

FORBIDDEN_FIELDS = [
    "raw prompts",
    "raw task text",
    "skill bodies",
    "local absolute paths",
    "tokens, keys, secrets",
    "customer names",
    "hosted uploads",
    "private repo paths",
    "raw MCP tool input/output payloads",
    "raw MCP schemas",
    "MCP server command lines or env values",
]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _read_jsonl(path: Path, *, limit: int = 2000) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _latest_mcp_savings_event(root: Path) -> dict[str, Any] | None:
    rows = _read_jsonl(root / ".learning" / EVENT_LOG)
    for row in reversed(rows):
        if row.get("type") != "mcp_savings":
            continue
        payload = row.get("payload")
        if isinstance(payload, dict):
            return payload
    return None


def _safe_mcp_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {
            "status": "unavailable",
            "source": "no_local_mcp_savings_snapshot",
            "measured_servers": 0,
            "skipped_servers": 0,
            "total_bytes": 0,
            "total_est_tokens": 0,
            "gateway_bytes": 0,
            "gateway_est_tokens": 0,
            "savings_bytes": 0,
            "savings_pct": 0.0,
            "server_names_included": False,
            "schema_contents_included": False,
            "commands_included": False,
            "env_included": False,
        }

    servers = payload.get("servers") if isinstance(payload.get("servers"), list) else []
    measured_servers = payload.get("measured_servers")
    skipped_servers = payload.get("skipped_servers")
    if not isinstance(measured_servers, int) or isinstance(measured_servers, bool):
        measured_servers = sum(1 for row in servers if isinstance(row, dict) and row.get("status") == "ok")
    if not isinstance(skipped_servers, int) or isinstance(skipped_servers, bool):
        skipped_servers = max(0, len(servers) - measured_servers)
    total_bytes = int(payload.get("total_bytes") or 0)
    gateway_bytes = int(payload.get("gateway_bytes") or 0)
    return {
        "status": "available" if measured_servers > 0 else "unavailable_no_measured_servers",
        "source": "local_mcp_savings",
        "measured_servers": int(measured_servers),
        "skipped_servers": int(skipped_servers),
        "total_bytes": total_bytes,
        "total_est_tokens": int(payload.get("total_est_tokens") or total_bytes // TOKEN_BYTES),
        "gateway_bytes": gateway_bytes,
        "gateway_est_tokens": int(payload.get("gateway_est_tokens") or gateway_bytes // TOKEN_BYTES),
        "savings_bytes": int(payload.get("savings_bytes") or 0),
        "savings_pct": float(payload.get("savings_pct") or 0.0),
        "server_names_included": False,
        "schema_contents_included": False,
        "commands_included": False,
        "env_included": False,
    }


def _audit_summary(root: Path, audit_log: Path | None) -> dict[str, Any]:
    from .mcp import audit_inspector

    path = audit_log or default_audit_path(root)
    try:
        report = audit_inspector.build_report(path)
    except FileNotFoundError:
        return {
            "status": "unavailable",
            "total_calls": 0,
            "ok_calls": 0,
            "refused_calls": 0,
            "redaction_status": "unavailable",
            "raw_upstream_names_included": False,
            "local_paths_included": False,
        }
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    redaction = report.get("redaction") if isinstance(report.get("redaction"), dict) else {}
    return {
        "status": "available",
        "total_calls": int(summary.get("total_calls") or 0),
        "ok_calls": int(summary.get("ok_calls") or 0),
        "refused_calls": int(summary.get("refused_calls") or 0),
        "redaction_status": str(redaction.get("status") or "unknown"),
        "raw_upstream_names_included": False,
        "local_paths_included": False,
    }


def _router_counts(root: Path) -> dict[str, Any]:
    metrics = read_router_metrics(root)
    total = int(metrics.get("total_invocations") or 0) if isinstance(metrics, dict) else 0
    return {
        "status": "available" if total else "unavailable",
        "total_invocations": total,
        "skill_names_included": False,
        "raw_queries_included": False,
        "local_paths_included": False,
    }


def _source_inputs(
    *,
    mcp_summary: dict[str, Any],
    audit_summary: dict[str, Any],
    router_counts: dict[str, Any],
    mcp_source: str,
    compare_report: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "mcp_savings_context_budget": {
            "status": "available" if mcp_summary["status"] == "available" else "unavailable",
            "source_kind": "mcp_savings",
            "source": mcp_source,
            "privacy_boundary": "aggregate_only_no_raw_payloads",
        },
        "gateway_audit_summary": {
            "status": audit_summary["status"],
            "source_kind": "mcp_audit_summary",
            "privacy_boundary": "aggregate_only_no_raw_payloads",
        },
        "local_router_metrics": {
            "status": router_counts["status"],
            "source_kind": "router_metrics",
            "privacy_boundary": "aggregate_only_no_raw_payloads",
        },
        "before_after_comparison": {
            "status": "available" if compare_report else "unavailable",
            "source_kind": "money_saved_meter_previous_report",
            "privacy_boundary": "aggregate_only_no_raw_payloads",
        },
        "compatible_roi_receipt": {
            "status": "compatible",
            "source_kind": "roi_receipt",
            "privacy_boundary": "aggregate_only_no_raw_payloads",
        },
    }


def _exact_count(value: int, source: str) -> dict[str, Any]:
    return {"value": int(value), "measurement_kind": "exact", "source": source}


def _measured_byte(value: int | None, *, available: bool, source: str, reason: str | None) -> dict[str, Any]:
    return {
        "value": value,
        "measurement_kind": "measured",
        "available": bool(available),
        "source": source,
        "reason": reason,
    }


def _estimate(value: int | float | None, *, available: bool, method: str | None, reason: str | None) -> dict[str, Any]:
    return {
        "value": value,
        "measurement_kind": "estimated",
        "available": bool(available),
        "method": method,
        "reason": reason,
    }


def _comparison(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any] | None:
    if not previous:
        return None
    previous_bytes = (((previous.get("measured_bytes") or {}).get("context_bytes_avoided") or {}).get("value"))
    current_bytes = (((current.get("measured_bytes") or {}).get("context_bytes_avoided") or {}).get("value"))
    if not isinstance(previous_bytes, int) or isinstance(previous_bytes, bool):
        previous_bytes = None
    if not isinstance(current_bytes, int) or isinstance(current_bytes, bool):
        current_bytes = None
    return {
        "baseline_report_type": str(previous.get("report_type") or "unknown"),
        "baseline_mode": str(previous.get("mode") or "unknown"),
        "current_mode": str(current.get("mode") or "unknown"),
        "before_context_bytes_avoided": previous_bytes,
        "current_context_bytes_avoided": current_bytes,
        "delta_context_bytes_avoided": (
            current_bytes - previous_bytes
            if current_bytes is not None and previous_bytes is not None
            else None
        ),
        "measurement_kind": "measured_when_both_reports_have_measured_bytes",
        "claim": "comparison is local and aggregate-only; tokens and dollars remain estimates",
    }


def _disabled_by_default() -> dict[str, dict[str, Any]]:
    reason = "disabled_by_default"
    return {
        "dollar_value": {"enabled": False, "configured_locally": False, "reason": "disabled_by_default_no_local_price_config"},
        "provider_specific_price_assumptions": {"enabled": False, "configured_locally": False, "reason": reason},
        "hosted_telemetry": {"enabled": False, "configured_locally": False, "reason": reason},
        "billing_provider_integration": {"enabled": False, "configured_locally": False, "reason": reason},
    }


def _privacy() -> dict[str, bool]:
    return {
        "local_only": True,
        "upload": False,
        "hosted_telemetry": False,
        "raw_prompts_included": False,
        "raw_task_text_included": False,
        "skill_bodies_included": False,
        "local_absolute_paths_included": False,
        "tokens_keys_secrets_included": False,
        "customer_names_included": False,
        "private_repo_paths_included": False,
        "raw_mcp_payloads_included": False,
        "server_names_included": False,
        "schema_contents_included": False,
        "commands_included": False,
        "env_included": False,
        "telemetry": False,
        "analytics": False,
    }


def build_money_saved_meter_report(
    root: Path,
    *,
    mode: str = "current",
    mcp_savings_report: dict[str, Any] | None = None,
    audit_log: Path | None = None,
    compare_report: dict[str, Any] | None = None,
    target_call_count: int = DEFAULT_TARGET_CALL_COUNT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = root.expanduser()
    mcp_source = "provided_mcp_savings_json" if mcp_savings_report else "latest_local_event"
    mcp_summary = _safe_mcp_summary(mcp_savings_report or _latest_mcp_savings_event(root))
    audit = _audit_summary(root, audit_log)
    router = _router_counts(root)

    context_available = mcp_summary["status"] == "available"
    raw_context_bytes = int(mcp_summary["savings_bytes"] or 0)
    context_bytes = max(raw_context_bytes, 0) if context_available else None
    token_estimate = context_bytes // TOKEN_BYTES if context_bytes is not None else None
    window_calls = int(audit["total_calls"] or 0)
    target = max(1, int(target_call_count or DEFAULT_TARGET_CALL_COUNT))

    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "generated_at": generated_at or now_iso(),
        "mode": mode,
        "measurement_surface": "before_after_install_measurement",
        "unlimited_skills_version": __version__,
        "model_scope": {
            "runtime_meter_implemented": False,
            "cli_command_implemented": True,
            "state_writer_implemented": False,
            "push_nudge_implemented": False,
            "before_after_measurement_supported": True,
        },
        "window": {
            "label": f"per_{target}_gateway_call_reporting_window",
            "target_call_count": target,
            "counted_call_kinds": ["gateway_mcp_call"],
            "window_call_count": window_calls,
            "is_complete_window": window_calls >= target,
            "cadence_not_billing_math": True,
            "partial_window_policy": "report counts so far; never extrapolate exact tokens, exact dollars, or bill reduction",
        },
        "source_inputs": _source_inputs(
            mcp_summary=mcp_summary,
            audit_summary=audit,
            router_counts=router,
            mcp_source=mcp_source,
            compare_report=compare_report,
        ),
        "exact_counts": {
            "router_call_count": _exact_count(router["total_invocations"], "local_router_metrics"),
            "suggested_skill_count": _exact_count(0, "not_counted_by_current_pull_surface"),
            "injected_skill_card_count": _exact_count(0, "not_counted_by_current_pull_surface"),
            "gateway_mcp_call_count": _exact_count(audit["total_calls"], "mcp_audit_summary"),
            "window_call_count": _exact_count(window_calls, "mcp_audit_summary"),
        },
        "measured_bytes": {
            "upstream_schema_bytes": _measured_byte(
                int(mcp_summary["total_bytes"]) if context_available else None,
                available=context_available,
                source="mcp_savings_context_budget",
                reason=None if context_available else "no_local_mcp_savings_measurement",
            ),
            "gateway_schema_bytes": _measured_byte(
                int(mcp_summary["gateway_bytes"]) if int(mcp_summary["gateway_bytes"]) > 0 else None,
                available=int(mcp_summary["gateway_bytes"]) > 0,
                source="mcp_savings_context_budget",
                reason=None if int(mcp_summary["gateway_bytes"]) > 0 else "no_local_gateway_schema_measurement",
            ),
            "context_bytes_avoided": _measured_byte(
                context_bytes,
                available=context_available,
                source="mcp_savings_context_budget",
                reason=None if context_available else "no_local_mcp_savings_measurement",
            ),
            "skill_card_bytes_injected": _measured_byte(
                None,
                available=False,
                source="router_delivery_artifact",
                reason="not_measured_by_current_artifacts",
            ),
        },
        "estimates": {
            "estimated_tokens_avoided": _estimate(
                token_estimate,
                available=token_estimate is not None,
                method="bytes_divided_by_4" if token_estimate is not None else None,
                reason=None if token_estimate is not None else "requires_measured_context_bytes",
            ),
            "estimated_context_bytes_avoided": _estimate(
                None,
                available=False,
                method=None,
                reason="no_context_size_assumption_configured",
            ),
            "estimated_dollar_value": _estimate(
                None,
                available=False,
                method=None,
                reason="disabled_by_default_no_local_price_config",
            )
            | {"enabled": False, "configured_locally": False},
        },
        "disabled_by_default": _disabled_by_default(),
        "forbidden_fields": FORBIDDEN_FIELDS,
        "claim_boundary": {
            "allowed_claims": ALLOWED_CLAIMS,
            "forbidden_claims": FORBIDDEN_CLAIMS,
        },
        "privacy": _privacy(),
        "next_actions": [
            "Run `unlimited-skills mcp savings --json --out before-mcp-savings.json` before installing the gateway.",
            "Run `unlimited-skills money-saved meter --json --mcp-savings-json before-mcp-savings.json --out before-meter.json`.",
            "After install and local usage, rerun `mcp savings` and `money-saved meter --compare before-meter.json`.",
        ],
        "notice": REQUIRED_NOTICE,
    }
    comparison = _comparison(report, compare_report)
    if comparison is not None:
        report["comparison"] = comparison
    assert_money_saved_meter_safe(report)
    return report


def assert_money_saved_meter_safe(value: Any) -> None:
    assert_feedback_report_safe(value)


def money_saved_meter_json(report: dict[str, Any]) -> str:
    assert_money_saved_meter_safe(report)
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def format_money_saved_meter_markdown(report: dict[str, Any]) -> str:
    assert_money_saved_meter_safe(report)
    measured = report["measured_bytes"]
    estimates = report["estimates"]
    window = report["window"]
    context = measured["context_bytes_avoided"]
    tokens = estimates["estimated_tokens_avoided"]
    lines = [
        "# Unlimited Skills Money Saved Meter",
        "",
        f"Generated: {report['generated_at']}",
        f"Mode: {report['mode']}",
        "Surface: before/after install measurement",
        "",
        f"- Gateway calls in window: {window['window_call_count']} / {window['target_call_count']}",
        f"- MCP schema bytes avoided: {context['value'] if context['available'] else 'unavailable'}",
        f"- Estimated tokens avoided: {tokens['value'] if tokens['available'] else 'unavailable'}",
        "- Dollar estimate: unavailable by default",
    ]
    comparison = report.get("comparison")
    if isinstance(comparison, dict):
        lines.extend(
            [
                "",
                "## Before/After Comparison",
                "",
                f"- Baseline mode: {comparison['baseline_mode']}",
                f"- Current mode: {comparison['current_mode']}",
                f"- Delta context bytes avoided: {comparison['delta_context_bytes_avoided']}",
            ]
        )
    lines.extend(
        [
            "",
            REQUIRED_NOTICE,
            "",
            "Local-only: yes. Upload: no. Telemetry: no.",
        ]
    )
    return "\n".join(lines) + "\n"


def load_optional_report(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    return _read_json(Path(path).expanduser())


def write_report(path: Path, text: str) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
