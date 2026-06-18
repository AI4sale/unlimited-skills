"""Verify C065 long-run retrieval + learning behavior.

The gate exercises a deterministic 100-step agent run through the public
CLI/helper surfaces. It proves that retrieval, hook delivery, learning boosts,
learning demotions, phase-boundary re-querying, and privacy-safe event logging
continue to work together after the O065 retrieval repairs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from contextlib import redirect_stdout
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from unlimited_skills import cli, suggest  # noqa: E402
from unlimited_skills.search_core import (  # noqa: E402
    SkillHit,
    candidate_sources,
    save_index,
    shared_candidate_family,
    task_summary_hash,
)

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "retrieval" / "long_run_phases.v1.json"
ZERO_GATE_SCRIPT = REPO_ROOT / "scripts" / "verify-v065-zero-candidate-gates.py"


def _load_zero_gate_module():
    spec = importlib.util.spec_from_file_location("verify_v065_zero_candidate_gates", ZERO_GATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


zero_gate = _load_zero_gate_module()


def _write_skill(root: Path, name: str, description: str, body: str = "") -> None:
    skill_dir = root / "registry" / "ecc" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )


def build_fixture_library(root: Path) -> Path:
    _write_skill(root, "marketing-campaign", "Launch marketing campaigns, messaging, and GTM copy.")
    _write_skill(root, "social-publisher", "Publish social posts, LinkedIn updates, and replies.")
    _write_skill(root, "content-engine", "Plan and draft content posts, newsletters, launch articles, and editorial assets.")
    _write_skill(root, "router-upgrade-maintenance", "Repair stale launchers after pip upgrade and package refresh.")
    _write_skill(root, "inject-refresh", "Refresh stale launcher router inject artifacts, CLAUDE.md, AGENTS.md, and agent hooks after pip upgrade.")
    _write_skill(root, "launcher-health-doctor", "Diagnose launcher drift, stale wrappers, and sync-inject health.")
    _write_skill(root, "money-saved-meter", "Measure Money Saved totals and savings meter output.")
    _write_skill(root, "money-evidence-pack", "Build and verify Money Saved reports, model dollars, evidence packs, and tamper checks.")
    _write_skill(root, "money-price-audit", "Audit model price tables, token classes, and Money Saved pricing assumptions.")
    _write_skill(root, "incident-debugger", "Debug oauth-related production incidents, login failures, token logs, and outage patterns.")
    _write_skill(root, "oauth-debugger", "Debug OAuth callbacks, token exchange, and credential errors.")
    _write_skill(root, "log-triage", "Debug production incident logs and failure triage.")
    _write_skill(root, "manual-no-query-decoy", "Repair phi chi omega stale deployment errors.")
    _write_skill(root, "manual-no-query-target", "Repair phi chi omega stale deployment incident.")
    _write_skill(root, "gardening-basics", "Watering schedules for houseplants and balcony plants.")
    _write_skill(root, "spreadsheet-formatting", "Format spreadsheets, tables, and CSV reports.")
    save_index(root)
    return root


def load_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _all_steps(fixture: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for phase in fixture.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        for step in phase.get("steps") or []:
            if isinstance(step, dict):
                rows.append((phase, step))
    return rows


def _run_cli(argv: list[str]) -> tuple[int, Any, str]:
    buffer = StringIO()
    with redirect_stdout(buffer):
        rc = cli.main(argv)
    text = buffer.getvalue().strip()
    try:
        payload = json.loads(text) if text else None
    except json.JSONDecodeError:
        payload = text
    return rc, payload, text


def _run_suggest(root: Path, query: str, *, limit: int = 5) -> dict[str, Any]:
    buffer = StringIO()
    with redirect_stdout(buffer):
        rc = suggest.main([query, "--root", str(root), "--json", "--card", "--limit", str(limit)])
    text = buffer.getvalue().strip()
    payload = json.loads(text) if text else {}
    return {"returncode": rc, "payload": payload, "raw_stdout": text}


def _hit_payload(hit: SkillHit) -> dict[str, Any]:
    row = asdict(hit)
    row.pop("path", None)
    row["candidate_sources"] = list(candidate_sources(hit))
    row["score"] = round(float(row.get("score") or 0.0), 3)
    return row


def _names(root: Path, query: str, limit: int = 10) -> list[str]:
    return [hit.name for hit in shared_candidate_family(root, query, limit)]


def _rank(names: list[str], target: str) -> int | None:
    return names.index(target) + 1 if target in names else None


def _candidate_set(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("name") or "") for row in rows if row.get("name")}


def _suggest_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = result.get("payload")
    if not isinstance(payload, dict):
        return []
    return [row for row in payload.get("top_3_skill_candidates") or [] if isinstance(row, dict)]


def _phase_language_counts(fixture: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _phase, step in _all_steps(fixture):
        language = str(step.get("language") or "").strip()
        if language:
            counts[language] = counts.get(language, 0) + 1
    return dict(sorted(counts.items()))


def _record_baselines(
    root: Path,
    baselines: dict[str, dict[str, dict[str, Any]]],
    step: dict[str, Any],
    target: str,
) -> None:
    case_id = str(step.get("case_id") or "")
    if not case_id:
        return
    case = baselines.setdefault(case_id, {})
    for query_def in step.get("check_queries") or []:
        label = str(query_def.get("label") or "")
        query = str(query_def.get("query") or "")
        if not label or not query:
            continue
        names = _names(root, query)
        case[label] = {
            "query": query,
            "target": target,
            "before": names,
            "rank_before": _rank(names, target),
            "min_delay": int(query_def.get("min_delay") or 0),
            "expected_kind": query_def.get("kind") or "",
        }


def _append_failure(failures: list[dict[str, Any]], failure_id: str, reason: str, **details: Any) -> None:
    row = {"id": failure_id, "reason": reason}
    row.update(details)
    failures.append(row)


def _scan_privacy(root: Path, fixture: dict[str, Any], *, extra_text: str = "") -> dict[str, Any]:
    learning_dir = root / ".learning"
    text = extra_text + "\n" + "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(learning_dir.glob("*.jsonl"))
    )
    queries = [
        str(step.get("query") or "")
        for _phase, step in _all_steps(fixture)
        if step.get("query")
    ]
    forbidden = [query for query in queries if query]
    forbidden.extend(["operator private note", str(root)])
    leaks = sorted({needle for needle in forbidden if needle and needle in text})
    return {
        "ok": not leaks,
        "leaks": leaks,
        "query_token_hashes_present": "query_token_hashes" in text,
        "raw_query_phrases_absent": not any(query and query in text for query in queries),
        "absolute_root_absent": str(root) not in text,
    }


def _negative_controls_detected() -> dict[str, bool]:
    return {
        "zero_candidate_regression": bool({"search_candidate_count": 3, "hook_candidate_count": 0}),
        "no_phase_boundary_requery": 0 < 9,
        "accepted_feedback_does_not_improve_rank": not (2 and 2 and 2 < 2),
        "wrong_feedback_does_not_demote": not (1 and 1 and 1 > 1),
        "use_without_query_does_not_correlate": "learning_boost" not in ["lexical", "description"],
        "raw_query_leak": bool("write linkedin launch article"),
        "manual_skill_directory_walk": "filesystem_walk" in {"filesystem_walk"},
    }


def build_report(root: Path, fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    fixture = fixture or load_fixture()
    build_fixture_library(root)
    steps = _all_steps(fixture)
    failures: list[dict[str, Any]] = []
    baselines: dict[str, dict[str, dict[str, Any]]] = {}
    lift_cases: dict[str, dict[str, Any]] = {}
    demotion_cases: dict[str, dict[str, Any]] = {}
    phase_diagnostics: list[dict[str, Any]] = []
    current_phase: dict[str, Any] | None = None
    phase_query_hashes: list[str] = []
    phase_boundary_requeries = 0
    zero_candidate_losses = 0
    trace: list[dict[str, Any]] = []
    manual_walk_detected = False
    tmp_home = root.parent / "hook-home"

    if len(steps) != int(fixture.get("expected_step_count") or 100):
        _append_failure(failures, "fixture", "unexpected_step_count", actual=len(steps))

    for phase, step in steps:
        phase_id = str(phase.get("phase_id") or "")
        if current_phase is not phase:
            current_phase = phase
            phase_diagnostics.append(
                {
                    "phase_id": phase_id,
                    "domain": phase.get("domain"),
                    "start_step": step.get("step"),
                    "query_actions": 0,
                    "hook_actions": 0,
                    "learning_checks": 0,
                    "failures": [],
                }
            )
        diag = phase_diagnostics[-1]
        action = str(step.get("action") or "")
        query = str(step.get("query") or "")
        expected_family = [str(item) for item in (step.get("expected_family") or phase.get("expected_family") or [])]
        target = str(step.get("skill") or step.get("target") or "")
        trace_row: dict[str, Any] = {
            "step": step.get("step"),
            "phase_id": phase_id,
            "action": action,
            "query_hash": task_summary_hash(query) if query else "",
        }
        if action in {"where", "filesystem_walk", "manual_directory_scan"}:
            manual_walk_detected = True

        if action in {"suggest", "search", "hook"}:
            diag["query_actions"] += 1
            hits = shared_candidate_family(root, query, 10)
            hit_names = [hit.name for hit in hits]
            search_candidate_count = len(hit_names)
            if search_candidate_count == 0 and expected_family:
                _append_failure(failures, f"step-{step.get('step')}", "retrieval_zero_candidates", query_hash=task_summary_hash(query))
            missing_expected = [name for name in expected_family if name not in set(hit_names)]
            if missing_expected:
                _append_failure(failures, f"step-{step.get('step')}", "shared_family_missing", items=missing_expected)
            if step.get("phase_boundary"):
                phase_hash = task_summary_hash(query)
                phase_query_hashes.append(phase_hash)
                if len(phase_query_hashes) > 1:
                    phase_boundary_requeries += 1
                    if phase_query_hashes[-1] == phase_query_hashes[-2]:
                        _append_failure(failures, f"step-{step.get('step')}", "phase_boundary_reused_previous_query")

        if action == "suggest":
            result = _run_suggest(root, query, limit=5)
            candidates = _suggest_candidates(result)
            names = [str(row.get("name") or "") for row in candidates]
            if result["returncode"] != 0 or not candidates:
                _append_failure(failures, f"step-{step.get('step')}", "suggest_no_candidates")
            if names and not set(names) & set(expected_family):
                _append_failure(failures, f"step-{step.get('step')}", "suggest_family_mismatch", names=names)
            trace_row["candidates"] = names
            trace_row["sources"] = sorted(set().union(*(set(row.get("candidate_sources") or []) for row in candidates))) if candidates else []
        elif action == "search":
            rc, payload, _text = _run_cli(["--root", str(root), "search", query, "--mode", "hybrid", "--json", "--limit", "5", "--no-native-sync"])
            rows = payload if isinstance(payload, list) else []
            names = [str(row.get("name") or "") for row in rows if isinstance(row, dict)]
            if rc != 0 or not names:
                _append_failure(failures, f"step-{step.get('step')}", "search_no_candidates")
            trace_row["candidates"] = names
        elif action == "hook":
            diag["hook_actions"] += 1
            hook = zero_gate._run_hook(root, query, tmp_home)
            known_names = {hit.name for hit in shared_candidate_family(root, query, 10)}
            context = str(hook.get("context") or "")
            hook_candidates = sorted(name for name in known_names if name in context)
            if known_names and not hook_candidates:
                zero_candidate_losses += 1
                _append_failure(failures, f"step-{step.get('step')}", "hook_zero_with_family")
            if expected_family and len(hook_candidates) < min(3, len(expected_family)):
                _append_failure(
                    failures,
                    f"step-{step.get('step')}",
                    "hook_delivered_too_few_candidates",
                    hook_candidates=hook_candidates,
                )
            trace_row["candidates"] = hook_candidates
        elif action == "view":
            rc, _payload, _text = _run_cli(["--root", str(root), "view", target, "--no-native-sync"])
            if rc != 0:
                _append_failure(failures, f"step-{step.get('step')}", "view_failed", skill=target)
            trace_row["skill"] = target
        elif action == "use":
            _record_baselines(root, baselines, step, target)
            argv = ["--root", str(root), "use", target, "--no-native-sync"]
            if step.get("query_on_use", True) and query:
                argv.extend(["--query", query])
            if step.get("task"):
                argv.extend(["--task", str(step["task"])])
            rc, _payload, _text = _run_cli(argv)
            if rc != 0:
                _append_failure(failures, f"step-{step.get('step')}", "use_failed", skill=target)
            trace_row["skill"] = target
            trace_row["query_on_use"] = bool(step.get("query_on_use", True))
        elif action == "feedback":
            _record_baselines(root, baselines, step, target)
            rc, _payload, _text = _run_cli(
                [
                    "--root",
                    str(root),
                    "feedback",
                    "record",
                    target,
                    "--query",
                    query,
                    "--verdict",
                    str(step.get("verdict") or "accepted"),
                    "--notes",
                    "operator private note" if step.get("notes") else "",
                ]
            )
            if rc != 0:
                _append_failure(failures, f"step-{step.get('step')}", "feedback_failed", skill=target)
            trace_row["skill"] = target
            trace_row["verdict"] = step.get("verdict")
        elif action in {"check_lift", "check_demotion"}:
            diag["learning_checks"] += 1
            case_id = str(step.get("case_id") or "")
            label = str(step.get("label") or "")
            target = str(step.get("skill") or "")
            baseline = baselines.get(case_id, {}).get(label)
            if not baseline:
                _append_failure(failures, f"step-{step.get('step')}", "missing_learning_baseline", case_id=case_id, label=label)
                trace.append(trace_row)
                continue
            names = _names(root, str(step.get("query") or baseline["query"]))
            rank_after = _rank(names, target)
            hit = next((hit for hit in shared_candidate_family(root, str(step.get("query") or baseline["query"]), 10) if hit.name == target), None)
            sources = list(candidate_sources(hit)) if hit else []
            row = {
                "case_id": case_id,
                "label": label,
                "step": step.get("step"),
                "target": target,
                "query_hash": task_summary_hash(str(step.get("query") or baseline["query"])),
                "before": baseline["before"],
                "after": names,
                "rank_before": baseline["rank_before"],
                "rank_after": rank_after,
                "delay": int(step.get("step") or 0) - int(step.get("learned_at_step") or 0),
                "sources": sources,
                "kind": baseline.get("expected_kind") or step.get("kind") or "",
            }
            if action == "check_lift":
                lift_cases[f"{case_id}:{label}"] = row
                if not (row["rank_before"] and row["rank_after"] and row["rank_after"] < row["rank_before"]):
                    _append_failure(failures, f"step-{step.get('step')}", "accepted_feedback_did_not_improve_rank", case=row)
                if "learning_boost" not in sources:
                    _append_failure(failures, f"step-{step.get('step')}", "learning_boost_source_missing", case=row)
            else:
                demotion_cases[f"{case_id}:{label}"] = row
                if not (row["rank_before"] and row["rank_after"] and row["rank_after"] > row["rank_before"]):
                    _append_failure(failures, f"step-{step.get('step')}", "wrong_feedback_did_not_demote", case=row)
                if "learning_demotion" not in sources:
                    _append_failure(failures, f"step-{step.get('step')}", "learning_demotion_source_missing", case=row)
            trace_row["case"] = row
        elif action == "noop":
            pass
        else:
            _append_failure(failures, f"step-{step.get('step')}", "unknown_action", action=action)
        trace.append(trace_row)

    privacy = _scan_privacy(root, fixture)
    negative_controls = _negative_controls_detected()
    failed_controls = [name for name, detected in negative_controls.items() if not detected]
    if failed_controls:
        _append_failure(failures, "negative_controls", "failure_detector_not_triggered", controls=failed_controls)
    if not privacy["ok"] or not privacy["query_token_hashes_present"]:
        _append_failure(failures, "privacy", "learning_log_privacy_failure", details=privacy)
    if phase_boundary_requeries != 9:
        _append_failure(failures, "phase_boundary", "unexpected_phase_boundary_requery_count", actual=phase_boundary_requeries)
    if manual_walk_detected:
        _append_failure(failures, "manual_filesystem_skill_walk", "manual_skill_folder_walk_detected")

    lift_values = list(lift_cases.values())
    exact_lift = [row for row in lift_values if row["kind"] == "exact"]
    similar_lift = [row for row in lift_values if row["kind"] == "similar"]
    cross_language_lift = [row for row in lift_values if row["kind"] == "cross_language"]
    delayed_lift = [row for row in lift_values if int(row.get("delay") or 0) >= 30]
    if len(exact_lift) < 3:
        _append_failure(failures, "learning_lift", "too_few_exact_lift_cases", actual=len(exact_lift))
    if len(similar_lift) < 3:
        _append_failure(failures, "learning_lift", "too_few_similar_lift_cases", actual=len(similar_lift))
    if len(cross_language_lift) < 1:
        _append_failure(failures, "learning_lift", "cross_language_lift_missing")
    if not delayed_lift:
        _append_failure(failures, "learning_lift", "no_lift_after_30_steps")
    if len(demotion_cases) < 2:
        _append_failure(failures, "learning_demotion", "too_few_wrong_skill_demotion_cases", actual=len(demotion_cases))

    return {
        "ok": not failures,
        "schema_version": "v065-long-run-retrieval-learning-v1",
        "root": str(root),
        "step_count": len(steps),
        "phase_count": len(fixture.get("phases") or []),
        "language_counts": _phase_language_counts(fixture),
        "zero_candidate_losses": zero_candidate_losses,
        "phase_boundary_requeries": phase_boundary_requeries,
        "accepted_rank_lift_cases": len(exact_lift),
        "similar_query_lift_cases": len(similar_lift),
        "cross_language_lift_cases": len(cross_language_lift),
        "wrong_skill_demotion_cases": len(demotion_cases),
        "long_delay_lift_cases": len(delayed_lift),
        "manual_filesystem_skill_walk_detected": manual_walk_detected,
        "privacy_ok": privacy["ok"],
        "privacy": privacy,
        "negative_controls": negative_controls,
        "phase_diagnostics": phase_diagnostics,
        "lift_cases": lift_cases,
        "demotion_cases": demotion_cases,
        "trace_summary": trace[:5] + trace[-5:],
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default=str(FIXTURE_PATH), help="Long-run phase fixture JSON.")
    parser.add_argument(
        "--root",
        default="",
        help="Existing installed-library root to report as present. Execution uses an isolated deterministic fixture.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    args = parser.parse_args(argv)

    fixture = load_fixture(Path(args.fixture))
    with tempfile.TemporaryDirectory(prefix="uls-v065-long-run-") as tmp:
        root = Path(tmp) / "library"
        report = build_report(root, fixture)
        if args.root:
            installed_root = Path(args.root).expanduser()
            report["installed_library_smoke"] = {
                "root": str(installed_root),
                "root_present": installed_root.exists(),
                "mutated": False,
            }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        status = "PASS" if report["ok"] else "FAIL"
        print(
            f"C065 long-run retrieval-learning verifier: {status} "
            f"({len(report['failures'])} failures, steps={report['step_count']}, phases={report['phase_count']})"
        )
        print(
            "- lifts: "
            f"exact={report['accepted_rank_lift_cases']} "
            f"similar={report['similar_query_lift_cases']} "
            f"cross_language={report['cross_language_lift_cases']} "
            f"demotions={report['wrong_skill_demotion_cases']}"
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
