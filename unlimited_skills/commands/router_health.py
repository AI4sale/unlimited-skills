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


def cmd_router_health_admin_export(args: argparse.Namespace) -> int:
    from .. import cli
    from ..money_saved_meter import write_report
    from ..router_health import (
        IncompatibleExportError,
        build_router_health_admin_export,
        router_health_admin_export_csv,
        router_health_admin_export_json,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="router-health admin-export library root")
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
        export = build_router_health_admin_export(Path(args.input), labels=labels)
    except IncompatibleExportError as exc:
        print(f"Rejected incompatible input: {exc}")
        return 2

    json_text = router_health_admin_export_json(export)
    csv_text = router_health_admin_export_csv(export)
    wrote = False
    if getattr(args, "csv", ""):
        write_report(Path(args.csv), csv_text)
        wrote = True
    if getattr(args, "json", ""):
        write_report(Path(args.json), json_text)
        wrote = True
    if wrote:
        print(f"Router-health admin export written (rows={export['measured']['row_count']}).")
        return 0
    print(json_text, end="")
    return 0


def cmd_router_health_evidence_pack(args: argparse.Namespace) -> int:
    from .. import cli
    from ..router_health import (
        IncompatibleExportError,
        build_router_health_evidence_pack,
        write_router_health_evidence_pack,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="router-health evidence-pack library root")
    if not args.input:
        print("No --input admin export provided.")
        return 2
    if not args.out:
        print("No --out directory provided for the evidence pack.")
        return 2
    try:
        pack = build_router_health_evidence_pack(Path(args.input))
    except IncompatibleExportError as exc:
        print(f"Rejected incompatible input: {exc}")
        return 2
    written = write_router_health_evidence_pack(pack, Path(args.out))
    print(json.dumps({
        "evidence_pack_written": True,
        "out_dir": str(args.out),
        "files": written,
        "reproducibility_hash": pack["reproducibility_hash"],
    }, indent=2))
    return 0


def cmd_router_health_verify_evidence_pack(args: argparse.Namespace) -> int:
    from .. import cli
    from ..router_health import verify_router_health_evidence_pack

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="router-health verify-evidence-pack library root")
    if not args.input:
        print("No --input evidence-pack directory provided.")
        return 2
    report = verify_router_health_evidence_pack(Path(args.input))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1
