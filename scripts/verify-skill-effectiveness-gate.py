#!/usr/bin/env python
"""Fail closed when skill invocation effectiveness is below threshold."""

from __future__ import annotations

import argparse
import contextlib
import io
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_runner():
    path = ROOT / "scripts" / "check-skill-effectiveness.py"
    spec = importlib.util.spec_from_file_location("check_skill_effectiveness", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load skill effectiveness runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify the skill effectiveness release gate.")
    parser.add_argument("--root", default="", help="Optional skill library root. Defaults to bundled packs.")
    parser.add_argument("--gate", choices=["a0-merge", "v0.5-release"], default="a0-merge")
    parser.add_argument("--report", default="", help="Write the JSON report to this path.")
    parser.add_argument("--record", action="store_true", help="Refresh evals/last-effectiveness-run.json.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report_path = Path(args.report) if args.report else ROOT / "build" / f"skill-effectiveness-{args.gate}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    runner = load_runner()
    runner_args = ["--json"]
    if args.root:
        runner_args.extend(["--root", args.root])
    if not args.record:
        runner_args.append("--no-record")
    if args.gate == "v0.5-release":
        runner_args.extend(
            [
                "--min-top1",
                "0.80",
                "--min-top3",
                "0.90",
                "--min-injection-precision",
                "0.95",
                "--max-p90-ms",
                "1200",
                "--max-p95-ms",
                "2000",
            ]
        )
    # The redirect target is kept explicit so the runner remains the single
    # implementation while this wrapper owns the persisted release artifact.
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = runner.main(runner_args)
    payload = json.loads(stdout.getvalue())
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if code != 0:
        failures = ", ".join(
            payload.get("failures") or payload.get("results", {}).get("failures", []) or []
        )
        raise SystemExit(f"Skill effectiveness gate failed for {args.gate}: {failures}")
    print(f"Skill effectiveness gate passed for {args.gate}: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
