"""Audit zero-candidate retrieval losses for C065-GATE-AUDIT-01.

This is an audit verifier, not the repair. It intentionally reports failure
when a query has a candidate family available through supported retrieval but
the UserPromptSubmit delivery path gives the model zero or too few candidates.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from unlimited_skills import cli, suggest  # noqa: E402
from unlimited_skills.search_core import SkillHit, load_records, save_index  # noqa: E402

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "retrieval" / "zero_candidate_queries.v1.json"
HOOK_PATH = REPO_ROOT / "plugin" / "hooks" / "user_prompt_submit.py"


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
    _write_skill(root, "content-engine", "Plan and draft content posts, newsletters, and editorial assets.")
    _write_skill(root, "router-upgrade-maintenance", "Repair stale launchers after pip upgrade and package refresh.")
    _write_skill(root, "inject-refresh", "Refresh router inject artifacts, CLAUDE.md, AGENTS.md, and agent hooks.")
    _write_skill(root, "gardening-basics", "Watering schedules for houseplants.")
    save_index(root)
    return root


def _hit_payload(hit: SkillHit) -> dict[str, Any]:
    row = asdict(hit)
    row.pop("path", None)
    row["score"] = round(float(row.get("score") or 0.0), 3)
    return row


def _safe_search(label: str, func, *args) -> dict[str, Any]:
    try:
        hits = func(*args)
        return {"ok": True, "hits": [_hit_payload(hit) for hit in hits[:10]], "error": None}
    except Exception as exc:  # audit must expose missing sidecar/deps, not crash
        return {"ok": False, "hits": [], "error": f"{type(exc).__name__}: {exc}", "label": label}


def _run_suggest(root: Path, query: str, *, card: bool, limit: int) -> dict[str, Any]:
    argv = [query, "--root", str(root), "--json", "--limit", str(limit)]
    if card:
        argv.append("--card")
    from io import StringIO
    from contextlib import redirect_stdout

    buffer = StringIO()
    with redirect_stdout(buffer):
        rc = suggest.main(argv)
    text = buffer.getvalue().strip()
    if not text:
        return {"returncode": rc, "payload": None, "raw_stdout": ""}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    return {"returncode": rc, "payload": payload, "raw_stdout": text}


def _run_hook(root: Path, query: str, tmp_home: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env["CLAUDE_HOME"] = str(tmp_home / "claude-home")
    env["UNLIMITED_SKILLS_INSTALL_ROOT"] = str(tmp_home / "install-root")
    env["UNLIMITED_SKILLS_NO_AUTOSERVE"] = "1"
    env["UNLIMITED_SKILLS_CLI"] = f'"{Path(sys.executable).as_posix()}" -m unlimited_skills --root "{root.as_posix()}"'
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps({"prompt": query}, ensure_ascii=False),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
        cwd=str(REPO_ROOT),
    )
    payload = None
    context = ""
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
            context = str(payload.get("hookSpecificOutput", {}).get("additionalContext") or "")
        except json.JSONDecodeError:
            context = proc.stdout
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "payload": payload,
        "context": context,
    }


def _context_candidates(context: str, known_names: set[str]) -> list[str]:
    return sorted(name for name in known_names if name and name in context)


def _candidate_names(search_result: dict[str, Any]) -> set[str]:
    return {str(hit.get("name") or "") for hit in search_result.get("hits") or [] if hit.get("name")}


def _payload_candidates(result: dict[str, Any]) -> set[str]:
    payload = result.get("payload")
    if not isinstance(payload, dict):
        return set()
    return {
        str(candidate.get("name") or "")
        for candidate in payload.get("top_3_skill_candidates") or []
        if isinstance(candidate, dict) and candidate.get("name")
    }


def _looks_non_english(query: str) -> bool:
    letters = [char for char in query if char.isalpha()]
    if not letters:
        return False
    ascii_letters = sum(1 for char in letters if char.isascii())
    return (ascii_letters / len(letters)) < 0.6


def _drop_reasons(
    *,
    query: str,
    root: Path,
    lexical: dict[str, Any],
    vector: dict[str, Any],
    hybrid: dict[str, Any],
    english_hybrid: dict[str, Any],
    suggest_card: dict[str, Any],
    hook_candidates: list[str],
    min_hook_candidates: int,
) -> list[str]:
    reasons: list[str] = []
    payload = suggest_card.get("payload") if isinstance(suggest_card.get("payload"), dict) else {}
    if payload.get("reason_code") == "below_floor":
        reasons.append("floor")
    if not lexical.get("hits") and (hybrid.get("hits") or english_hybrid.get("hits")):
        reasons.append("lexical-only path")
    if min_hook_candidates > 1 and len(hook_candidates) < min_hook_candidates:
        reasons.append("limit=1")
    if payload.get("delivery_tier") == suggest.TIER_HINT:
        reasons.append("card threshold")
    if payload.get("delivery_tier") == suggest.TIER_HINT and len(payload.get("top_3_skill_candidates") or []) <= 1:
        reasons.append("high-margin gate")
    if vector.get("error") and not cli.vector_sidecar_path(root).exists():
        reasons.append("missing sidecar")
    if _looks_non_english(query) or payload.get("needs_english_query") is True:
        reasons.append("non-English branch")
    if "timed out" in str(suggest_card.get("raw_stdout") or "").lower():
        reasons.append("timeout")
    return sorted(set(reasons))


def load_fixture(path: Path = FIXTURE_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in payload.get("queries", []) if isinstance(row, dict)]


def build_report(root: Path, queries: list[dict[str, Any]], tmp_home: Path) -> dict[str, Any]:
    records = load_records(root)
    known_names = {hit.name for hit, _body in records}
    rows = []
    losses = []
    for query_def in queries:
        query = str(query_def["query"])
        english_query = str(query_def.get("english_retrieval_query") or query)
        min_hook_candidates = int(query_def.get("min_hook_candidates") or 1)
        lexical = _safe_search("lexical", cli.lexical_search, root, query, 10, None, False)
        vector = _safe_search("vector", cli.vector_search, root, query, 10, cli.DEFAULT_EMBED_MODEL, None)
        hybrid = _safe_search("hybrid", cli.hybrid_search, root, query, 10, cli.DEFAULT_EMBED_MODEL, None, False, False)
        english_hybrid = _safe_search(
            "english_hybrid",
            cli.hybrid_search,
            root,
            english_query,
            10,
            cli.DEFAULT_EMBED_MODEL,
            None,
            False,
            False,
        )
        suggest_json = _run_suggest(root, query, card=False, limit=3)
        suggest_card = _run_suggest(root, query, card=True, limit=1)
        hook = _run_hook(root, query, tmp_home)
        hook_candidates = _context_candidates(hook["context"], known_names)

        search_names = (
            _candidate_names(lexical)
            | _candidate_names(vector)
            | _candidate_names(hybrid)
            | _candidate_names(english_hybrid)
            | _payload_candidates(suggest_json)
            | _payload_candidates(suggest_card)
        )
        zero_candidate_loss = bool(search_names) and not hook_candidates
        insufficient_candidate_delivery = bool(search_names) and len(hook_candidates) < min_hook_candidates
        row = {
            "id": query_def.get("id"),
            "query": query,
            "english_retrieval_query": english_query,
            "library_skill_count": len(records),
            "lexical_search_top_10": lexical,
            "vector_search_top_10": vector,
            "hybrid_search_top_10": hybrid,
            "english_hybrid_search_top_10": english_hybrid,
            "suggest_json": suggest_json,
            "suggest_card_json": suggest_card,
            "user_prompt_submit": {
                "returncode": hook["returncode"],
                "context_present": bool(hook["context"]),
                "hook_candidates": hook_candidates,
                "context_preview": hook["context"][:500],
            },
            "expected_family": query_def.get("expected_family") or [],
            "min_hook_candidates": min_hook_candidates,
            "search_candidate_count": len(search_names),
            "hook_candidate_count": len(hook_candidates),
            "zero_candidate_loss": zero_candidate_loss,
            "insufficient_candidate_delivery": insufficient_candidate_delivery,
            "drop_reasons": _drop_reasons(
                query=query,
                root=root,
                lexical=lexical,
                vector=vector,
                hybrid=hybrid,
                english_hybrid=english_hybrid,
                suggest_card=suggest_card,
                hook_candidates=hook_candidates,
                min_hook_candidates=min_hook_candidates,
            ),
        }
        rows.append(row)
        if zero_candidate_loss or insufficient_candidate_delivery:
            losses.append(row)
    return {
        "ok": not losses,
        "schema_version": 1,
        "root": str(root),
        "query_count": len(rows),
        "loss_count": len(losses),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="", help="Skill library root. Defaults to a deterministic audit fixture.")
    parser.add_argument("--fixture", default=str(FIXTURE_PATH), help="Query fixture JSON.")
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    args = parser.parse_args(argv)

    queries = load_fixture(Path(args.fixture))
    with tempfile.TemporaryDirectory(prefix="uls-c065-audit-") as tmp:
        tmp_path = Path(tmp)
        root = Path(args.root).expanduser() if args.root else build_fixture_library(tmp_path / "library")
        report = build_report(root, queries, tmp_path)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            status = "PASS" if report["ok"] else "FAIL"
            print(f"C065 zero-candidate gate audit: {status} ({report['loss_count']} losses)")
            for row in report["rows"]:
                marker = "LOSS" if row["zero_candidate_loss"] or row["insufficient_candidate_delivery"] else "ok"
                print(
                    f"- {marker} {row['id']}: search_candidates={row['search_candidate_count']} "
                    f"hook_candidates={row['hook_candidate_count']} reasons={','.join(row['drop_reasons'])}"
                )
        return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
