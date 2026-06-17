"""Verify O065 shared candidate-family retrieval and ranking contracts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from unlimited_skills import suggest  # noqa: E402
from unlimited_skills.search_core import candidate_sources, shared_candidate_family, write_jsonl  # noqa: E402

ZERO_GATE_SCRIPT = REPO_ROOT / "scripts" / "verify-v065-zero-candidate-gates.py"


def _load_zero_gate_module():
    spec = importlib.util.spec_from_file_location("verify_v065_zero_candidate_gates", ZERO_GATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


zero_gate = _load_zero_gate_module()


def _run_suggest(root: Path, query: str, *, limit: int = 5) -> dict[str, Any]:
    from contextlib import redirect_stdout
    from io import StringIO

    buffer = StringIO()
    with redirect_stdout(buffer):
        rc = suggest.main([query, "--root", str(root), "--json", "--card", "--limit", str(limit)])
    text = buffer.getvalue().strip()
    payload = json.loads(text) if text else {}
    return {"returncode": rc, "payload": payload}


def _candidate_names(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row.get("name") or "") for row in rows if isinstance(row, dict) and row.get("name")]


def _mrr(ranked_names: list[str], expected: list[str]) -> float:
    expected_set = set(expected)
    for index, name in enumerate(ranked_names, start=1):
        if name in expected_set:
            return round(1.0 / index, 3)
    return 0.0


def _rank_row(root: Path, query_def: dict[str, Any]) -> dict[str, Any]:
    query = str(query_def["query"])
    expected = [str(item) for item in query_def.get("expected_family") or []]
    min_hook_candidates = int(query_def.get("min_hook_candidates") or 1)
    family_hits = shared_candidate_family(root, query, 10)
    family_names = [hit.name for hit in family_hits]
    family_sources = {hit.name: list(candidate_sources(hit)) for hit in family_hits}
    suggest_payload = _run_suggest(root, query, limit=5)["payload"]
    suggest_candidates = suggest_payload.get("top_3_skill_candidates") or []
    suggest_names = _candidate_names(suggest_candidates)
    missing_sources = [
        row.get("name")
        for row in suggest_candidates
        if isinstance(row, dict) and not row.get("candidate_sources")
    ]
    hook_report = zero_gate.build_report(root, [query_def], Path(tempfile.mkdtemp(prefix="uls-v065-shared-hook-")))
    hook_row = hook_report["rows"][0]
    hook_names = list(hook_row["user_prompt_submit"]["hook_candidates"])
    expected_hits = [name for name in expected if name in family_names]
    shared_family_missing = [name for name in expected if name not in set(family_names)]
    hook_missing = [name for name in expected[:min_hook_candidates] if name not in set(hook_names)]
    suggest_divergence = [name for name in suggest_names if name not in set(family_names)]
    hook_zero_with_family = bool(family_names) and not hook_names
    return {
        "id": query_def.get("id"),
        "query_summary_hash": suggest.task_summary_hash(query),
        "expected_family": expected,
        "family_top_10": family_names,
        "family_sources": family_sources,
        "suggest_top": suggest_names,
        "suggest_missing_candidate_sources": missing_sources,
        "hook_candidates": hook_names,
        "shared_family_missing": shared_family_missing,
        "suggest_divergence": suggest_divergence,
        "hook_zero_with_family": hook_zero_with_family,
        "hook_missing_required": hook_missing,
        "hit_at_3": bool(set(family_names[:3]) & set(expected)),
        "mrr": _mrr(family_names, expected),
        "expected_hits": expected_hits,
    }


def _learning_lift_probe(root: Path) -> dict[str, Any]:
    query = "write LinkedIn post"
    before = shared_candidate_family(root, query, 5)
    before_names = [hit.name for hit in before]
    target = "content-engine"
    learning_dir = root / ".learning"
    learning_dir.mkdir(parents=True, exist_ok=True)
    for _index in range(2):
        write_jsonl(learning_dir / "feedback.jsonl", {"name": target, "verdict": "accepted"})
    after = shared_candidate_family(root, query, 5)
    after_names = [hit.name for hit in after]
    target_after = next((hit for hit in after if hit.name == target), None)
    return {
        "query_summary_hash": suggest.task_summary_hash(query),
        "target": target,
        "before_top": before_names[:3],
        "after_top": after_names[:3],
        "target_has_learning_boost_source": bool(target_after and "learning_boost" in candidate_sources(target_after)),
        "rank_improved": before_names.index(target) > after_names.index(target)
        if target in before_names and target in after_names
        else False,
    }


def build_report(root: Path, *, read_only_root: bool) -> dict[str, Any]:
    queries = zero_gate.load_fixture()
    rows = [_rank_row(root, query_def) for query_def in queries]
    ranking = {
        "hit_at_3": round(sum(1 for row in rows if row["hit_at_3"]) / len(rows), 3) if rows else 0.0,
        "mean_reciprocal_rank": round(sum(float(row["mrr"]) for row in rows) / len(rows), 3) if rows else 0.0,
    }
    learning_lift = {"skipped": True, "reason": "read_only_root"} if read_only_root else _learning_lift_probe(root)
    failures = []
    for row in rows:
        if row["shared_family_missing"] and not read_only_root:
            failures.append({"id": row["id"], "reason": "shared_family_missing", "items": row["shared_family_missing"]})
        if row["suggest_divergence"]:
            failures.append({"id": row["id"], "reason": "suggest_not_from_shared_family", "items": row["suggest_divergence"]})
        if row["suggest_missing_candidate_sources"]:
            failures.append({"id": row["id"], "reason": "candidate_sources_missing", "items": row["suggest_missing_candidate_sources"]})
        if row["hook_zero_with_family"]:
            failures.append({"id": row["id"], "reason": "hook_zero_with_family"})
        if row["hook_missing_required"] and not read_only_root:
            failures.append({"id": row["id"], "reason": "hook_missing_required", "items": row["hook_missing_required"]})
    if not read_only_root and (not learning_lift.get("target_has_learning_boost_source") or not learning_lift.get("rank_improved")):
        failures.append({"id": "learning_lift", "reason": "learning_boost_not_visible_or_not_ranked"})
    if ranking["hit_at_3"] < 1.0 and not read_only_root:
        failures.append({"id": "ranking", "reason": "hit_at_3_below_1_0", "value": ranking["hit_at_3"]})
    if ranking["mean_reciprocal_rank"] <= 0.0 and not read_only_root:
        failures.append({"id": "ranking", "reason": "mrr_zero"})
    return {
        "ok": not failures,
        "schema_version": "v065-shared-candidate-family-v1",
        "root": str(root),
        "read_only_root": read_only_root,
        "query_count": len(rows),
        "ranking": ranking,
        "learning_lift": learning_lift,
        "failures": failures,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="", help="Skill library root. Defaults to a deterministic fixture.")
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="uls-v065-shared-family-") as tmp:
        tmp_path = Path(tmp)
        if args.root:
            root = Path(args.root).expanduser()
            read_only_root = True
        else:
            root = zero_gate.build_fixture_library(tmp_path / "library")
            read_only_root = False
        report = build_report(root, read_only_root=read_only_root)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            status = "PASS" if report["ok"] else "FAIL"
            print(
                f"C065 shared candidate-family verifier: {status} "
                f"({len(report['failures'])} failures, hit_at_3={report['ranking']['hit_at_3']}, "
                f"mrr={report['ranking']['mean_reciprocal_rank']})"
            )
            for row in report["rows"]:
                print(
                    f"- {row['id']}: family={row['family_top_10'][:5]} "
                    f"suggest={row['suggest_top'][:5]} hook={row['hook_candidates'][:5]}"
                )
        return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
