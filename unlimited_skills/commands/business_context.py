"""CLI commands for the local business-context provider contract."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from unlimited_skills.business_context import (
    provider_doctor,
    retrieve_business_context,
    submit_completion_candidate,
)


def _emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif payload.get("context"):
        print(payload["context"])
    else:
        print(f"Business context provider: {payload.get('status', 'unknown')}")
    return 0


def cmd_context_retrieve(args: argparse.Namespace) -> int:
    return _emit(
        retrieve_business_context(
            args.query,
            agent=args.agent,
            config_path=Path(args.config).expanduser() if args.config else None,
        ),
        args.json,
    )


def cmd_context_completion(args: argparse.Namespace) -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return _emit(
        submit_completion_candidate(
            payload,
            config_path=Path(args.config).expanduser() if args.config else None,
        ),
        args.json,
    )


def cmd_context_doctor(args: argparse.Namespace) -> int:
    return _emit(
        provider_doctor(Path(args.config).expanduser() if args.config else None),
        args.json,
    )
