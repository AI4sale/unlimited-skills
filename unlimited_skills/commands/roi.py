"""Local ROI receipt command wrappers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def cmd_roi_receipt(args: argparse.Namespace) -> int:
    from .. import cli
    from ..roi_receipt import (
        build_roi_receipt,
        format_roi_receipt_markdown,
        roi_receipt_json,
        write_receipt,
    )

    root = Path(args.root).expanduser()
    cli.enforce_local_root(root, action="roi receipt library root")
    try:
        receipt = build_roi_receipt(root, since=args.since)
    except ValueError as exc:
        print(f"roi receipt refused: {exc}", file=__import__("sys").stderr)
        return 2
    text = roi_receipt_json(receipt) if args.format == "json" else format_roi_receipt_markdown(receipt)
    if args.out:
        write_receipt(Path(args.out), text)
        print(json.dumps({"schema_version": 1, "written": True, "format": args.format}, indent=2) if args.json else f"ROI receipt written ({args.format}).")
        return 0
    print(text, end="")
    return 0
