"""`unlimited-skills suggest` — the fast, always-cheap invocation probe.

Design contract (A0 invocation rescue, F1 + Hermes privacy hardening):

- lexical-only: never loads the embedding model, never touches the vector
  index, never syncs native skill roots;
- import-cheap: depends only on :mod:`unlimited_skills.search_core`, so the
  dominant cost is the Python interpreter spawn itself;
- top-3 one-liners: ``name [source] — description`` (no filesystem paths);
- score floor: plain text suppresses hits below the configured floor. Card mode
  separately exposes raw diagnostics, recall-safe NAME hints, and a stricter
  card/body candidate; body-only evidence can never create a hint;
- ``--json`` prints a privacy-hardened object containing ONLY
  ``task_summary_hash`` (short sha256 of the normalized query),
  ``top_3_skill_candidates`` (name, source, score — never paths or bodies),
  ``reason_code`` (match_found / low_confidence_candidates / below_floor /
  empty_library / error),
  ``recommended_next_action`` (a command by skill NAME only), and
  ``latency_ms``. The task/query text, local filesystem paths, and skill
  bodies must never appear in the output;
- ``--card`` (F3b ambient injection, opt-in, JSON mode only) adds schema-v2
  retrieval/delivery fields plus ``delivery_tier`` (1 silence / 2 hint / 3
  card) and, ONLY at tier 3,
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
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .search_core import (
    DEFAULT_ROOT,
    SkillHit,
    candidate_debug_payload,
    library_generation_hash,
    lexical_search,
    load_records,
    log_event,
    margin_bucket,
    read_text,
    record_router_call,
    score_bucket,
    shared_candidate_family,
    split_frontmatter,
    vector_sidecar_status,
)
from .daemon_endpoint import warm_daemon_url

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Default floor calibrated on the bundled 267-skill library against the
# frozen eval set in evals/invocation-scenarios.json (see
# docs/adoption/skill-effectiveness-standard.md for the measured numbers):
# the strongest no-skill scenario scores 11, the weakest true positives 12.
DEFAULT_FLOOR = 12.0
HINT_FLOOR = 6.0
NAME_HINT_IDF_MIN = 2.0
NAME_HINT_IDF_RATIO_MIN = 0.80
NAME_STRONG_LEXICAL_MIN = 18.0
NAME_STRONG_IDF_MIN = 4.0
DESCRIPTION_HINT_IDF_MIN = 4.0
VECTOR_HINT_MIN = 0.50
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
    if not load_records(root, include_body=False):
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
VECTOR_SIDECAR_NAME = ".unlimited-skills-vectors.json"
DEFAULT_EMBED_MODEL = os.environ.get(
    "UNLIMITED_SKILLS_EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
WARM_DAEMON_TIMEOUT_SECONDS = 0.25
WARM_DAEMON_SEARCH_TIMEOUT_SECONDS = 1.5
WARM_DAEMON_PROTOCOL = "warm-search-v1"


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

    This is a direct filesystem check. Confident lexical queries never call
    the vector engine; low-confidence queries may use an installed sidecar to
    preserve semantic-only matches without importing the full CLI up front.
    """
    try:
        return bool(
            vector_sidecar_status(
                root,
                root / VECTOR_SIDECAR_NAME,
                DEFAULT_EMBED_MODEL,
            ).get("ready")
        )
    except OSError:
        return False


def vector_probe(root: Path, query: str, limit: int, collection: str | None = None) -> list[SkillHit]:
    """Best-effort vector rescue without cold-loading an embedding model.

    Exact cached fixture/query embeddings can be evaluated from the sidecar.
    Arbitrary queries use only an already-running, root-matched warm daemon.
    Any failure returns ``[]``; this function never starts a service.
    """
    query = (query or "").strip()[:MAX_QUERY_CHARS]
    if not query:
        return []
    try:
        payload = json.loads(read_text(root / VECTOR_SIDECAR_NAME))
        records = payload.get("records") if isinstance(payload, dict) else None
        dimensions = int(payload.get("embedding_dimensions") or 0) if isinstance(payload, dict) else 0
        if not (
            isinstance(payload, dict)
            and int(payload.get("schema_version") or 0) >= 2
            and payload.get("complete") is True
            and str(payload.get("model") or "") == DEFAULT_EMBED_MODEL
            and payload.get("library_generation_hash") == library_generation_hash(root)
            and isinstance(records, list)
            and int(payload.get("count") or -1) == len(records)
            and dimensions > 0
        ):
            return []
        query_embeddings = payload.get("query_embeddings") if isinstance(payload, dict) else None
        query_vector = None
        if isinstance(query_embeddings, dict):
            for key in (task_summary_hash(query), " ".join(query.split()).lower(), query):
                if isinstance(query_embeddings.get(key), list) and len(query_embeddings[key]) == dimensions:
                    query_vector = [float(value) for value in query_embeddings[key]]
                    break
        if query_vector is not None:
            scored: list[SkillHit] = []
            for row in records:
                if not isinstance(row, dict) or (collection and row.get("collection") != collection):
                    continue
                embedding = row.get("embedding")
                if not isinstance(embedding, list) or len(embedding) != dimensions:
                    continue
                dot = sum(left * float(right) for left, right in zip(query_vector, embedding))
                q_norm = sum(value * value for value in query_vector) ** 0.5
                e_norm = sum(float(value) * float(value) for value in embedding) ** 0.5
                score = dot / (q_norm * e_norm) if q_norm and e_norm else 0.0
                if score >= VECTOR_FLOOR:
                    scored.append(
                        SkillHit(
                            name=str(row.get("name") or ""),
                            description=str(row.get("description") or ""),
                            collection=str(row.get("collection") or ""),
                            path=str(row.get("path") or ""),
                            score=score,
                        )
                    )
            return sorted(scored, key=lambda hit: (-hit.score, hit.collection, hit.name))[: max(limit, 1)]

        daemon_url = warm_daemon_url(root, DEFAULT_EMBED_MODEL)
        if not daemon_url:
            return []
        with urllib.request.urlopen(f"{daemon_url}/health", timeout=WARM_DAEMON_TIMEOUT_SECONDS) as response:
            health = json.loads(response.read().decode("utf-8"))
        daemon_root_raw = str(health.get("root") or "").strip()
        if not (
            health.get("ok") is True
            and health.get("service") == "unlimited-skills"
            and health.get("protocol") == WARM_DAEMON_PROTOCOL
            and daemon_root_raw
        ):
            return []
        daemon_root = Path(daemon_root_raw).expanduser().resolve()
        if daemon_root != root.expanduser().resolve() or str(health.get("model") or "") != DEFAULT_EMBED_MODEL:
            return []
        request = urllib.request.Request(
            f"{daemon_url}/search",
            data=json.dumps(
                {"query": query, "mode": "vector", "limit": max(limit, 1), "collection": collection, "require_vector": True}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=WARM_DAEMON_SEARCH_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
        hits = [
            SkillHit(
                name=str(row.get("name") or ""),
                description=str(row.get("description") or ""),
                collection=str(row.get("collection") or ""),
                path=str(row.get("path") or ""),
                score=float(row.get("score") or 0.0),
            )
            for row in result.get("hits") or []
            if isinstance(row, dict)
        ]
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


def exact_identity_match(query: str, hit: SkillHit) -> bool:
    query_tokens = [token for token in re.split(r"[^a-z0-9+.#]+", query.lower()) if token]
    identity_tokens = [token for token in re.split(r"[^a-z0-9+.#]+", hit.name.lower()) if token]
    if not identity_tokens or len(identity_tokens) > len(query_tokens):
        return False
    return any(
        query_tokens[index : index + len(identity_tokens)] == identity_tokens
        for index in range(len(query_tokens) - len(identity_tokens) + 1)
    )


def recall_safe_hint_hits(hits: list[SkillHit], query: str = "") -> list[SkillHit]:
    """Return low-risk NAME/description hints, excluding generic body-only noise."""
    safe: list[SkillHit] = []
    for hit in hits:
        evidence = candidate_debug_payload(hit)
        exact_ok = exact_identity_match(query, hit) if query else bool(evidence.get("exact_match"))
        name_idf_ok = (
            float(evidence.get("name_overlap_idf") or 0.0) >= NAME_HINT_IDF_MIN
            or float(evidence.get("name_overlap_idf_ratio") or 0.0) >= NAME_HINT_IDF_RATIO_MIN
        )
        description_idf_ok = (
            float(evidence.get("description_overlap_idf") or 0.0) >= DESCRIPTION_HINT_IDF_MIN
            or float(evidence.get("description_overlap_idf_ratio") or 0.0) >= NAME_HINT_IDF_RATIO_MIN
        )
        phrase_idf_ok = (
            float(evidence.get("phrase_overlap_idf") or 0.0) >= NAME_HINT_IDF_MIN
            or float(evidence.get("phrase_overlap_idf_ratio") or 0.0) >= NAME_HINT_IDF_RATIO_MIN
        )
        name_ok = (
            float(evidence.get("lexical_score") or 0.0) >= HINT_FLOOR
            and int(evidence.get("name_overlap_count") or 0) >= 1
            and name_idf_ok
            and (
                int(evidence.get("name_overlap_count") or 0) >= 2
                or bool(evidence.get("name_overlap_anchor"))
                or (
                    float(evidence.get("lexical_score") or 0.0) >= NAME_STRONG_LEXICAL_MIN
                    and float(evidence.get("name_overlap_idf") or 0.0) >= NAME_STRONG_IDF_MIN
                )
            )
        )
        description_ok = (
            float(evidence.get("lexical_score") or 0.0) >= HINT_FLOOR
            and int(evidence.get("description_overlap_count") or 0) >= 2
            and description_idf_ok
        )
        phrase_ok = (
            float(evidence.get("lexical_score") or 0.0) >= HINT_FLOOR
            and int(evidence.get("phrase_overlap_count") or 0) >= 1
            and phrase_idf_ok
        )
        vector_ok = (
            float(evidence.get("vector_score") or 0.0) >= VECTOR_HINT_MIN
            and 0 < int(evidence.get("vector_rank") or 0) <= 3
        )
        if exact_ok or name_ok or description_ok or phrase_ok or vector_ok:
            safe.append(hit)
    return safe


def card_safe_hits(
    hints: list[SkillHit],
    *,
    query: str,
    floor: float,
    mixed_language_uncertain: bool,
) -> list[SkillHit]:
    """Card/body injection requires strong lexical identity, never vector-only."""
    if mixed_language_uncertain:
        return []
    cards: list[SkillHit] = []
    for hit in hints:
        evidence = candidate_debug_payload(hit)
        lexical_score = float(evidence.get("lexical_score") or 0.0)
        lexical_identity = exact_identity_match(query, hit) or int(
            evidence.get("name_overlap_count") or 0
        ) >= 1
        # RRF can promote a weak lexical row, but ranking is not qualification:
        # a card must independently clear the lexical evidence floor.
        if lexical_score >= floor and lexical_identity:
            cards.append(hit)
    return cards


def select_card_tier(
    hits: list[SkillHit],
    floor: float = DEFAULT_FLOOR,
    high_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
    margin: float = HIGH_CONFIDENCE_MARGIN,
) -> int:
    """Select card delivery from lexical evidence, never an RRF score."""
    if not hits:
        return TIER_SILENCE

    def lexical_score(hit: SkillHit) -> float:
        return float(candidate_debug_payload(hit).get("lexical_score") or 0.0)

    top_score = lexical_score(hits[0])
    if top_score < high_threshold:
        return TIER_HINT
    runner_up_score = max((lexical_score(hit) for hit in hits[1:]), default=0.0)
    if runner_up_score >= floor and top_score < margin * runner_up_score:
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


def candidate_payload(hits: list[SkillHit], *, include_sources: bool = False) -> list[dict]:
    """JSON candidates: name/source/score; card mode also exposes family sources."""
    rows = []
    for hit in hits:
        row = {"name": hit.name, "source": hit.collection, "score": round(float(hit.score), 1)}
        if include_sources:
            row.update(candidate_debug_payload(hit))
        rows.append(row)
    return rows


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


def _print_json(query: str, hits: list[SkillHit], reason_code: str, elapsed_ms: float, extra: dict | None = None, *, include_candidate_sources: bool = False) -> None:
    payload = {
        "task_summary_hash": task_summary_hash(query),
        "top_3_skill_candidates": candidate_payload(hits, include_sources=include_candidate_sources),
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

    # Card/hook mode skips vector only for exact identity or a discriminative,
    # non-mixed lexical winner with a clear margin. Every rescue stays bounded:
    # cached query vectors or an already-warm, root-matched daemon only.
    retrieval_path = "lexical" if hits else "none"
    vector_status = "not_requested"
    needs_english = False
    non_english = not looks_english(args.query)
    lexical_hint_hits = recall_safe_hint_hits(hits, args.query)
    runner_up = hits[1] if len(hits) > 1 else None
    margin_clear = bool(
        hits
        and (
            runner_up is None
            or runner_up.score <= 0
            or hits[0].score >= args.high_margin * runner_up.score
        )
    )
    top_exact_identity = bool(hits and exact_identity_match(args.query, hits[0]))
    lexical_decisive = top_exact_identity or bool(
        not non_english
        and lexical_hint_hits
        and reason_code == REASON_MATCH_FOUND
        and margin_clear
    )
    if args.card and not lexical_decisive:
        if _vector_fallback_disabled():
            vector_status = "disabled"
        elif sidecar_installed(root):
            vector_status = "compatible_no_in_budget_hits"
            vector_hits = vector_probe(root, args.query, fetch_limit, args.collection)
            if vector_hits:
                hits = shared_candidate_family(
                    root,
                    args.query,
                    fetch_limit,
                    collection=args.collection,
                    vector_hits=vector_hits,
                )
                reason_code = REASON_MATCH_FOUND if hits and hits[0].score >= args.floor else REASON_LOW_CONFIDENCE
                retrieval_path = "hybrid" if any("lexical" in candidate_debug_payload(hit).get("candidate_sources", []) for hit in hits) else "vector"
                vector_status = "available_used"
        elif non_english and reason_code != REASON_MATCH_FOUND:
            vector_status = "unavailable_missing_sidecar"

    # Mixed-language prompts need an explicit recovery action unless exact
    # identity or a strong semantic hint actually resolved them.
    semantic_rescue_succeeded = any(
        float(candidate_debug_payload(hit).get("vector_score") or 0.0) >= VECTOR_HINT_MIN
        for hit in hits
    )
    if non_english and not (top_exact_identity or semantic_rescue_succeeded):
        needs_english = True

    hint_hits = recall_safe_hint_hits(hits, args.query)
    card_hits = card_safe_hits(
        hint_hits,
        query=args.query,
        floor=args.floor,
        mixed_language_uncertain=non_english and reason_code != REASON_MATCH_FOUND,
    )

    # The new routing fields ride only on the --card channel (the hook's mode);
    # the plain --json contract stays byte-identical for existing consumers.
    extra: dict = {}
    tier = None
    injected = False
    card_obj = None
    if args.card:
        extra["retrieval_path"] = retrieval_path
        extra["vector_status"] = vector_status
        # Keep the existing candidate family as diagnostics, but expose the
        # exact floor-filtered delivery surface separately so hook consumers
        # never have to infer it from scores or accidentally forward noise.
        extra["schema_version"] = 2
        extra["minimum_score"] = args.floor
        extra["hint_policy_revision"] = "hint-policy-v1"
        extra["hint_minimum_score"] = HINT_FLOOR
        extra["retrieval_candidates"] = candidate_payload(
            hits[: args.limit], include_sources=True
        )
        extra["delivery_candidates"] = candidate_payload(
            hint_hits[: args.limit], include_sources=True
        )
        extra["card_candidates"] = candidate_payload(card_hits[:1], include_sources=True)
        if needs_english:
            extra["needs_english_query"] = True
        tier = TIER_SILENCE
        if hint_hits:
            tier = TIER_HINT
        if card_hits:
            tier = select_card_tier(
                card_hits,
                floor=args.floor,
                high_threshold=args.high_threshold,
                margin=args.high_margin,
            )
        if tier == TIER_CARD and not kill_switch_active():
            card_text = build_skill_card(card_hits[0], max_chars=args.card_max_chars)
            if card_text:
                card_obj = {
                    "name": card_hits[0].name,
                    "source": card_hits[0].collection,
                    "card": card_text,
                }
        if tier == TIER_CARD and card_obj is None:
            tier = TIER_HINT  # kill switch or unreadable SKILL.md: degrade, never block
        injected = card_obj is not None
        extra["delivery_tier"] = tier  # update, never reassign: keep retrieval_path/needs_english_query
        extra["delivery"] = {
            "mode": "card" if tier == TIER_CARD else ("hint" if tier == TIER_HINT else ("rescue" if needs_english else "silence")),
            "hint_candidates": candidate_payload(hint_hits[: args.limit], include_sources=True),
            "card_candidate": candidate_payload(card_hits[:1], include_sources=True)[0]
            if tier == TIER_CARD and card_hits
            else None,
        }
        if card_obj is not None:
            extra["skill_card"] = card_obj
    display_hits = hits[: args.limit]
    json_hits = hint_hits[: args.limit] if args.card else display_hits
    # Explicit plain-text suggest remains the score-floor CLI contract. The
    # stricter safe-hint/card filter belongs only to the ambient --card path.
    text_hits = (
        card_hits[: args.limit]
        if args.card
        else [hit for hit in display_hits if hit.score >= args.floor]
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    if args.json:
        _print_json(args.query, json_hits, reason_code, elapsed_ms, extra, include_candidate_sources=bool(args.card))
    else:
        for hit in text_hits:
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
            "query": args.query,
            "task_summary_hash": task_summary_hash(args.query),
            "floor": args.floor,
            "elapsed_ms": round(elapsed_ms, 1),
            "reason_code": reason_code,
            "low_confidence": reason_code == REASON_LOW_CONFIDENCE,
            "injected": injected,
            "score_bucket": score_bucket(top_score),
            "margin_bucket": margin_bucket(top_score, runner_up_score),
            "hits": [{"name": hit.name, "score": hit.score} for hit in display_hits],
            "retrieved_candidates": [hit.name for hit in display_hits],
            "shown_candidates": [hit.name for hit in hint_hits[: args.limit]] if args.card else [hit.name for hit in text_hits],
            "card_injected_candidate": card_obj.get("name") if isinstance(card_obj, dict) else None,
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
