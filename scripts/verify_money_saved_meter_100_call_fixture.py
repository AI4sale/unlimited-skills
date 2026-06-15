from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unlimited_skills.money_saved_meter import assert_money_saved_meter_safe

DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "money_saved_meter" / "100-call-value-report.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def verify_fixture_report(payload: dict[str, Any]) -> dict[str, Any]:
    assert_money_saved_meter_safe(payload)
    window = payload.get("window") if isinstance(payload.get("window"), dict) else {}
    exact_counts = payload.get("exact_counts") if isinstance(payload.get("exact_counts"), dict) else {}
    measured = payload.get("measured_bytes") if isinstance(payload.get("measured_bytes"), dict) else {}
    estimates = payload.get("estimates") if isinstance(payload.get("estimates"), dict) else {}
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}

    _require(payload.get("schema_version") == 1, "schema_version must be 1")
    _require(payload.get("report_type") == "money_saved_meter", "report_type must be money_saved_meter")
    _require(payload.get("measurement_surface") == "100_call_value_report_fixture", "measurement_surface must be fixture")
    _require(window.get("target_call_count") == 100, "target_call_count must be 100")
    _require(window.get("window_call_count") == 100, "window_call_count must be 100")
    _require(window.get("is_complete_window") is True, "100-call fixture must be complete")
    _require(window.get("cadence_not_billing_math") is True, "100-call fixture must not be billing math")

    for name in ("router_call_count", "gateway_mcp_call_count", "window_call_count"):
        row = exact_counts.get(name)
        _require(isinstance(row, dict), f"{name} must be present")
        _require(row.get("measurement_kind") == "exact", f"{name} must be an exact count")
        _require(isinstance(row.get("value"), int) and not isinstance(row.get("value"), bool), f"{name} must be an integer count")

    context_bytes = measured.get("context_bytes_avoided")
    _require(isinstance(context_bytes, dict), "context_bytes_avoided must be present")
    _require(context_bytes.get("measurement_kind") == "measured", "context bytes must be measured bytes")
    _require(context_bytes.get("available") is True, "context bytes must be available in fixture")
    _require(context_bytes.get("source") == "mcp_savings_context_budget", "context bytes must come from local MCP savings fixture")

    token_estimate = estimates.get("estimated_tokens_avoided")
    _require(isinstance(token_estimate, dict), "estimated_tokens_avoided must be present")
    _require(token_estimate.get("measurement_kind") == "estimated", "tokens must remain estimated")
    _require(token_estimate.get("method") == "bytes_divided_by_4", "token estimate method must be labeled")

    dollar_estimate = estimates.get("estimated_dollar_value")
    _require(isinstance(dollar_estimate, dict), "estimated_dollar_value must be present")
    _require(dollar_estimate.get("enabled") is False, "dollar estimate must be disabled by default")
    _require(dollar_estimate.get("value") is None, "dollar estimate value must stay null")

    for flag in (
        "upload",
        "hosted_telemetry",
        "raw_prompts_included",
        "raw_task_text_included",
        "skill_bodies_included",
        "local_absolute_paths_included",
        "tokens_keys_secrets_included",
        "customer_names_included",
        "private_repo_paths_included",
        "raw_mcp_payloads_included",
        "server_names_included",
        "schema_contents_included",
        "commands_included",
        "env_included",
    ):
        _require(privacy.get(flag) is False, f"privacy flag {flag} must be false")

    return {
        "schema_version": 1,
        "report_type": "money_saved_meter_100_call_fixture_verification",
        "ok": True,
        "target_call_count": window["target_call_count"],
        "window_call_count": window["window_call_count"],
        "context_bytes_avoided": context_bytes["value"],
        "estimated_tokens_avoided": token_estimate["value"],
        "dollar_value_enabled": dollar_estimate["enabled"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the deterministic Money Saved Meter 100-call fixture.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE), help="Fixture JSON path.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable verification result.")
    args = parser.parse_args()

    payload = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    result = verify_fixture_report(payload)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("money saved meter 100-call fixture verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
