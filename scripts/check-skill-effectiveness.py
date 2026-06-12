#!/usr/bin/env python
"""Run the deterministic A0 skill effectiveness gate."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unlimited_skills import cli
from unlimited_skills.skill_effectiveness import (
    effectiveness_report_to_json,
    evaluate_skill_effectiveness,
    write_fixture_library,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the A0 skill suggestion effectiveness gate.")
    parser.add_argument("--root", default="", help="Skill library root. Defaults to built-in fixture mode.")
    parser.add_argument("--gate", choices=["a0-merge", "v0.5-release"], default="a0-merge")
    parser.add_argument("--score-floor", type=float, default=3.0)
    parser.add_argument("--fixture-mode", action="store_true", help="Force the frozen built-in fixture library.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", default="", help="Write report JSON to this path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    use_fixture = args.fixture_mode or not args.root
    if use_fixture:
        with tempfile.TemporaryDirectory(prefix="unlimited-skills-a0-fixture-") as tmp:
            root = Path(tmp)
            write_fixture_library(root)
            cli.save_index(root)
            report = evaluate_skill_effectiveness(root, gate=args.gate, score_floor=args.score_floor, fresh=True)
    else:
        root = Path(args.root).expanduser()
        cli.enforce_local_root(root, action="check skill effectiveness")
        report = evaluate_skill_effectiveness(root, gate=args.gate, score_floor=args.score_floor, fresh=True)

    payload = effectiveness_report_to_json(report)
    if args.out:
        Path(args.out).expanduser().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Skill effectiveness gate: {report.status}")
        print(f"top_1_hit_rate: {report.top_1_hit_rate:.2%}")
        print(f"top_3_hit_rate: {report.top_3_hit_rate:.2%}")
        print(f"false_positive_rate: {report.false_positive_rate:.2%}")
        print(f"p90_suggest_latency_ms: {report.p90_suggest_latency_ms}")
        if report.failures:
            print("failures: " + ", ".join(report.failures))
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
