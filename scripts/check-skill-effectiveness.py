#!/usr/bin/env python3
"""Skill-suggestion effectiveness regression check (A0 standard).

Runs every frozen scenario from ``evals/invocation-scenarios.json`` through
the real cold ``suggest`` probe (one subprocess per scenario, exactly the way
agents and hooks invoke it) and reports:

- top-1 / top-3 hit rate on scenarios with expected skills;
- false-positive rate on the no-skill scenarios (any hit above the floor);
- wrong-ecosystem top-1 violations (``forbidden_top1`` lists);
- cold-probe latency p50/p90/p95/max (max is a warning, not a gate);
- F3b ambient-injection gates (probes run with ``--card``):
  ``injection_precision`` (tier-3 cards naming an expected skill / all cards
  shown) >= 0.90, ``negatives_injected`` = 0 (hard: no-skill scenarios must
  NEVER get a card), and every scenario marked ``expected_tier: 3`` must
  inject a card naming an expected skill;
- privacy invariants VERIFIED by scanning every actual probe output:
  ``no_prompt_upload`` (the task/query text never appears in suggest output,
  INCLUDING the card), ``no_local_path_leak`` (no absolute filesystem paths
  anywhere, INCLUDING the card), and ``no_unintended_body_leak`` (no skill
  body content outside the sanctioned tier-3 ``skill_card`` channel; the
  card carries the matched skill's body BY DESIGN and is excluded from the
  body scan only). All three must be true to PASS.

PASS/FAIL thresholds are the Hermes A0 merge-gate values (see
docs/adoption/skill-effectiveness-standard.md for the measured numbers).

Cadence contract («каждые 10 релизов прогоняется проверка эффективности»):
a full run records ``evals/last-effectiveness-run.json``; ``--cadence-check``
FAILS when 10 or more releases (release manifests in docs/releases/) have
shipped since the recorded run. Add ``--cadence-check`` to every release
checklist run (docs/release-process.md).
"""
from __future__ import annotations

import argparse
import json
import os
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

# Thresholds: the Hermes A0 merge-gate values (2026-06-12), set against the
# bundled 267-skill library (see docs/adoption/skill-effectiveness-standard.md
# for the measured numbers and the stricter v0.5 outlook). Thresholds sit
# below the measured numbers so the check fails on real regressions, not on
# noise. max latency over DEFAULT_WARN_MAX_MS is a WARNING only (cold-spawn
# outliers happen); repeated violations should be investigated.
DEFAULT_MIN_TOP1 = 0.70
DEFAULT_MIN_TOP3 = 0.85
DEFAULT_MAX_FP = 0.10
DEFAULT_MAX_P90_MS = 1500.0
DEFAULT_MAX_P95_MS = 2500.0
DEFAULT_WARN_MAX_MS = 5000.0
DEFAULT_MAX_RELEASE_GAP = 10
DEFAULT_MIN_POSITIVES = 30
DEFAULT_MIN_NEGATIVES = 10
# F3b ambient-injection gates: cards must overwhelmingly name the right
# skill, and a no-skill scenario receiving a card is an unconditional FAIL.
DEFAULT_MIN_INJECTION_PRECISION = 0.90
# The hook-side kill switch must never silently disable the injection gates
# during a checker run; it is stripped from the probe environment.
KILL_SWITCH_ENV = "UNLIMITED_SKILLS_NO_INJECT"

# Absolute filesystem path detector for the privacy scan: Windows drive paths
# (C:\..., C:/...; the (?!/) keeps protocol separators like :// out) and
# rooted POSIX user/system paths.
PATH_LEAK_RE = re.compile(
    r"[A-Za-z]:[\\/](?!/)\S|(?:^|[\s\"'(=\[,])/(?:home|users|usr|var|opt|tmp|mnt|etc)/",
    re.IGNORECASE,
)


def collect_body_snippets(root: Path) -> frozenset[str]:
    """Whitespace-normalized chunks of every indexed skill body.

    Used to VERIFY (not assume) that no skill body content appears in any
    probe output OUTSIDE the sanctioned tier-3 ``skill_card`` channel: if any
    chunk shows up in a suggest stdout with the card field removed, the
    ``no_unintended_body_leak`` invariant fails.
    """
    from unlimited_skills.search_core import load_records

    snippets: set[str] = set()
    for _hit, body in load_records(root):
        normalized = " ".join(str(body).split()).lower()
        if len(normalized) < 80:
            continue
        snippets.add(normalized[:120])
        middle = len(normalized) // 2
        chunk = normalized[middle : middle + 120]
        if len(chunk) >= 60:
            snippets.add(chunk)
    return frozenset(snippets)


def scan_privacy(raw_stdout: str, query: str, body_snippets: frozenset[str]) -> dict:
    """Scan one actual probe output for the three privacy invariants."""
    normalized_out = " ".join(raw_stdout.split()).lower()
    normalized_query = " ".join(query.split()).lower()
    return {
        "prompt_leak": bool(normalized_query) and normalized_query in normalized_out,
        "path_leak": bool(PATH_LEAK_RE.search(raw_stdout)),
        "body_leak": any(snippet in normalized_out for snippet in body_snippets),
    }


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


def scan_privacy_with_card(payload: dict | None, raw_stdout: str, query: str, body_snippets: frozenset[str]) -> dict:
    """Privacy scan honoring the sanctioned tier-3 card channel.

    The body scan runs over the output WITHOUT the ``skill_card`` field (the
    card carries the matched skill's body by design). The prompt-echo and
    path scans stay strict over EVERYTHING, card included: a card must never
    contain the query text or an absolute filesystem path.
    """
    if payload is None:
        return scan_privacy(raw_stdout, query, body_snippets)
    body_channel = {key: value for key, value in payload.items() if key != "skill_card"}
    privacy = scan_privacy(json.dumps(body_channel, ensure_ascii=False), query, body_snippets)
    card = payload.get("skill_card")
    card_text = str(card.get("card") or "") if isinstance(card, dict) else ""
    if card_text:
        normalized_card = " ".join(card_text.split()).lower()
        normalized_query = " ".join(query.split()).lower()
        if normalized_query and normalized_query in normalized_card:
            privacy["prompt_leak"] = True
        if PATH_LEAK_RE.search(card_text):
            privacy["path_leak"] = True
    return privacy


def run_scenario(python_exe: str, root: Path, scenario: dict, limit: int, floor: float | None, body_snippets: frozenset[str]) -> dict:
    cmd = [python_exe, "-m", "unlimited_skills", "suggest", scenario["query"], "--root", str(root), "--json", "--limit", str(limit), "--card"]
    if floor is not None:
        cmd.extend(["--floor", str(floor)])
    env = dict(os.environ)
    env.pop(KILL_SWITCH_ENV, None)  # the kill switch must not mask injection regressions
    started = time.perf_counter()
    # suggest emits UTF-8 (it reconfigures its stdout); card bodies may carry
    # non-ASCII, so never trust the Windows locale codepage here.
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=30, cwd=str(REPO_ROOT), env=env)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    hits: list[dict] = []
    reason_code = ""
    payload: dict | None = None
    tier = None
    card_skill = ""
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict):
                payload = parsed
                candidates = payload.get("top_3_skill_candidates")
                if isinstance(candidates, list):
                    hits = [hit for hit in candidates if isinstance(hit, dict)]
                reason_code = str(payload.get("reason_code") or "")
                tier = payload.get("delivery_tier")
                card = payload.get("skill_card")
                if isinstance(card, dict) and str(card.get("card") or "").strip():
                    card_skill = str(card.get("name") or "")
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
        "reason_code": reason_code,
        "elapsed_ms": round(elapsed_ms, 1),
        "expect_no_skill": expect_no_skill,
        "tier": tier,
        "card_skill": card_skill or None,
        "card_correct": bool(card_skill) and not expect_no_skill and card_skill in expected,
        "privacy": scan_privacy_with_card(payload, proc.stdout or "", scenario["query"], body_snippets),
    }
    if scenario.get("expected_tier") is not None:
        result["expected_tier"] = scenario["expected_tier"]
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
    parser.add_argument("--min-top1", type=float, default=DEFAULT_MIN_TOP1)
    parser.add_argument("--min-top3", type=float, default=DEFAULT_MIN_TOP3)
    parser.add_argument("--max-fp", type=float, default=DEFAULT_MAX_FP)
    parser.add_argument("--min-positives", type=int, default=DEFAULT_MIN_POSITIVES)
    parser.add_argument("--min-negatives", type=int, default=DEFAULT_MIN_NEGATIVES)
    parser.add_argument("--min-injection-precision", type=float, default=DEFAULT_MIN_INJECTION_PRECISION, help="Minimum share of tier-3 cards naming an expected skill (negatives_injected = 0 stays a hard gate).")
    parser.add_argument("--max-p90-ms", type=float, default=DEFAULT_MAX_P90_MS)
    parser.add_argument("--max-p95-ms", type=float, default=DEFAULT_MAX_P95_MS)
    parser.add_argument("--warn-max-ms", type=float, default=DEFAULT_WARN_MAX_MS, help="Max single-probe latency above which a WARNING (not a failure) is reported.")
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
    body_snippets = collect_body_snippets(root)

    results = [run_scenario(args.python, root, scenario, args.limit, args.floor, body_snippets) for scenario in scenarios]

    positives = [row for row in results if not row["expect_no_skill"]]
    negatives = [row for row in results if row["expect_no_skill"]]
    latencies = [row["elapsed_ms"] for row in results]
    top1_rate = sum(1 for row in positives if row["top1_hit"]) / len(positives) if positives else 0.0
    top3_rate = sum(1 for row in positives if row["top3_hit"]) / len(positives) if positives else 0.0
    fp_rate = sum(1 for row in negatives if row["false_positive"]) / len(negatives) if negatives else 0.0
    forbidden_violations = [row["id"] for row in results if row.get("forbidden_top1_violation")]
    p50 = percentile(latencies, 0.50)
    p90 = percentile(latencies, 0.90)
    p95 = percentile(latencies, 0.95)
    max_ms = max(latencies) if latencies else 0.0
    latency_warning = max_ms > args.warn_max_ms

    prompt_leaks = [row["id"] for row in results if row["privacy"]["prompt_leak"]]
    path_leaks = [row["id"] for row in results if row["privacy"]["path_leak"]]
    body_leaks = [row["id"] for row in results if row["privacy"]["body_leak"]]
    privacy = {
        "no_unintended_body_leak": not body_leaks,
        "no_prompt_upload": not prompt_leaks,
        "no_local_path_leak": not path_leaks,
    }

    # F3b ambient-injection gates (tier-3 skill cards).
    cards = [row for row in results if row.get("card_skill")]
    negatives_injected = [row["id"] for row in negatives if row.get("card_skill")]
    injection_precision = (sum(1 for row in cards if row["card_correct"]) / len(cards)) if cards else 1.0
    expected_tier3_misses = [row["id"] for row in results if row.get("expected_tier") == 3 and not row["card_correct"]]

    passed = (
        top1_rate >= args.min_top1
        and top3_rate >= args.min_top3
        and fp_rate <= args.max_fp
        and len(positives) >= args.min_positives
        and len(negatives) >= args.min_negatives
        and p90 <= args.max_p90_ms
        and p95 <= args.max_p95_ms
        and not forbidden_violations
        and injection_precision >= args.min_injection_precision
        and not negatives_injected
        and not expected_tier3_misses
        and all(privacy.values())
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
            "latency_ms": {"p50": round(p50, 1), "p90": round(p90, 1), "p95": round(p95, 1), "max": round(max_ms, 1)},
            "latency_max_warning": latency_warning,
            "cards_shown": len(cards),
            "injection_precision": round(injection_precision, 3),
            "negatives_injected": negatives_injected,
            "expected_tier3_misses": expected_tier3_misses,
            "privacy": privacy,
            "privacy_violations": {"prompt_upload": prompt_leaks, "local_path_leak": path_leaks, "unintended_body_leak": body_leaks},
        },
        "thresholds": {
            "min_top1": args.min_top1,
            "min_top3": args.min_top3,
            "max_fp": args.max_fp,
            "min_positives": args.min_positives,
            "min_negatives": args.min_negatives,
            "max_p90_ms": args.max_p90_ms,
            "max_p95_ms": args.max_p95_ms,
            "warn_max_ms": args.warn_max_ms,
            "min_injection_precision": args.min_injection_precision,
            "max_negatives_injected": 0,
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
            card_marker = f"  [card: {row['card_skill']}]" if row.get("card_skill") else ""
            print(f"{row['id']:>4} [{status}] {row['elapsed_ms']:7.1f} ms  {row['query'][:48]:<50} -> {', '.join(row['hits'][:3]) or '<silence>'}{card_marker}")
        print()
        print(f"top-1 hit rate:       {top1_rate:.3f}  ({len(positives)} positive scenarios, threshold >= {args.min_top1})")
        print(f"top-3 hit rate:       {top3_rate:.3f}  (threshold >= {args.min_top3})")
        print(f"false-positive rate:  {fp_rate:.3f}  ({len(negatives)} no-skill scenarios, threshold <= {args.max_fp})")
        print(f"forbidden top-1:      {forbidden_violations or 'none'}")
        print(f"cards shown (tier 3): {len(cards)}")
        print(f"injection precision:  {injection_precision:.3f}  (threshold >= {args.min_injection_precision})")
        print(f"negatives injected:   {negatives_injected or 'none'}  (hard gate: 0)")
        print(f"expected tier-3:      {'all hit' if not expected_tier3_misses else 'MISSES ' + str(expected_tier3_misses)}")
        print(f"latency ms:           p50={p50:.1f} p90={p90:.1f} p95={p95:.1f} max={max_ms:.1f}  (p90 <= {args.max_p90_ms:.0f}, p95 <= {args.max_p95_ms:.0f})")
        if latency_warning:
            print(f"WARNING:              max latency {max_ms:.1f} ms exceeds {args.warn_max_ms:.0f} ms (warning only; investigate if repeated)")
        print(f"privacy invariants:   no_unintended_body_leak={privacy['no_unintended_body_leak']} no_prompt_upload={privacy['no_prompt_upload']} no_local_path_leak={privacy['no_local_path_leak']}")
        if prompt_leaks or path_leaks or body_leaks:
            print(f"privacy violations:   prompt={prompt_leaks} paths={path_leaks} bodies={body_leaks}")
        print(f"RESULT:               {'PASS' if passed else 'FAIL'}")
        if not args.no_record:
            print(f"record:               {args.record}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
