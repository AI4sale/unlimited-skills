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


def cmd_money_saved_registered_export(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_meter import (
        REGISTERED_EXPORT_SCHEMA_VERSION,
        build_registered_export,
        load_optional_report,
        registered_export_json,
        write_report,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved registered-export library root")
    mcp_savings_report = load_optional_report(args.mcp_savings_json)
    audit_log = Path(args.audit_log).expanduser() if args.audit_log else None
    export = build_registered_export(
        root,
        mode=args.mode,
        mcp_savings_report=mcp_savings_report,
        audit_log=audit_log,
        target_call_count=args.target_calls,
    )
    text = registered_export_json(export)
    if args.out:
        write_report(Path(args.out), text)
        if args.json_status:
            print(json.dumps({"schema_version": REGISTERED_EXPORT_SCHEMA_VERSION, "written": True, "format": "json"}, indent=2))
        else:
            print(f"Registered Money Saved export written ({args.out}).")
        return 0
    print(text, end="")
    return 0


def cmd_money_saved_team_rollup(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_meter import write_report
    from ..money_saved_tiers import (
        MSM_TEAM_ROLLUP_SCHEMA_VERSION,
        IncompatibleExportError,
        build_money_saved_team_rollup,
        money_saved_team_rollup_json,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved team-rollup library root")
    inputs = [Path(p) for p in (args.input or [])]
    if not inputs:
        print("No --input exports provided. Pass one or more Registered Money Saved export files.")
        return 2
    aliases = list(args.alias) if getattr(args, "alias", None) else None
    try:
        rollup = build_money_saved_team_rollup(inputs, aliases=aliases)
    except IncompatibleExportError as exc:
        print(f"Rejected incompatible input: {exc}")
        return 2
    text = money_saved_team_rollup_json(rollup)
    if args.out:
        write_report(Path(args.out), text)
        if getattr(args, "json_status", False):
            print(json.dumps({"schema_version": MSM_TEAM_ROLLUP_SCHEMA_VERSION, "written": True, "format": "json"}, indent=2))
        else:
            print(f"Money Saved team rollup written ({args.out}).")
        return 0
    print(text, end="")
    return 0


def cmd_money_saved_admin_export(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_meter import write_report
    from ..money_saved_tiers import (
        IncompatibleExportError,
        build_money_saved_admin_export,
        money_saved_admin_export_csv,
        money_saved_admin_export_json,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="money-saved admin-export library root")
    if not args.input:
        print("No --input team rollup provided.")
        return 2
    labels = None
    if getattr(args, "labels", ""):
        try:
            labels = json.loads(Path(args.labels).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Could not read --labels file: {exc.__class__.__name__}.")
            return 2
    try:
        export = build_money_saved_admin_export(Path(args.input), labels=labels)
    except IncompatibleExportError as exc:
        print(f"Rejected incompatible input: {exc}")
        return 2

    json_text = money_saved_admin_export_json(export)
    csv_text = money_saved_admin_export_csv(export)
    wrote = False
    if getattr(args, "csv", ""):
        write_report(Path(args.csv), csv_text)
        wrote = True
    if getattr(args, "json", ""):
        write_report(Path(args.json), json_text)
        wrote = True
    if wrote:
        print(f"Money Saved admin export written (rows={export['measured']['row_count']}).")
        return 0
    print(json_text, end="")
    return 0
