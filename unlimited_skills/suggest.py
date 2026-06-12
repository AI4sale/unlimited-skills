"""`unlimited-skills suggest` — the fast, always-cheap invocation probe.

Design contract (A0 invocation rescue, F1 + Hermes privacy hardening):

- lexical-only: never loads the embedding model, never touches the vector
  index, never syncs native skill roots;
- import-cheap: depends only on :mod:`unlimited_skills.search_core`, so the
  dominant cost is the Python interpreter spawn itself;
- top-3 one-liners: ``name [source] — description`` (no filesystem paths);
- score floor: hits below the floor are suppressed entirely. Text mode
  prints NOTHING and exits 0 — silence beats noise, and an empty answer is
  an explicit "no relevant skill, proceed with the task";
- ``--json`` prints a privacy-hardened object containing ONLY
  ``task_summary_hash`` (short sha256 of the normalized query),
  ``top_3_skill_candidates`` (name, source, score — never paths or bodies),
  ``reason_code`` (match_found / below_floor / empty_library / error),
  ``recommended_next_action`` (a command by skill NAME only), and
  ``latency_ms``. The task/query text, local filesystem paths, and skill
  bodies must never appear in the output;
- event logging is best-effort, strictly local, and can never fail the probe.

`python -m unlimited_skills suggest ...` and the rendered launchers route
here directly without importing the full CLI; `unlimited-skills suggest`
through the classic CLI entry point reuses the same functions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from .search_core import DEFAULT_ROOT, SkillHit, lexical_search, load_records, log_event

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Default floor calibrated on the bundled 267-skill library against the
# frozen eval set in evals/invocation-scenarios.json (see
# docs/adoption/skill-effectiveness-standard.md for the measured numbers):
# the strongest no-skill scenario scores 11, the weakest true positives 12.
DEFAULT_FLOOR = 12.0
DEFAULT_LIMIT = 3
MAX_QUERY_CHARS = 300

REASON_MATCH_FOUND = "match_found"
REASON_BELOW_FLOOR = "below_floor"
REASON_EMPTY_LIBRARY = "empty_library"
REASON_ERROR = "error"


def task_summary_hash(query: str) -> str:
    """Short sha256 of the normalized query — a correlation id, never the text."""
    normalized = " ".join((query or "").split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def suggest_hits(
    root: Path,
    query: str,
    limit: int = DEFAULT_LIMIT,
    floor: float = DEFAULT_FLOOR,
    collection: str | None = None,
) -> list[SkillHit]:
    """Return the top suggestions at or above the score floor."""
    query = (query or "").strip()[:MAX_QUERY_CHARS]
    if not query:
        return []
    hits = lexical_search(root, query, limit=max(limit, 1), collection=collection)
    return [hit for hit in hits if hit.score >= floor]


def probe(
    root: Path,
    query: str,
    limit: int = DEFAULT_LIMIT,
    floor: float = DEFAULT_FLOOR,
    collection: str | None = None,
) -> tuple[list[SkillHit], str]:
    """Return (hits, reason_code). Never raises for I/O-shaped failures."""
    hits = suggest_hits(root, query, limit=limit, floor=floor, collection=collection)
    if hits:
        return hits, REASON_MATCH_FOUND
    # Only the empty path pays for the second (cheap, cached-on-disk) load.
    if not load_records(root):
        return [], REASON_EMPTY_LIBRARY
    return [], REASON_BELOW_FLOOR


def recommended_next_action(hits: list[SkillHit], reason_code: str) -> str:
    """A next step referencing skills by NAME only — never local paths."""
    if reason_code == REASON_MATCH_FOUND and hits:
        return f"unlimited-skills view {hits[0].name}"
    if reason_code == REASON_EMPTY_LIBRARY:
        return "no skill library found; proceed with the task (or run: unlimited-skills reindex)"
    if reason_code == REASON_ERROR:
        return "probe failed; proceed with the task"
    return "no skill clears the score floor; proceed with the task"


def candidate_payload(hits: list[SkillHit]) -> list[dict]:
    """JSON candidates: name, source (collection/pack), score. Nothing else."""
    return [
        {"name": hit.name, "source": hit.collection, "score": round(float(hit.score), 1)}
        for hit in hits
    ]


def format_suggestion(hit: SkillHit) -> str:
    description = " ".join((hit.description or "").split())
    if len(description) > 120:
        description = description[:117].rstrip() + "..."
    return f"{hit.name} [{hit.collection}] — {description}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="unlimited-skills suggest",
        description="Fast lexical skill probe: top-3 one-liners or silence.",
    )
    parser.add_argument("query", help="Task description in 3-8 keywords.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Skill library root.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum suggestions to print.")
    parser.add_argument("--floor", type=float, default=DEFAULT_FLOOR, help="Suppress hits scoring below this floor.")
    parser.add_argument("--collection", default=None, help="Only suggest from one collection.")
    parser.add_argument("--json", action="store_true", help="Print the privacy-hardened JSON object instead of text.")
    return parser


def _print_json(query: str, hits: list[SkillHit], reason_code: str, elapsed_ms: float) -> None:
    print(
        json.dumps(
            {
                "task_summary_hash": task_summary_hash(query),
                "top_3_skill_candidates": candidate_payload(hits),
                "reason_code": reason_code,
                "recommended_next_action": recommended_next_action(hits, reason_code),
                "latency_ms": round(elapsed_ms, 1),
            },
            ensure_ascii=False,
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser()
    started = time.perf_counter()
    try:
        hits, reason_code = probe(root, args.query, limit=args.limit, floor=args.floor, collection=args.collection)
    except Exception:
        # The probe must never block the task it is trying to help.
        if args.json:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            _print_json(args.query, [], REASON_ERROR, elapsed_ms)
        return 0
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    if args.json:
        _print_json(args.query, hits, reason_code, elapsed_ms)
    else:
        for hit in hits:
            print(format_suggestion(hit))

    try:
        # Local-only learning log (never printed, never uploaded).
        log_event(
            root,
            "suggest",
            {
                "query": args.query[:MAX_QUERY_CHARS],
                "floor": args.floor,
                "elapsed_ms": round(elapsed_ms, 1),
                "reason_code": reason_code,
                "hits": [{"name": hit.name, "score": hit.score} for hit in hits],
            },
        )
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
