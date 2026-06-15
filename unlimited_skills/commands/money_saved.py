"""Local Money Saved Meter command wrappers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def cmd_money_saved_meter(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_meter import (
        build_100_call_value_report_fixture,
        build_money_saved_meter_report,
        format_money_saved_meter_markdown,
        load_optional_report,
        money_saved_meter_json,
        write_report,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved meter library root")
    if args.fixture_100_call:
        report = build_100_call_value_report_fixture()
    else:
        mcp_savings_report = load_optional_report(args.mcp_savings_json)
        compare_report = load_optional_report(args.compare)
        audit_log = Path(args.audit_log).expanduser() if args.audit_log else None
        report = build_money_saved_meter_report(
            root,
            mode=args.mode,
            mcp_savings_report=mcp_savings_report,
            audit_log=audit_log,
            compare_report=compare_report,
            target_call_count=args.target_calls,
        )
    text = money_saved_meter_json(report) if args.json else format_money_saved_meter_markdown(report)
    if args.out:
        write_report(Path(args.out), text)
        if args.json_status:
            print(json.dumps({"schema_version": 1, "written": True, "format": "json" if args.json else "markdown"}, indent=2))
        else:
            print(f"Money Saved Meter report written ({'json' if args.json else 'markdown'}).")
        return 0
    print(text, end="")
    return 0
