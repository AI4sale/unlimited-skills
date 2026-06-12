"""`unlimited-skills suggest` — the fast, always-cheap invocation probe.

Design contract (A0 invocation rescue, F1):

- lexical-only: never loads the embedding model, never touches the vector
  index, never syncs native skill roots;
- import-cheap: depends only on :mod:`unlimited_skills.search_core`, so the
  dominant cost is the Python interpreter spawn itself;
- top-3 one-liners: ``name — description (score)``;
- score floor: hits below the floor are suppressed entirely. Text mode
  prints NOTHING and exits 0 — silence beats noise, and an empty answer is
  an explicit "no relevant skill, proceed with the task";
- ``--json`` prints a machine-friendly JSON array (possibly ``[]``);
- event logging is best-effort and can never fail the probe.

`python -m unlimited_skills suggest ...` and the rendered launchers route
here directly without importing the full CLI; `unlimited-skills suggest`
through the classic CLI entry point reuses the same functions.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .search_core import DEFAULT_ROOT, SkillHit, lexical_search, log_event

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


def format_suggestion(hit: SkillHit) -> str:
    description = " ".join((hit.description or "").split())
    if len(description) > 120:
        description = description[:117].rstrip() + "..."
    return f"{hit.name} — {description} ({hit.score:.0f})"


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
    parser.add_argument("--json", action="store_true", help="Print a JSON array (possibly empty) instead of text.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser()
    started = time.perf_counter()
    try:
        hits = suggest_hits(root, args.query, limit=args.limit, floor=args.floor, collection=args.collection)
    except Exception:
        # The probe must never block the task it is trying to help.
        if args.json:
            print("[]")
        return 0
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)

    if args.json:
        print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False))
    else:
        for hit in hits:
            print(format_suggestion(hit))

    try:
        log_event(
            root,
            "suggest",
            {
                "query": args.query[:MAX_QUERY_CHARS],
                "floor": args.floor,
                "elapsed_ms": elapsed_ms,
                "hits": [{"name": hit.name, "score": hit.score} for hit in hits],
            },
        )
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
