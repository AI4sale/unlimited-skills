"""Feedback report command wrappers."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def _legacy_record(args: argparse.Namespace) -> int:
    from . import library as library_cmds

    args.name = args.feedback_args[0] if args.feedback_args else getattr(args, "name", "")
    if not args.name:
        print("feedback record requires a skill name", file=__import__("sys").stderr)
        return 2
    if not args.verdict:
        print("feedback record requires --verdict accepted|rejected|neutral|missed|wrong", file=__import__("sys").stderr)
        return 2
    return library_cmds.cmd_feedback(args)


def cmd_feedback(args: argparse.Namespace) -> int:
    from ..feedback import (
        build_feedback_report,
        feedback_doctor_text,
        feedback_report_json,
        format_feedback_markdown,
        write_report,
    )

    action = args.feedback_args[0] if args.feedback_args else "record"
    if action not in {"prepare", "doctor", "record"}:
        return _legacy_record(args)
    if action == "record":
        args.feedback_args = args.feedback_args[1:]
        return _legacy_record(args)
    if action == "doctor":
        if args.json:
            payload = {
                "schema_version": 1,
                "status": "ok",
                "local_only": True,
                "telemetry": False,
                "auto_upload": False,
                "safe_commands": [
                    "unlimited-skills feedback prepare",
                    "unlimited-skills feedback prepare --include-usage-snapshot",
                ],
                "forbidden": [
                    "prompts",
                    "tool inputs",
                    "tool outputs",
                    "skill bodies",
                    "MCP schemas",
                    "launch commands",
                    "environment names or values",
                    "tokens",
                    "private keys",
                    "local absolute paths",
                    "raw .mcp.json",
                    "raw .claude.json",
                ],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(feedback_doctor_text())
        return 0
    root = Path(args.root).expanduser()
    report = build_feedback_report(root, include_usage_snapshot=args.include_usage_snapshot)
    output_format = args.format
    text = format_feedback_markdown(report) if output_format == "markdown" else feedback_report_json(report)
    if args.out:
        write_report(Path(args.out), text)
        if args.json:
            print(json.dumps({"schema_version": 1, "written": True, "format": output_format}, indent=2))
        else:
            print(f"Feedback report written ({output_format}).")
    else:
        print(text, end="")
    try:
        from .. import cli

        cli.write_jsonl(
            root / ".learning" / "feedback-prepare.jsonl",
            {
                "ts": time.time(),
                "type": "feedback_prepare",
                "include_usage_snapshot": bool(args.include_usage_snapshot),
                "format": output_format,
                "written": bool(args.out),
            },
        )
    except OSError:
        pass
    return 0
