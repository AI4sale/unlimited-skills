"""Learning Loop command wrappers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _emit(payload: dict) -> int:
    from ..learning_loop import assert_privacy_safe

    assert_privacy_safe(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_learning_doctor(args: argparse.Namespace) -> int:
    from ..learning_loop import learning_doctor

    root = Path(args.root).expanduser()
    return _emit(learning_doctor(root))


def cmd_improvement_candidates(args: argparse.Namespace) -> int:
    from ..learning_loop import build_improvement_candidates

    root = Path(args.root).expanduser()
    candidates = [candidate.to_json() for candidate in build_improvement_candidates(root)]
    payload = {
        "schema_version": 1,
        "status": "ok",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "message": "No improvement candidates found." if not candidates else "Improvement candidates generated from local feedback.",
        "privacy": {
            "local_only": True,
            "prompts_included": False,
            "raw_queries_included": False,
            "raw_notes_included": False,
            "skill_bodies_included": False,
            "local_paths_included": False,
            "tokens_included": False,
            "keys_included": False,
        },
    }
    return _emit(payload)


def cmd_apply_candidate(args: argparse.Namespace) -> int:
    from ..learning_loop import dry_run_candidate

    if not args.dry_run:
        print("apply-candidate currently supports --dry-run only; no files were modified.", file=__import__("sys").stderr)
        return 2
    root = Path(args.root).expanduser()
    return _emit(dry_run_candidate(root, args.candidate_id))


def cmd_learning_export(args: argparse.Namespace) -> int:
    from .. import cli
    from ..learning_tiers import (
        LEARNING_EXPORT_SCHEMA_VERSION,
        build_learning_export,
        learning_export_json,
    )
    from ..money_saved_meter import write_report

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="learning export library root")
    export = build_learning_export(root)
    text = learning_export_json(export)
    if args.out:
        write_report(Path(args.out), text)
        if getattr(args, "json_status", False):
            print(json.dumps({"schema_version": LEARNING_EXPORT_SCHEMA_VERSION, "written": True, "format": "json"}, indent=2))
        else:
            print(f"Learning export written ({args.out}).")
        return 0
    print(text, end="")
    return 0


def cmd_learning_team_rollup(args: argparse.Namespace) -> int:
    from .. import cli
    from ..learning_tiers import (
        LEARNING_TEAM_ROLLUP_SCHEMA_VERSION,
        IncompatibleExportError,
        build_learning_team_rollup,
        learning_team_rollup_json,
    )
    from ..money_saved_meter import write_report

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="learning team-rollup library root")
    inputs = [Path(p) for p in (args.input or [])]
    if not inputs:
        print("No --input exports provided. Pass one or more Registered learning export files.")
        return 2
    aliases = list(args.alias) if getattr(args, "alias", None) else None
    try:
        rollup = build_learning_team_rollup(inputs, aliases=aliases)
    except IncompatibleExportError as exc:
        print(f"Rejected incompatible input: {exc}")
        return 2
    text = learning_team_rollup_json(rollup)
    if args.out:
        write_report(Path(args.out), text)
        if getattr(args, "json_status", False):
            print(json.dumps({"schema_version": LEARNING_TEAM_ROLLUP_SCHEMA_VERSION, "written": True, "format": "json"}, indent=2))
        else:
            print(f"Learning team rollup written ({args.out}).")
        return 0
    print(text, end="")
    return 0


def cmd_learning_admin_export(args: argparse.Namespace) -> int:
    from .. import cli
    from ..learning_tiers import (
        IncompatibleExportError,
        build_learning_admin_export,
        learning_admin_export_csv,
        learning_admin_export_json,
    )
    from ..money_saved_meter import write_report

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="learning admin-export library root")
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
        export = build_learning_admin_export(Path(args.input), labels=labels)
    except IncompatibleExportError as exc:
        print(f"Rejected incompatible input: {exc}")
        return 2
    json_text = learning_admin_export_json(export)
    csv_text = learning_admin_export_csv(export)
    wrote = False
    if getattr(args, "csv", ""):
        write_report(Path(args.csv), csv_text)
        wrote = True
    if getattr(args, "json", ""):
        write_report(Path(args.json), json_text)
        wrote = True
    if wrote:
        print(f"Learning admin export written (rows={export['measured']['row_count']}).")
        return 0
    print(json_text, end="")
    return 0
