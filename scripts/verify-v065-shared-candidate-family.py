"""Verify O065 shared candidate-family retrieval and ranking contracts."""

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
    candidate_debug_payload,
    candidate_sources,
    load_records,
    save_index,
    shared_candidate_family,
    write_jsonl,
)

ZERO_GATE_SCRIPT = REPO_ROOT / "scripts" / "verify-v065-zero-candidate-gates.py"


def _load_zero_gate_module():
    spec = importlib.util.spec_from_file_location("verify_v065_zero_candidate_gates", ZERO_GATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


zero_gate = _load_zero_gate_module()


def _hit_payload(hit: SkillHit) -> dict[str, Any]:
    row = asdict(hit)
    row.pop("path", None)
    row.update(candidate_debug_payload(hit))
    row["score"] = round(float(row.get("score") or 0.0), 3)
    return row


def _run_suggest(root: Path, query: str, *, limit: int = 5) -> dict[str, Any]:
    buffer = StringIO()
    with redirect_stdout(buffer):
        rc = suggest.main([query, "--root", str(root), "--json", "--card", "--limit", str(limit)])
    text = buffer.getvalue().strip()
    payload = json.loads(text) if text else {}
    return {"returncode": rc, "payload": payload, "raw_stdout": text}


def _run_search_json(root: Path, query: str, *, limit: int = 10) -> dict[str, Any]:
    buffer = StringIO()
    with redirect_stdout(buffer):
        rc = cli.main(
            [
                "--root",
                str(root),
                "search",
                query,
                "--mode",
                "hybrid",
                "--json",
                "--limit",
                str(limit),
                "--no-native-sync",
            ]
        )
    text = buffer.getvalue().strip()
    try:
        payload = json.loads(text) if text else []
    except json.JSONDecodeError:
        payload = None
    return {"returncode": rc, "payload": payload, "raw_stdout": text}


def _candidate_names(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row.get("name") or "") for row in rows if isinstance(row, dict) and row.get("name")]


def _payload_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = result.get("payload")
    if not isinstance(payload, dict):
        return []
    return [row for row in payload.get("top_3_skill_candidates") or [] if isinstance(row, dict)]


def _search_payload_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = result.get("payload")
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _mrr(ranked_names: list[str], expected: list[str]) -> float:
    expected_set = set(expected)
    for index, name in enumerate(ranked_names, start=1):
        if name in expected_set:
            return round(1.0 / index, 3)
    return 0.0


def _required_family(expected: list[str], hybrid_names: list[str], min_hook_candidates: int, *, read_only_root: bool) -> list[str]:
    if expected and not read_only_root:
        return expected[:min_hook_candidates]
    return hybrid_names[:min_hook_candidates]


def _rank_row(root: Path, query_def: dict[str, Any], *, read_only_root: bool) -> dict[str, Any]:
    query = str(query_def["query"])
    expected = [str(item) for item in query_def.get("expected_family") or []]
    min_hook_candidates = int(query_def.get("min_hook_candidates") or 1)
    hybrid_hits = cli.hybrid_search(root, query, 10, cli.DEFAULT_EMBED_MODEL, None, False, False)
    hybrid_rows = [_hit_payload(hit) for hit in hybrid_hits]
    hybrid_names = [hit.name for hit in hybrid_hits]
    hybrid_sources = {hit.name: list(candidate_sources(hit)) for hit in hybrid_hits}
    search_json = _run_search_json(root, query, limit=10)
    search_rows = _search_payload_rows(search_json)
    search_names = _candidate_names(search_rows)
    suggest_card = _run_suggest(root, query, limit=5)
    suggest_candidates = _payload_candidates(suggest_card)
    suggest_names = _candidate_names(suggest_candidates)
    missing_suggest_sources = [row.get("name") for row in suggest_candidates if not row.get("candidate_sources")]
    missing_search_sources = [row.get("name") for row in search_rows if row.get("name") and not row.get("candidate_sources")]

    hook_report = zero_gate.build_report(root, [query_def], Path(tempfile.mkdtemp(prefix="uls-v065-shared-hook-")))
    hook_row = hook_report["rows"][0]
    hook_names = list(hook_row["user_prompt_submit"]["hook_candidates"])

    required = _required_family(expected, hybrid_names, min_hook_candidates, read_only_root=read_only_root)
    expected_hits = [name for name in expected if name in hybrid_names]
    shared_family_missing = [name for name in expected if name not in set(hybrid_names)]
    suggest_divergence = [name for name in suggest_names if name not in set(hybrid_names)]
    search_json_divergence = [name for name in search_names if name not in set(hybrid_names)]
    hook_zero_with_family = bool(hybrid_names) and not hook_names
    hook_missing = [name for name in required if name not in set(hook_names)]
    hybrid_suggest_overlap = bool(set(hybrid_names) & set(suggest_names))
    hybrid_hook_overlap = bool(set(hybrid_names) & set(hook_names))
    vector_status = None
    payload = suggest_card.get("payload")
    if isinstance(payload, dict):
        vector_status = payload.get("vector_status")

    return {
        "id": query_def.get("id"),
        "query_summary_hash": suggest.task_summary_hash(query),
        "expected_family": expected,
        "required_hook_family": required,
        "hybrid_top_10": hybrid_names,
        "hybrid_rows": hybrid_rows,
        "hybrid_sources": hybrid_sources,
        "search_json_top_10": search_names,
        "suggest_top": suggest_names,
        "suggest_vector_status": vector_status,
        "hook_candidates": hook_names,
        "shared_family_missing": shared_family_missing,
        "suggest_divergence": suggest_divergence,
        "search_json_divergence": search_json_divergence,
        "suggest_missing_candidate_sources": missing_suggest_sources,
        "search_missing_candidate_sources": missing_search_sources,
        "hybrid_suggest_overlap": hybrid_suggest_overlap,
        "hybrid_hook_overlap": hybrid_hook_overlap,
        "hook_zero_with_family": hook_zero_with_family,
        "hook_missing_required": hook_missing,
        "hit_at_3": bool(set(hybrid_names[:3]) & set(expected)) if expected else bool(hybrid_names[:3]),
        "mrr": _mrr(hybrid_names, expected) if expected else (1.0 if hybrid_names else 0.0),
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


def _write_vector_sidecar(root: Path, query: str, embeddings: dict[str, list[float]]) -> None:
    records = []
    for hit, _body in load_records(root):
        records.append(
            {
                "name": hit.name,
                "description": hit.description,
                "collection": hit.collection,
                "path": hit.path,
                "embedding": embeddings.get(hit.name, [0.0, 1.0]),
            }
        )
    payload = {
        "schema_version": 1,
        "model": cli.DEFAULT_EMBED_MODEL,
        "query_embeddings": {
            suggest.task_summary_hash(query): [1.0, 0.0],
            " ".join(query.split()).lower(): [1.0, 0.0],
        },
        "records": records,
    }
    cli.vector_sidecar_path(root).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_vector_only_fixture(root: Path) -> tuple[Path, str, str]:
    query = "quasar nebula routing"
    target = "semantic-vector-target"
    zero_gate._write_skill(root, target, "Handles hidden workflow handoff.", "No query words appear in this skill.")
    zero_gate._write_skill(root, "lexical-decoy", "quasar nebula placeholder unrelated to routing quality.")
    save_index(root)
    _write_vector_sidecar(root, query, {target: [1.0, 0.0], "lexical-decoy": [0.0, 1.0]})
    return root, query, target


def _vector_only_probe(tmp_path: Path) -> dict[str, Any]:
    root, query, target = _build_vector_only_fixture(tmp_path / "vector-only-library")
    lexical_hits = cli.lexical_search(root, query, 5)
    vector_hits = cli.vector_search(root, query, 5, cli.DEFAULT_EMBED_MODEL, None)
    hybrid_hits = cli.hybrid_search(root, query, 5, cli.DEFAULT_EMBED_MODEL, None, False, False)
    search_json = _run_search_json(root, query, limit=5)
    suggest_card = _run_suggest(root, query, limit=5)
    hook_report = zero_gate.build_report(
        root,
        [{"id": "vector_only", "query": query, "expected_family": [target], "min_hook_candidates": 1}],
        tmp_path / "vector-only-hook-home",
    )
    suggest_candidates = _payload_candidates(suggest_card)
    search_rows = _search_payload_rows(search_json)
    target_suggest = next((row for row in suggest_candidates if row.get("name") == target), {})
    target_search = next((row for row in search_rows if row.get("name") == target), {})
    hook_names = list(hook_report["rows"][0]["user_prompt_submit"]["hook_candidates"])
    return {
        "query_summary_hash": suggest.task_summary_hash(query),
        "target": target,
        "lexical_top": [hit.name for hit in lexical_hits],
        "vector_top": [hit.name for hit in vector_hits],
        "hybrid_top": [hit.name for hit in hybrid_hits],
        "search_json_top": _candidate_names(search_rows),
        "suggest_top": _candidate_names(suggest_candidates),
        "suggest_vector_status": suggest_card.get("payload", {}).get("vector_status")
        if isinstance(suggest_card.get("payload"), dict)
        else None,
        "hook_candidates": hook_names,
        "target_suggest_sources": target_suggest.get("candidate_sources") or [],
        "target_search_sources": target_search.get("candidate_sources") or [],
        "ok": bool(
            vector_hits
            and vector_hits[0].name == target
            and target in [hit.name for hit in hybrid_hits[:3]]
            and target in _candidate_names(suggest_candidates)
            and target in hook_names
            and "vector" in (target_suggest.get("candidate_sources") or [])
            and "vector" in (target_search.get("candidate_sources") or [])
        ),
    }


def build_report(root: Path, *, read_only_root: bool) -> dict[str, Any]:
    queries = zero_gate.load_fixture()
    rows = [_rank_row(root, query_def, read_only_root=read_only_root) for query_def in queries]
    ranking = {
        "hit_at_3": round(sum(1 for row in rows if row["hit_at_3"]) / len(rows), 3) if rows else 0.0,
        "mean_reciprocal_rank": round(sum(float(row["mrr"]) for row in rows) / len(rows), 3) if rows else 0.0,
    }
    with tempfile.TemporaryDirectory(prefix="uls-v065-vector-only-") as tmp:
        vector_only = _vector_only_probe(Path(tmp))
    learning_lift = {"skipped": True, "reason": "read_only_root"} if read_only_root else _learning_lift_probe(root)
    failures = []
    for row in rows:
        if row["shared_family_missing"] and not read_only_root:
            failures.append({"id": row["id"], "reason": "shared_family_missing", "items": row["shared_family_missing"]})
        if row["suggest_divergence"]:
            failures.append({"id": row["id"], "reason": "suggest_not_from_hybrid_family", "items": row["suggest_divergence"]})
        if row["search_json_divergence"]:
            failures.append({"id": row["id"], "reason": "search_json_not_from_hybrid_family", "items": row["search_json_divergence"]})
        if row["suggest_missing_candidate_sources"]:
            failures.append({"id": row["id"], "reason": "suggest_candidate_sources_missing", "items": row["suggest_missing_candidate_sources"]})
        if row["search_missing_candidate_sources"]:
            failures.append({"id": row["id"], "reason": "search_candidate_sources_missing", "items": row["search_missing_candidate_sources"]})
        if row["hybrid_top_10"] and not row["hybrid_suggest_overlap"]:
            failures.append({"id": row["id"], "reason": "hybrid_suggest_divergence"})
        if row["hybrid_top_10"] and not row["hybrid_hook_overlap"]:
            failures.append({"id": row["id"], "reason": "hybrid_hook_divergence"})
        if row["hook_zero_with_family"]:
            failures.append({"id": row["id"], "reason": "hook_zero_with_family"})
        if row["hook_missing_required"]:
            failures.append({"id": row["id"], "reason": "hook_missing_required", "items": row["hook_missing_required"]})
    if not vector_only["ok"]:
        failures.append({"id": "vector_only_fixture", "reason": "vector_candidate_not_delivered", "details": vector_only})
    if not read_only_root and (not learning_lift.get("target_has_learning_boost_source") or not learning_lift.get("rank_improved")):
        failures.append({"id": "learning_lift", "reason": "learning_boost_not_visible_or_not_ranked"})
    if ranking["hit_at_3"] < 1.0 and not read_only_root:
        failures.append({"id": "ranking", "reason": "hit_at_3_below_1_0", "value": ranking["hit_at_3"]})
    if ranking["mean_reciprocal_rank"] <= 0.0 and not read_only_root:
        failures.append({"id": "ranking", "reason": "mrr_zero"})
    return {
        "ok": not failures,
        "schema_version": "v065-shared-candidate-family-v2",
        "root": str(root),
        "read_only_root": read_only_root,
        "query_count": len(rows),
        "ranking": ranking,
        "learning_lift": learning_lift,
        "vector_only": vector_only,
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
            print(
                "- vector-only: "
                f"hybrid={report['vector_only']['hybrid_top'][:3]} "
                f"suggest={report['vector_only']['suggest_top'][:3]} "
                f"hook={report['vector_only']['hook_candidates'][:3]}"
            )
            for row in report["rows"]:
                print(
                    f"- {row['id']}: hybrid={row['hybrid_top_10'][:5]} "
                    f"suggest={row['suggest_top'][:5]} hook={row['hook_candidates'][:5]}"
                )
        return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
