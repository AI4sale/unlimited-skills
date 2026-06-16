"""Router-health tier command wrappers (O062 tier debt)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def cmd_router_health_export(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_meter import write_report
    from ..router_health import (
        ROUTER_HEALTH_EXPORT_SCHEMA_VERSION,
        build_router_health_export,
        router_health_export_json,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="router-health export library root")
    export = build_router_health_export(root)
    text = router_health_export_json(export)
    if args.out:
        write_report(Path(args.out), text)
        if getattr(args, "json_status", False):
            print(json.dumps({"schema_version": ROUTER_HEALTH_EXPORT_SCHEMA_VERSION, "written": True, "format": "json"}, indent=2))
        else:
            print(f"Router-health export written ({args.out}).")
        return 0
    print(text, end="")
    return 0


def cmd_router_health_team_rollup(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_meter import write_report
    from ..router_health import (
        ROUTER_HEALTH_TEAM_ROLLUP_SCHEMA_VERSION,
        IncompatibleExportError,
        build_router_health_team_rollup,
        router_health_team_rollup_json,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="router-health team-rollup library root")
    inputs = [Path(p) for p in (args.input or [])]
    if not inputs:
        print("No --input exports provided. Pass one or more Registered router-health export files.")
        return 2
    aliases = list(args.alias) if getattr(args, "alias", None) else None
    try:
        rollup = build_router_health_team_rollup(inputs, aliases=aliases)
    except IncompatibleExportError as exc:
        print(f"Rejected incompatible input: {exc}")
        return 2
    text = router_health_team_rollup_json(rollup)
    if args.out:
        write_report(Path(args.out), text)
        if getattr(args, "json_status", False):
            print(json.dumps({"schema_version": ROUTER_HEALTH_TEAM_ROLLUP_SCHEMA_VERSION, "written": True, "format": "json"}, indent=2))
        else:
            print(f"Router-health team rollup written ({args.out}).")
        return 0
    print(text, end="")
    return 0
