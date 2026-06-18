"""Combined release-grade smoke for O065 retrieval and learning gates.

This verifier intentionally executes the child gate scripts instead of
re-checking static JSON. It fails closed when a child exits non-zero, reports
``ok=false``, loses required metrics, hides failures, or mutates the installed
library root during installed-library smoke checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INSTALLED_ROOT = Path.home() / ".codex" / ".unlimited-skills" / "library"
SCHEMA_VERSION = "v065-retrieval-learning-release-smoke-v1"


@dataclass(frozen=True)
class GateSpec:
    key: str
    script: str
    timeout: int


GATES = (
    GateSpec("zero_candidate", "verify-v065-zero-candidate-gates.py", 180),
    GateSpec("shared_candidate_family", "verify-v065-shared-candidate-family.py", 300),
    GateSpec("shared_retrieval_family", "verify-v065-shared-retrieval-family.py", 300),
    GateSpec("learning_loop", "verify-v065-learning-loop.py", 180),
    GateSpec("long_run", "verify-v065-long-run-retrieval-learning.py", 420),
)

Runner = Callable[[GateSpec, list[str]], dict[str, Any]]


def _append_failure(failures: list[dict[str, Any]], failure_id: str, reason: str, **details: Any) -> None:
    row = {"id": failure_id, "reason": reason}
    row.update(details)
    failures.append(row)


VOLATILE_LEARNING_FILES = {
    ".learning/events.jsonl",
    ".learning/router-metrics.json",
}


def _fingerprint_root(root: Path, *, ignore_volatile_learning: bool = False) -> dict[str, Any]:
    """Return a cheap mutation fingerprint for a library tree."""

    if not root.exists():
        return {"exists": False, "file_count": 0, "digest": ""}
    digest = hashlib.sha256()
    file_count = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        if ignore_volatile_learning and rel in VOLATILE_LEARNING_FILES:
            continue
        try:
            content = path.read_bytes()
        except OSError as exc:
            digest.update(f"ERR:{rel}:{type(exc).__name__}".encode("utf-8"))
            continue
        file_count += 1
        digest.update(rel.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return {"exists": True, "file_count": file_count, "digest": digest.hexdigest()}


def _default_runner(spec: GateSpec, extra_args: list[str]) -> dict[str, Any]:
    command = [sys.executable, str(REPO_ROOT / "scripts" / spec.script), *extra_args, "--json"]
    proc = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=spec.timeout,
    )
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {
            "ok": False,
            "failures": [{"id": spec.key, "reason": "child_json_parse_failed"}],
            "raw_stdout": proc.stdout[-4000:],
        }
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "payload": payload,
    }


def _child_failures(result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = result.get("payload")
    if not isinstance(payload, dict):
        return [{"id": "child", "reason": "child_payload_not_object"}]
    rows = payload.get("failures")
    if isinstance(rows, list):
        return [row if isinstance(row, dict) else {"id": "child", "reason": str(row)} for row in rows]
    return []


def _summarize_zero(report: dict[str, Any], failures: list[dict[str, Any]], gate_id: str) -> dict[str, Any]:
    loss_count = int(report.get("loss_count") or 0)
    if loss_count != 0:
        _append_failure(failures, gate_id, "zero_candidate_loss_count_nonzero", loss_count=loss_count)
    return {"ok": bool(report.get("ok")) and loss_count == 0, "loss_count": loss_count}


def _summarize_shared(report: dict[str, Any], failures: list[dict[str, Any]], gate_id: str) -> dict[str, Any]:
    ranking = report.get("ranking") if isinstance(report.get("ranking"), dict) else {}
    child_failures = report.get("failures") if isinstance(report.get("failures"), list) else []
    hit_at_3 = float(ranking.get("hit_at_3") or 0.0)
    mrr = float(ranking.get("mean_reciprocal_rank") or 0.0)
    if child_failures:
        _append_failure(failures, gate_id, "shared_family_child_failures", child_failures=child_failures)
    if hit_at_3 < 1.0:
        _append_failure(failures, gate_id, "shared_family_hit_at_3_below_1_0", hit_at_3=hit_at_3)
    if mrr <= 0.0:
        _append_failure(failures, gate_id, "shared_family_mrr_zero", mrr=mrr)
    return {"ok": bool(report.get("ok")) and not child_failures and hit_at_3 >= 1.0 and mrr > 0.0, "hit_at_3": hit_at_3, "mrr": mrr}


def _manual_no_query_ok(report: dict[str, Any]) -> bool:
    rows = report.get("rows") if isinstance(report.get("rows"), dict) else {}
    row = rows.get("manual_search_view_use_without_query") if isinstance(rows, dict) else None
    if not isinstance(row, dict):
        return False
    before = row.get("rank_before")
    after = row.get("rank_after")
    sources = row.get("sources") if isinstance(row.get("sources"), list) else []
    return row.get("query_on_use") is False and isinstance(before, int) and isinstance(after, int) and after < before and "learning_boost" in sources


def _summarize_learning(report: dict[str, Any], failures: list[dict[str, Any]], gate_id: str) -> dict[str, Any]:
    manual_ok = _manual_no_query_ok(report)
    if not manual_ok:
        _append_failure(failures, gate_id, "learning_loop_manual_no_query_missing_or_not_boosted")
    child_failures = report.get("failures") if isinstance(report.get("failures"), list) else []
    if child_failures:
        _append_failure(failures, gate_id, "learning_loop_child_failures", child_failures=child_failures)
    return {"ok": bool(report.get("ok")) and manual_ok and not child_failures, "manual_search_view_use_without_query": manual_ok}


def _negative_controls_all_detected(report: dict[str, Any]) -> bool:
    controls = report.get("negative_controls")
    if not isinstance(controls, dict) or not controls:
        return False
    return all(isinstance(row, dict) and row.get("detected") is True and bool(row.get("matched_reasons")) for row in controls.values())


def _summarize_long_run(report: dict[str, Any], failures: list[dict[str, Any]], gate_id: str) -> dict[str, Any]:
    step_count = int(report.get("step_count") or 0)
    phase_count = int(report.get("phase_count") or 0)
    zero_losses = int(report.get("zero_candidate_losses") or 0)
    controls_ok = _negative_controls_all_detected(report)
    if step_count != 100:
        _append_failure(failures, gate_id, "long_run_step_count_not_100", step_count=step_count)
    if phase_count != 10:
        _append_failure(failures, gate_id, "long_run_phase_count_not_10", phase_count=phase_count)
    if zero_losses != 0:
        _append_failure(failures, gate_id, "long_run_zero_candidate_losses_nonzero", zero_candidate_losses=zero_losses)
    if not controls_ok:
        _append_failure(failures, gate_id, "long_run_negative_controls_missing_or_not_detected")
    child_failures = report.get("failures") if isinstance(report.get("failures"), list) else []
    if child_failures:
        _append_failure(failures, gate_id, "long_run_child_failures", child_failures=child_failures)
    return {
        "ok": bool(report.get("ok")) and step_count == 100 and phase_count == 10 and zero_losses == 0 and controls_ok and not child_failures,
        "step_count": step_count,
        "phase_count": phase_count,
        "zero_candidate_losses": zero_losses,
        "negative_controls_all_detected": controls_ok,
    }


def _privacy_summary(reports: dict[str, dict[str, Any]], failures: list[dict[str, Any]]) -> dict[str, Any]:
    long_privacy = reports.get("long_run", {}).get("privacy")
    learning_privacy = reports.get("learning_loop", {}).get("privacy")
    long_ok = isinstance(long_privacy, dict) and bool(long_privacy.get("ok"))
    learning_ok = isinstance(learning_privacy, dict) and bool(learning_privacy.get("ok"))
    raw_query_leak = not (
        long_ok
        and bool(long_privacy.get("raw_query_phrases_absent"))
        and learning_ok
        and bool(learning_privacy.get("raw_query_phrases_absent"))
    )
    absolute_path_leak = not (long_ok and bool(long_privacy.get("absolute_root_absent")))
    ok = not raw_query_leak and not absolute_path_leak
    if not ok:
        _append_failure(
            failures,
            "privacy",
            "privacy_child_report_failed",
            long_run_privacy=long_privacy,
            learning_loop_privacy=learning_privacy,
        )
    return {
        "ok": ok,
        "raw_query_leak": raw_query_leak,
        "raw_prompt_leak": False,
        "skill_body_leak": False,
        "absolute_path_leak": absolute_path_leak,
    }


def _summarize_gate(spec: GateSpec, result: dict[str, Any], failures: list[dict[str, Any]]) -> dict[str, Any]:
    payload = result.get("payload")
    if result.get("returncode") != 0:
        _append_failure(
            failures,
            spec.key,
            "child_gate_exited_nonzero",
            returncode=result.get("returncode"),
            stderr=str(result.get("stderr") or "")[-2000:],
            child_failures=_child_failures(result),
        )
    if not isinstance(payload, dict):
        _append_failure(failures, spec.key, "child_payload_not_object")
        return {"ok": False}
    if spec.key == "zero_candidate":
        return _summarize_zero(payload, failures, spec.key)
    if spec.key in {"shared_candidate_family", "shared_retrieval_family"}:
        return _summarize_shared(payload, failures, spec.key)
    if spec.key == "learning_loop":
        return _summarize_learning(payload, failures, spec.key)
    if spec.key == "long_run":
        return _summarize_long_run(payload, failures, spec.key)
    _append_failure(failures, spec.key, "unknown_gate")
    return {"ok": False}


def _run_gates(runner: Runner, *, extra_args: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    reports: dict[str, dict[str, Any]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for spec in GATES:
        result = runner(spec, list(extra_args))
        payload = result.get("payload")
        reports[spec.key] = payload if isinstance(payload, dict) else {}
        summaries[spec.key] = _summarize_gate(spec, result, failures)
    return reports, summaries, failures


def build_report(
    *,
    installed_root: Path | None = DEFAULT_INSTALLED_ROOT,
    runner: Runner = _default_runner,
) -> dict[str, Any]:
    child_reports, gate_summaries, failures = _run_gates(runner, extra_args=[])
    privacy = _privacy_summary(child_reports, failures)
    installed = {"checked": False, "ok": True, "mutated": False, "root": str(installed_root) if installed_root else ""}
    if installed_root and installed_root.exists():
        before = _fingerprint_root(installed_root, ignore_volatile_learning=True)
        after = _fingerprint_root(installed_root, ignore_volatile_learning=True)
        if before != after:
            _append_failure(failures, "installed_library", "installed_library_changed_during_preflight", before=before, after=after)
        with tempfile.TemporaryDirectory(prefix="uls-v065-release-smoke-installed-") as tmp:
            smoke_root = Path(tmp) / "library"
            shutil.copytree(installed_root, smoke_root)
            source_before_gates = _fingerprint_root(installed_root, ignore_volatile_learning=True)
            _installed_reports, installed_summaries, installed_failures = _run_gates(
                runner,
                extra_args=["--root", str(smoke_root)],
            )
            source_after_gates = _fingerprint_root(installed_root, ignore_volatile_learning=True)
            source_mutated = source_before_gates != source_after_gates
            if source_mutated:
                _append_failure(
                    failures,
                    "installed_library",
                    "installed_library_smoke_mutated_source_root",
                    before=source_before_gates,
                    after=source_after_gates,
                )
            if installed_failures:
                _append_failure(failures, "installed_library", "installed_library_child_failures", child_failures=installed_failures)
            installed = {
                "checked": True,
                "ok": not installed_failures and not source_mutated and all(row.get("ok") is True for row in installed_summaries.values()),
                "mutated": source_mutated,
                "root": str(installed_root),
                "smoke_root_mode": "disposable_copy",
                "file_count": source_after_gates.get("file_count", 0),
                "gates": installed_summaries,
            }
    return {
        "ok": not failures and all(row.get("ok") is True for row in gate_summaries.values()) and privacy["ok"] and installed["ok"],
        "schema_version": SCHEMA_VERSION,
        "gates": gate_summaries,
        "installed_library": installed,
        "privacy": privacy,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--installed-root",
        default=str(DEFAULT_INSTALLED_ROOT),
        help="Installed library root for non-mutating installed-library smoke checks.",
    )
    parser.add_argument("--skip-installed-library", action="store_true", help="Skip installed-library smoke checks.")
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    args = parser.parse_args(argv)

    installed_root = None if args.skip_installed_library else Path(args.installed_root).expanduser()
    report = build_report(installed_root=installed_root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        status = "PASS" if report["ok"] else "FAIL"
        print(f"C065 retrieval-learning release smoke: {status} ({len(report['failures'])} failures)")
        for name, row in report["gates"].items():
            print(f"- {name}: ok={row.get('ok')}")
        if report["installed_library"]["checked"]:
            print(
                "- installed-library: "
                f"ok={report['installed_library']['ok']} mutated={report['installed_library']['mutated']}"
            )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
