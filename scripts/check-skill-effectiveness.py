#!/usr/bin/env python3
"""Skill-suggestion effectiveness regression check (A0 standard).

Runs every frozen scenario from ``evals/invocation-scenarios.json`` through
the real cold ``suggest`` probe (one subprocess per scenario, exactly the way
agents and hooks invoke it) and reports:

- top-1 / top-3 hit rate on scenarios with expected skills;
- false-positive rate on the no-skill scenarios (any hit above the floor);
- wrong-ecosystem top-1 violations (``forbidden_top1`` lists);
- cold-probe latency p50/p90/max.

PASS/FAIL thresholds are calibrated against the bundled library (see
docs/adoption/skill-effectiveness-standard.md for the measured baseline).

Cadence contract («каждые 10 релизов прогоняется проверка эффективности»):
a full run records ``evals/last-effectiveness-run.json``; ``--cadence-check``
FAILS when 10 or more releases (release manifests in docs/releases/) have
shipped since the recorded run. Add ``--cadence-check`` to every release
checklist run (docs/release-process.md).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from unlimited_skills import __version__  # noqa: E402
from unlimited_skills.search_core import index_path, save_index  # noqa: E402

DEFAULT_SCENARIOS = REPO_ROOT / "evals" / "invocation-scenarios.json"
DEFAULT_RECORD = REPO_ROOT / "evals" / "last-effectiveness-run.json"
DEFAULT_RELEASES_DIR = REPO_ROOT / "docs" / "releases"
DEFAULT_ROOT = REPO_ROOT / "packs"

# Thresholds: calibrated 2026-06-12 against the bundled 267-skill library
# (measured: top-1 0.821, top-3 0.821, FP 0.000, p90 ~0.45 s cold; see
# docs/adoption/skill-effectiveness-standard.md). Thresholds sit below the
# measured numbers so the check fails on real regressions, not on noise.
DEFAULT_MIN_TOP3 = 0.60
DEFAULT_MAX_FP = 0.10
DEFAULT_MAX_P90_MS = 1500.0
DEFAULT_MAX_RELEASE_GAP = 10


def parse_version(text: str) -> tuple[int, ...] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", str(text or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def list_release_versions(releases_dir: Path) -> list[tuple[int, ...]]:
    versions = []
    for manifest in sorted(releases_dir.glob("*.release-manifest.json")):
        parsed = parse_version(manifest.name)
        if parsed:
            versions.append(parsed)
    return sorted(set(versions))


def cadence_check(record_path: Path, releases_dir: Path, max_gap: int) -> tuple[bool, str]:
    if not record_path.is_file():
        return False, (
            f"No recorded effectiveness run found at {record_path}. "
            "Run scripts/check-skill-effectiveness.py (full mode) and commit the record."
        )
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Effectiveness record is unreadable: {record_path} ({exc})"
    recorded_version = parse_version(record.get("version", ""))
    if not recorded_version:
        return False, f"Effectiveness record has no parseable version: {record_path}"
    releases = list_release_versions(releases_dir)
    gap = sum(1 for version in releases if version > recorded_version)
    recorded_str = ".".join(str(part) for part in recorded_version)
    if gap >= max_gap:
        return False, (
            f"FAIL: {gap} releases have shipped since the last recorded effectiveness run "
            f"(recorded at version {recorded_str}; limit is {max_gap - 1}). "
            "Run scripts/check-skill-effectiveness.py and commit evals/last-effectiveness-run.json."
        )
    return True, (
        f"OK: {gap} release(s) since the last recorded effectiveness run "
        f"(version {recorded_str}, {record.get('date', 'unknown date')}); limit {max_gap - 1}."
    )


def run_scenario(python_exe: str, root: Path, scenario: dict, limit: int, floor: float | None) -> dict:
    cmd = [python_exe, "-m", "unlimited_skills", "suggest", scenario["query"], "--root", str(root), "--json", "--limit", str(limit)]
    if floor is not None:
        cmd.extend(["--floor", str(floor)])
    started = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT))
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    hits: list[dict] = []
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
            if isinstance(payload, list):
                hits = [hit for hit in payload if isinstance(hit, dict)]
        except json.JSONDecodeError:
            hits = []

    expected = scenario.get("expected_skills") or []
    forbidden = scenario.get("forbidden_top1") or []
    expect_no_skill = bool(scenario.get("expect_no_skill"))
    hit_names = [str(hit.get("name") or "") for hit in hits]

    result = {
        "id": scenario["id"],
        "category": scenario.get("category", ""),
        "query": scenario["query"],
        "hits": hit_names,
        "elapsed_ms": round(elapsed_ms, 1),
        "expect_no_skill": expect_no_skill,
    }
    if expect_no_skill:
        result["false_positive"] = bool(hit_names)
    else:
        result["top1_hit"] = bool(hit_names) and hit_names[0] in expected
        result["top3_hit"] = any(name in expected for name in hit_names)
    if forbidden:
        result["forbidden_top1_violation"] = bool(hit_names) and hit_names[0] in forbidden
    return result


def _portable_path(path: Path) -> str:
    """Repo-relative when possible, so committed records carry no machine paths."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Skill-suggestion effectiveness regression check.")
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Skill library root (default: bundled packs).")
    parser.add_argument("--python", default=sys.executable, help="Python executable used to spawn the cold probe.")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--floor", type=float, default=None, help="Override the suggest score floor.")
    parser.add_argument("--min-top3", type=float, default=DEFAULT_MIN_TOP3)
    parser.add_argument("--max-fp", type=float, default=DEFAULT_MAX_FP)
    parser.add_argument("--max-p90-ms", type=float, default=DEFAULT_MAX_P90_MS)
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD, help="Where the run record is written.")
    parser.add_argument("--no-record", action="store_true", help="Do not write the run record.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cadence-check", action="store_true", help="Only verify the release-gap cadence; do not run scenarios.")
    parser.add_argument("--releases-dir", type=Path, default=DEFAULT_RELEASES_DIR)
    parser.add_argument("--max-release-gap", type=int, default=DEFAULT_MAX_RELEASE_GAP)
    args = parser.parse_args(argv)

    if args.cadence_check:
        ok, message = cadence_check(args.record, args.releases_dir, args.max_release_gap)
        print(json.dumps({"ok": ok, "message": message}, ensure_ascii=False) if args.json else message)
        return 0 if ok else 1

    scenarios_payload = json.loads(args.scenarios.read_text(encoding="utf-8"))
    scenarios = scenarios_payload["scenarios"]
    root = args.root.expanduser()
    if not index_path(root).is_file():
        save_index(root)

    results = [run_scenario(args.python, root, scenario, args.limit, args.floor) for scenario in scenarios]

    positives = [row for row in results if not row["expect_no_skill"]]
    negatives = [row for row in results if row["expect_no_skill"]]
    latencies = [row["elapsed_ms"] for row in results]
    top1_rate = sum(1 for row in positives if row["top1_hit"]) / len(positives) if positives else 0.0
    top3_rate = sum(1 for row in positives if row["top3_hit"]) / len(positives) if positives else 0.0
    fp_rate = sum(1 for row in negatives if row["false_positive"]) / len(negatives) if negatives else 0.0
    forbidden_violations = [row["id"] for row in results if row.get("forbidden_top1_violation")]
    p50 = percentile(latencies, 0.50)
    p90 = percentile(latencies, 0.90)

    passed = (
        top3_rate >= args.min_top3
        and fp_rate <= args.max_fp
        and p90 <= args.max_p90_ms
        and not forbidden_violations
    )

    summary = {
        "version": __version__,
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenarios_file": _portable_path(args.scenarios),
        "root": _portable_path(root),
        "scenario_count": len(results),
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "results": {
            "top1_hit_rate": round(top1_rate, 3),
            "top3_hit_rate": round(top3_rate, 3),
            "false_positive_rate": round(fp_rate, 3),
            "forbidden_top1_violations": forbidden_violations,
            "latency_ms": {"p50": round(p50, 1), "p90": round(p90, 1), "max": round(max(latencies), 1) if latencies else 0.0},
        },
        "thresholds": {
            "min_top3": args.min_top3,
            "max_fp": args.max_fp,
            "max_p90_ms": args.max_p90_ms,
        },
        "pass": passed,
        "scenarios": results,
    }

    if not args.no_record:
        record = {key: summary[key] for key in ("version", "date", "scenarios_file", "root", "scenario_count", "results", "thresholds", "pass")}
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for row in results:
            if row["expect_no_skill"]:
                status = "FP " if row["false_positive"] else "ok "
            elif row["top3_hit"]:
                status = "ok " if row["top1_hit"] else "top3"
            else:
                status = "MISS"
            if row.get("forbidden_top1_violation"):
                status = "FORB"
            print(f"{row['id']:>4} [{status}] {row['elapsed_ms']:7.1f} ms  {row['query'][:48]:<50} -> {', '.join(row['hits'][:3]) or '<silence>'}")
        print()
        print(f"top-1 hit rate:       {top1_rate:.3f}  ({len(positives)} positive scenarios)")
        print(f"top-3 hit rate:       {top3_rate:.3f}  (threshold >= {args.min_top3})")
        print(f"false-positive rate:  {fp_rate:.3f}  ({len(negatives)} no-skill scenarios, threshold <= {args.max_fp})")
        print(f"forbidden top-1:      {forbidden_violations or 'none'}")
        print(f"latency ms:           p50={p50:.1f} p90={p90:.1f} max={max(latencies):.1f}  (p90 threshold <= {args.max_p90_ms:.0f})")
        print(f"RESULT:               {'PASS' if passed else 'FAIL'}")
        if not args.no_record:
            print(f"record:               {args.record}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
