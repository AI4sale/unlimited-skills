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
  ``reason_code`` (match_found / low_confidence_candidates / below_floor /
  empty_library / error),
  ``recommended_next_action`` (a command by skill NAME only), and
  ``latency_ms``. The task/query text, local filesystem paths, and skill
  bodies must never appear in the output;
- ``--card`` (F3b ambient injection, opt-in, JSON mode only) adds
  ``delivery_tier`` (1 silence / 2 hint / 3 card) and, ONLY at tier 3,
  a ``skill_card`` object whose ``card`` text intentionally carries the head
  of the matched skill's own SKILL.md body (hard-capped, see
  :func:`build_skill_card`). The card channel is the single sanctioned
  body-bearing output; it still never contains local filesystem paths, the
  query text, or any other skill's content. Tier 3 requires BOTH a top score
  >= ``HIGH_CONFIDENCE_THRESHOLD`` AND a >= ``HIGH_CONFIDENCE_MARGIN`` ratio
  over the runner-up (or no runner-up above the floor); otherwise it degrades
  to tier 2. The ``UNLIMITED_SKILLS_NO_INJECT`` kill-switch forces tier 3
  down to tier 2;
- event logging is best-effort, strictly local, and can never fail the probe.

`python -m unlimited_skills suggest ...` and the rendered launchers route
here directly without importing the full CLI; `unlimited-skills suggest`
through the classic CLI entry point reuses the same functions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from .search_core import (
    DEFAULT_ROOT,
    SkillHit,
    lexical_search,
    load_records,
    log_event,
    margin_bucket,
    read_text,
    record_router_call,
    score_bucket,
    split_frontmatter,
)

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

# F3b ambient injection (tier 3) calibration against the frozen eval set in
# evals/invocation-scenarios.json on the bundled 267-skill library
# (docs/adoption/skill-effectiveness-standard.md records the distribution):
# every no-skill scenario tops out at 11 (below the 12.0 floor, so negatives
# can never reach ANY tier), true-positive top scores run 12-51. The high
# threshold 18.0 = 1.5x the floor keeps weak/ambiguous matches (12-17) at the
# one-line hint, and the 1.5x runner-up margin keeps contested rankings
# (e.g. S5: wrong top-1 at 19.0 vs right #2 at 18.0, margin 1.06) at tier 2.
HIGH_CONFIDENCE_THRESHOLD = 18.0
HIGH_CONFIDENCE_MARGIN = 1.5
# Hard cap for the injected skill card: ~2,000 tokens.
CARD_MAX_CHARS = 8000
CARD_DESCRIPTION_MAX_CHARS = 600
# Kill switch: downgrades tier 3 (card injection) to tier 2 (one-line hint).
KILL_SWITCH_ENV = "UNLIMITED_SKILLS_NO_INJECT"

TIER_SILENCE = 1
TIER_HINT = 2
TIER_CARD = 3

REASON_MATCH_FOUND = "match_found"
REASON_BELOW_FLOOR = "below_floor"
REASON_LOW_CONFIDENCE = "low_confidence_candidates"
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
    query = (query or "").strip()[:MAX_QUERY_CHARS]
    hits = lexical_search(root, query, limit=max(limit, 1), collection=collection) if query else []
    if hits:
        if hits[0].score >= floor:
            return hits, REASON_MATCH_FOUND
        return hits, REASON_LOW_CONFIDENCE
    # Only the empty path pays for the second (cheap, cached-on-disk) load.
    if not load_records(root):
        return [], REASON_EMPTY_LIBRARY
    return [], REASON_BELOW_FLOOR


def kill_switch_active() -> bool:
    """True when UNLIMITED_SKILLS_NO_INJECT disables tier-3 card injection."""
    return os.environ.get(KILL_SWITCH_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


# Non-English rescue. The lexical engine + ASCII tokenizer score a non-English
# prompt at zero (no tokens), so a Russian/Chinese/etc. prompt would retrieve
# nothing. When lexical comes back empty AND the prompt is not English we route
# to the local MULTILINGUAL embedding sidecar; if no sidecar is installed (or it
# is too slow and the caller times us out) we flag ``needs_english_query`` so
# the caller can re-query with English keywords instead of getting silence.
VECTOR_FLOOR = 0.35  # cosine; good cross-lingual matches measured at 0.55-0.65
NO_VECTOR_FALLBACK_ENV = "UNLIMITED_SKILLS_NO_VECTOR_FALLBACK"


def looks_english(query: str) -> bool:
    """Heuristic: is the query dominated by Latin letters (lexical-friendly)?

    No letters at all (digits/symbols only) counts as English — there is
    nothing to translate and lexical is the right, cheap path.
    """
    letters = [c for c in (query or "") if c.isalpha()]
    if not letters:
        return True
    ascii_letters = sum(1 for c in letters if c.isascii())
    return (ascii_letters / len(letters)) >= 0.6


def _vector_fallback_disabled() -> bool:
    return os.environ.get(NO_VECTOR_FALLBACK_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def sidecar_installed(root: Path) -> bool:
    """True when a local multilingual embedding sidecar is present.

    Imports the heavy CLI module lazily — only the non-English branch ever
    calls this, so the English lexical fast path stays import-cheap.
    """
    try:
        from unlimited_skills import cli

        return cli.vector_sidecar_path(root).exists()
    except Exception:
        return False


def vector_probe(root: Path, query: str, limit: int, collection: str | None = None) -> list[SkillHit]:
    """Best-effort multilingual vector retrieval at/above ``VECTOR_FLOOR``.

    Heavy deps (embedding model, sidecar) are lazy-imported. Any failure
    returns ``[]`` so the probe degrades to the English-keywords signal rather
    than blocking or raising.
    """
    query = (query or "").strip()[:MAX_QUERY_CHARS]
    if not query:
        return []
    try:
        from unlimited_skills import cli

        hits = cli.vector_search(root, query, max(limit, 1), cli.DEFAULT_EMBED_MODEL, collection)
    except Exception:
        return []
    return [hit for hit in hits if getattr(hit, "score", 0.0) >= VECTOR_FLOOR]


def select_tier(
    hits: list[SkillHit],
    floor: float = DEFAULT_FLOOR,
    high_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
    margin: float = HIGH_CONFIDENCE_MARGIN,
) -> int:
    """Delivery tier for floor-filtered hits: 1 silence, 2 hint, 3 card.

    Tier 3 requires BOTH conditions; failing either degrades to tier 2:

    - confidence: top score >= ``high_threshold``;
    - margin: top score >= ``margin`` x the runner-up score (trivially true
      when there is no runner-up at or above the floor).
    """
    if not hits:
        return TIER_SILENCE
    top = hits[0]
    if top.score < high_threshold:
        return TIER_HINT
    runner_up = hits[1] if len(hits) > 1 else None
    if runner_up is not None and runner_up.score >= floor and top.score < margin * runner_up.score:
        return TIER_HINT
    return TIER_CARD


def build_skill_card(hit: SkillHit, max_chars: int = CARD_MAX_CHARS) -> str | None:
    """Compact injectable card from the skill's own SKILL.md, or None.

    Contract: name + source header, when-to-use line (frontmatter
    description), the HEAD of the body after the frontmatter, hard-capped at
    ``max_chars`` total. When truncated, a final note points to the full
    skill by NAME; a footer with the view command is always appended. The
    card never contains local filesystem paths, the query text, or any other
    skill's content. Any read/shape failure returns None (callers degrade to
    tier 2) — the card must never break the probe.
    """
    try:
        text = read_text(Path(hit.path))
    except (OSError, ValueError):
        return None
    meta, body = split_frontmatter(text)
    name = (hit.name or meta.get("name") or "").strip()
    if not name:
        return None
    description = " ".join((meta.get("description") or hit.description or "").split())
    if len(description) > CARD_DESCRIPTION_MAX_CHARS:
        description = description[: CARD_DESCRIPTION_MAX_CHARS - 3].rstrip() + "..."
    header_lines = [f"Skill card: {name} (source: {hit.collection})"]
    if description:
        header_lines.append(f"When to use: {description}")
    head = "\n".join(header_lines)
    footer = f"Full skill body: unlimited-skills view {name}"
    truncation_note = f"(card truncated — full skill: unlimited-skills view {name})"
    body = body.strip()

    full_card = (head + "\n\n" + body + "\n\n" if body else head + "\n\n") + footer
    if len(full_card) <= max_chars:
        return full_card
    # Keep the head of the body; append the truncation note, then the footer.
    suffix = "\n\n" + truncation_note + "\n" + footer
    room = max_chars - len(head) - 2 - len(suffix)
    if room < 0:
        return None  # pathological cap: no room for even an empty body
    truncated_body = body[:room].rstrip()
    return head + "\n\n" + truncated_body + suffix


def recommended_next_action(hits: list[SkillHit], reason_code: str) -> str:
    """A next step referencing skills by NAME only — never local paths."""
    if reason_code == REASON_MATCH_FOUND and hits:
        return f"unlimited-skills view {hits[0].name}"
    if reason_code == REASON_EMPTY_LIBRARY:
        return "no skill library found; proceed with the task (or run: unlimited-skills reindex)"
    if reason_code == REASON_ERROR:
        return "probe failed; proceed with the task"
    if reason_code == REASON_LOW_CONFIDENCE and hits:
        return f"low-confidence candidates available; consider: unlimited-skills view {hits[0].name}"
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
    parser.add_argument("--card", action="store_true", help="JSON mode only: add delivery_tier and, at tier 3 (high confidence + margin), a compact skill_card built from the matched SKILL.md.")
    parser.add_argument("--high-threshold", type=float, default=HIGH_CONFIDENCE_THRESHOLD, help="Tier-3 minimum top score (only with --card).")
    parser.add_argument("--high-margin", type=float, default=HIGH_CONFIDENCE_MARGIN, help="Tier-3 minimum top/runner-up score ratio (only with --card).")
    parser.add_argument("--card-max-chars", type=int, default=CARD_MAX_CHARS, help="Hard cap for the skill card text (only with --card).")
    return parser


def _print_json(query: str, hits: list[SkillHit], reason_code: str, elapsed_ms: float, extra: dict | None = None) -> None:
    payload = {
        "task_summary_hash": task_summary_hash(query),
        "top_3_skill_candidates": candidate_payload(hits),
        "reason_code": reason_code,
        "recommended_next_action": recommended_next_action(hits, reason_code),
        "latency_ms": round(elapsed_ms, 1),
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser()
    started = time.perf_counter()
    try:
        # Card mode needs the runner-up score for the margin check even when
        # the caller only displays one candidate.
        fetch_limit = max(args.limit, 5) if args.card else args.limit
        hits, reason_code = probe(root, args.query, limit=fetch_limit, floor=args.floor, collection=args.collection)
    except Exception:
        # The probe must never block the task it is trying to help.
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if args.json:
            _print_json(args.query, [], REASON_ERROR, elapsed_ms)
        # An errored probe is still a router invocation: count it so the meter
        # reflects every call, not just the successful ones.
        try:
            record_router_call(root, elapsed_ms=elapsed_ms, reason_code=REASON_ERROR, path="none")
        except Exception:
            pass
        return 0

    # Non-English / lexical-empty rescue: try the local multilingual embedding
    # sidecar; if none is installed (or disabled), flag needs_english_query so
    # the caller re-queries with English keywords instead of getting silence.
    retrieval_path = "lexical" if hits else "none"
    needs_english = False
    if not hits and not looks_english(args.query):
        if not _vector_fallback_disabled() and sidecar_installed(root):
            vector_hits = vector_probe(root, args.query, fetch_limit, args.collection)
            if vector_hits:
                hits = vector_hits
                reason_code = REASON_MATCH_FOUND
                retrieval_path = "vector"
        if not hits:
            needs_english = True

    # The new routing fields ride only on the --card channel (the hook's mode);
    # the plain --json contract stays byte-identical for existing consumers.
    extra: dict = {}
    tier = None
    injected = False
    if args.card:
        extra["retrieval_path"] = retrieval_path
        if needs_english:
            extra["needs_english_query"] = True
        tier = select_tier(hits, floor=args.floor, high_threshold=args.high_threshold, margin=args.high_margin)
        card_obj = None
        if tier == TIER_CARD and not kill_switch_active():
            card_text = build_skill_card(hits[0], max_chars=args.card_max_chars)
            if card_text:
                card_obj = {"name": hits[0].name, "source": hits[0].collection, "card": card_text}
        if tier == TIER_CARD and card_obj is None:
            tier = TIER_HINT  # kill switch or unreadable SKILL.md: degrade, never block
        injected = card_obj is not None
        extra["delivery_tier"] = tier  # update, never reassign: keep retrieval_path/needs_english_query
        if card_obj is not None:
            extra["skill_card"] = card_obj
    display_hits = hits[: args.limit]
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    if args.json:
        _print_json(args.query, display_hits, reason_code, elapsed_ms, extra)
    else:
        for hit in display_hits:
            print(format_suggestion(hit))

    try:
        # Local-only learning log (never printed, never uploaded).
        # A3.1.1: delivery_tier + injected + coarse score/margin buckets feed the
        # effectiveness funnel; session_correlation_id is stamped by log_event.
        top_score = hits[0].score if hits else None
        runner_up_score = hits[1].score if len(hits) > 1 else None
        event = {
            # A3.1.1 privacy gate: store ONLY the short hash of the query, never
            # the raw prompt/task text. Identical queries still correlate by hash.
            "task_summary_hash": task_summary_hash(args.query),
            "floor": args.floor,
            "elapsed_ms": round(elapsed_ms, 1),
            "reason_code": reason_code,
            "low_confidence": reason_code == REASON_LOW_CONFIDENCE,
            "injected": injected,
            "score_bucket": score_bucket(top_score),
            "margin_bucket": margin_bucket(top_score, runner_up_score),
            "hits": [{"name": hit.name, "score": hit.score} for hit in display_hits],
        }
        if tier is not None:
            event["delivery_tier"] = tier
        log_event(root, "suggest", event)
    except OSError:
        pass

    # Internal router-invocation meter: bump the running count and stamp this
    # call's timing/outcome. Separate from the event log above so "how many
    # times was the router called, and when last?" is one cheap file read.
    record_router_call(
        root,
        elapsed_ms=elapsed_ms,
        reason_code=reason_code,
        path=retrieval_path,
        injected=injected,
        delivery_tier=tier,
        top_skill=hits[0].name if hits else "",
        top_score=hits[0].score if hits else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
