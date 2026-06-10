"""Local SkillOps diagnostics commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..skillops_usage_snapshot import build_usage_snapshot, format_usage_snapshot_text, usage_snapshot_explain


def cmd_skillops_usage_snapshot(args: argparse.Namespace) -> int:
    if getattr(args, "usage_snapshot_command", None) == "explain":
        print(usage_snapshot_explain())
        return 0
    root = Path(args.root).expanduser()
    snapshot = build_usage_snapshot(root, dry_run=args.dry_run)
    if args.out and not args.dry_run:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_usage_snapshot_text(snapshot))
        if args.out:
            print("Output write: " + ("skipped by dry-run" if args.dry_run else "done"))
    return 0
