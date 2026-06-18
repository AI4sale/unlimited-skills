"""Lightweight lexical search core for Unlimited Skills.

This module is the import-cheap heart of skill retrieval: index layout,
tokenization, lexical scoring, and event logging. It deliberately imports
only the standard library plus :mod:`unlimited_skills.frontmatter`, so the
fast `suggest` probe (and hooks that shell out to it) can run without paying
for the full CLI import graph (hub, registration, billing, MCP, ...).

`unlimited_skills.cli` re-exports everything defined here, so existing code
and tests that reach through ``cli.<name>`` keep working unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .frontmatter import split_frontmatter as _shared_split_frontmatter

DEFAULT_ROOT = Path(os.environ.get("UNLIMITED_SKILLS_ROOT", Path.home() / ".unlimited-skills" / "library"))
INDEX_NAME = ".unlimited-skills-index.json"
EVENT_LOG = "events.jsonl"
# Internal router-invocation counter (separate from the verbose event log): a
# tiny, always-current JSON meter answering "how many times has the router been
# called, and when/how fast was the last call?" without grepping events.jsonl.
ROUTER_METRICS = "router-metrics.json"
# Keep the per-day histogram bounded so the meter file never grows unbounded.
ROUTER_METRICS_MAX_DAYS = 90
# Session correlation (A3.1.1 effectiveness v2 instrumentation): the
# UserPromptSubmit hook forwards the Claude Code session id through
# SESSION_ID_ENV; agent-run CLI commands fall back to CLAUDE_SESSION_ID when
# the harness exports it. Only the SHORT HASH ever reaches the event log —
# the raw id is never written anywhere.
SESSION_ID_ENV = "UNLIMITED_SKILLS_SESSION_ID"
SESSION_ID_FALLBACK_ENV = "CLAUDE_SESSION_ID"
SESSION_HASH_LEN = 12
# A machine-local PRIVATE salt makes the correlation token non-reversible and
# not stable across machines (an unsalted sha256 of the raw id would be a
# globally-stable fingerprint). The salt is generated once, persisted locally,
# and NEVER printed, logged, or uploaded. An env override exists for tests and
# for operators who want to pin it.
SESSION_SALT_ENV = "UNLIMITED_SKILLS_SESSION_SALT"
SESSION_SALT_FILE = ".session_salt"
_SALT_CACHE: str | None = None
_RUN_CORRELATION_CACHE: str | None = None
WORD_RE = re.compile(r"(?u)[^\W_][\w+.#/-]*")
IGNORED_SKILL_PATH_PARTS = {
    ".chroma-skills",
    ".git",
    ".learning",
    "duplicates",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
# Function words carry no skill signal but used to inflate lexical scores
# (every "Use when the user asks..." description matched "what is the ..."
# prompts). Filtered symmetrically from queries and skill text.
STOPWORDS = frozenset(
    """
    a an the and or but if then else nor of to in on at by with from into onto
    over under is are was were be been being am do does did done doing have has
    had having can could should would will shall may might must this that these
    those it its as not no yes you your yours me my mine we us our ours they
    them their theirs he him his she her hers who whom whose what which how
    when where why all any both each few more most other some such only own
    same so than too very just about also there here while during before after
    above below again further once please help want wants need needs use using
    used user users ask asks
    и в во не на я с со как а то все она так его но да ты к у же вы за бы по
    только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг
    ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом
    себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам
    чтоб без будто чего раз тоже себе под будет ж тогда кто этот
    """.split()
)

QUERY_EXPANSIONS = {
    "rerender": "re-render render rendering react component performance memo memoization",
    "re-render": "rerender render rendering react component performance memo memoization",
    "memoization": "memo usememo usecallback react performance",
    "component": "components react jsx tsx frontend",
    "components": "component react jsx tsx frontend",
    "oauth": "auth authentication authorization credentials token secret",
    "test": "tests testing",
    "tests": "test testing",
    "testing": "test tests",
    "write": "writing",
    "writing": "write written",
    "docs": "documentation readme document",
    "documentation": "docs readme document",
    "readme": "documentation docs",
    "sql": "postgres postgresql mysql database query index",
    "prompt": "prompts prompting",
    "prompts": "prompt prompting",
    "social": "social media linkedin post content marketing",
    "media": "social media linkedin post content marketing",
    "content": "content social media linkedin post marketing",
    # Performance-measurement vocabulary: profiling and benchmarking name the
    # same activity (measure, compare, find the slow part) in different tools.
    "profiling": "profiler benchmark benchmarking performance measure",
    "profiler": "profiling benchmark benchmarking performance",
    "benchmark": "benchmarks benchmarking profiling performance",
    "benchmarking": "benchmark benchmarks profiling performance",
    # Release vocabulary: changelogs/release notes/versioning are one workflow.
    "changelog": "release notes versioning history",
    "versioning": "version semver release changelog",
    # Refactoring synonyms (verb stemming + common aliases).
    "refactor": "refactoring restructure cleanup",
    "refactoring": "refactor restructure cleanup",
    "pr": "pull request github review merge",
    "токены": "token tokens oauth credentials auth secret",
    "безопасно": "security secure secrets credentials auth",
    "скил": "skill procedure workflow",
    "скилы": "skills procedures workflows",
    "линкедин": "linkedin social content post marketing",
    "linkedin": "linkedin social content post marketing",
    "пост": "post content social writing",
    "релиз": "release launch changelog announcement marketing",
    "обнови": "update upgrade refresh repair",
    "после": "after upgrade refresh repair",
}

# Multi-word aliases applied on the lowercased query before token expansion:
# bigrams like "pull request" carry an ecosystem meaning their individual
# tokens lack ("pull" and "request" alone are generic verbs/nouns).
PHRASE_EXPANSIONS = {
    "pull request": "pr github merge review branch",
    "merge request": "pr mr github gitlab merge review",
    "release notes": "changelog release versioning publish github",
    "social media": "linkedin post content marketing campaign",
    "social media content": "linkedin post content marketing campaign",
}

# Ecosystem ranking guard (A0 fix): when the query clearly names one
# language/framework ecosystem and a skill clearly names a DIFFERENT one,
# the skill's lexical score is multiplied by ECOSYSTEM_PENALTY. This stops
# wrong-ecosystem skills (e.g. `flutter-dart-code-review`) from outranking
# the right ones (e.g. `python-patterns`) on generic shared tokens like
# "code review". Skills and queries with no ecosystem signal are untouched.
ECOSYSTEM_PENALTY = 0.4
ECOSYSTEM_TOKEN_GROUPS: dict[str, frozenset[str]] = {
    "python": frozenset({"python", "django", "flask", "fastapi", "pytest", "pep8", "pip", "pytorch"}),
    "react": frozenset({"react", "jsx", "nextjs"}),
    "vue": frozenset({"vue", "nuxt", "nuxt4"}),
    "angular": frozenset({"angular"}),
    "javascript": frozenset({"javascript", "nodejs", "node", "npm", "bun", "vite"}),
    "typescript": frozenset({"typescript", "tsx"}),
    "flutter": frozenset({"flutter", "dart"}),
    "go": frozenset({"golang"}),
    "rust": frozenset({"rust", "cargo"}),
    "kotlin": frozenset({"kotlin", "ktor"}),
    "java": frozenset({"java", "spring", "springboot", "quarkus", "jpa"}),
    "csharp": frozenset({"csharp", "dotnet", "fsharp"}),
    "cpp": frozenset({"cpp", "c++", "cmake"}),
    "swift": frozenset({"swift", "swiftui", "ios"}),
    "php": frozenset({"php", "laravel"}),
    "perl": frozenset({"perl"}),
    "ruby": frozenset({"ruby", "rails"}),
    "n8n": frozenset({"n8n"}),
    "healthcare": frozenset({"healthcare", "emr", "hipaa", "phi", "cdss"}),
    "blockchain": frozenset({"defi", "evm", "solidity", "blockchain", "crypto", "trading", "wallet"}),
}
# Mild demotion for ecosystem-specific skills on ecosystem-neutral queries:
# a generic "code review checklist" query should rank generic review skills
# above `flutter-dart-code-review`, without hiding the specific skill.
ECOSYSTEM_NEUTRAL_QUERY_PENALTY = 0.8


@dataclass
class SkillHit:
    name: str
    description: str
    collection: str
    path: str
    score: float = 0.0


VECTOR_SCORE_WEIGHT = 20.0
LEARNING_BOOST_WEIGHT = 6.0
LEARNING_DEMOTION_WEIGHT = 6.0
LEARNING_MAX_ADJUSTMENT = 6.0


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").lstrip("﻿")


def write_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def task_summary_hash(query: object) -> str:
    """Short sha256 of normalized task/query text; never store the raw text."""
    normalized = " ".join(str(query or "").split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def token_summary_hash(token: object) -> str:
    """Short sha256 for one normalized query token; never store the token."""
    normalized = str(token or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    return _shared_split_frontmatter(text, lower_keys=True)


def first_body_line(body: str) -> str:
    for line in body.splitlines():
        line = line.strip(" #\t")
        if line:
            return line[:240]
    return ""


def tokens(text: str) -> set[str]:
    result: set[str] = set()
    for match in WORD_RE.finditer(text or ""):
        raw = match.group(0).lower().strip("-_/")
        if len(raw) > 1 and raw not in STOPWORDS:
            result.add(raw)
        for part in re.split(r"[-_/]+", raw):
            if len(part) > 1 and part not in STOPWORDS:
                result.add(part)
    return result


def expanded_query(query: str) -> str:
    q_lower = (query or "").lower()
    extras = [expansion for phrase, expansion in PHRASE_EXPANSIONS.items() if phrase in q_lower]
    q_tokens = tokens(query)
    extras.extend(QUERY_EXPANSIONS[tok] for tok in q_tokens if tok in QUERY_EXPANSIONS)
    return query + (" " + " ".join(extras) if extras else "")


def collection_for(root: Path, skill_file: Path) -> str:
    rel = skill_file.relative_to(root)
    if len(rel.parts) > 3 and rel.parts[0] == "registry":
        return rel.parts[1]
    if len(rel.parts) > 2 and rel.parts[0] == "local":
        return "local"
    return rel.parts[0] if len(rel.parts) > 1 else "default"


def skill_identity(name: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", str(name or "").strip().lower()).strip("-")


def skill_priority(root: Path, skill_file: Path, collection: str) -> tuple[int, str]:
    rel = skill_file.relative_to(root)
    parts = rel.parts
    if len(parts) > 2 and parts[0] == "local" and parts[1] == "skills":
        return (0, str(rel).lower())
    if collection == "ecc":
        return (10, str(rel).lower())
    if collection == "superpowers":
        return (20, str(rel).lower())
    if len(parts) > 1 and parts[0] == "registry":
        return (30, str(rel).lower())
    if len(parts) > 1 and parts[0] == "local":
        return (40, str(rel).lower())
    return (50, str(rel).lower())


def iter_skills(root: Path) -> Iterable[tuple[SkillHit, str]]:
    if not root.exists():
        return
    candidates = []
    for skill_file in root.rglob("SKILL.md"):
        rel_parts = skill_file.relative_to(root).parts
        if any(part in IGNORED_SKILL_PATH_PARTS for part in rel_parts):
            continue
        try:
            text = read_text(skill_file)
        except OSError:
            continue
        meta, body = split_frontmatter(text)
        name = meta.get("name") or skill_file.parent.name
        desc = meta.get("description") or first_body_line(body)
        collection = collection_for(root, skill_file)
        candidates.append((skill_priority(root, skill_file, collection), skill_identity(name), SkillHit(name=name, description=desc, collection=collection, path=str(skill_file)), body))

    seen: set[str] = set()
    for _priority, identity, hit, body in sorted(candidates, key=lambda item: (item[0], item[2].collection, item[2].name)):
        if identity in seen:
            continue
        seen.add(identity)
        yield hit, body


def index_path(root: Path) -> Path:
    return root / INDEX_NAME


def build_index(root: Path) -> list[dict]:
    records = []
    for hit, body in iter_skills(root):
        records.append(
            {
                "name": hit.name,
                "description": hit.description,
                "collection": hit.collection,
                "path": hit.path,
                "search_text": body[:12000],
            }
        )
    return sorted(records, key=lambda row: (row["collection"], row["name"]))


def save_index(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = index_path(root)
    path.write_text(json.dumps(build_index(root), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_records(root: Path, fresh: bool = False) -> list[tuple[SkillHit, str]]:
    path = index_path(root)
    if not fresh and path.is_file():
        try:
            raw = json.loads(read_text(path))
            records = []
            for row in raw if isinstance(raw, list) else []:
                if not isinstance(row, dict):
                    continue
                records.append(
                    (
                        SkillHit(
                            name=str(row.get("name") or ""),
                            description=str(row.get("description") or ""),
                            collection=str(row.get("collection") or "default"),
                            path=str(row.get("path") or ""),
                        ),
                        str(row.get("search_text") or ""),
                    )
                )
            return records
        except (OSError, json.JSONDecodeError):
            pass
    return list(iter_skills(root))


def _ecosystems(token_set: set[str]) -> set[str]:
    return {eco for eco, eco_tokens in ECOSYSTEM_TOKEN_GROUPS.items() if eco_tokens & token_set}


def ecosystem_factor(query_tokens: set[str], hit: SkillHit) -> float:
    """Return the ecosystem-mismatch score multiplier (1.0 = no penalty)."""
    skill_ecos = _ecosystems(tokens(hit.name) | tokens(hit.description))
    if not skill_ecos:
        return 1.0
    query_ecos = _ecosystems(query_tokens)
    if not query_ecos:
        return ECOSYSTEM_NEUTRAL_QUERY_PENALTY
    if skill_ecos & query_ecos:
        return 1.0
    return ECOSYSTEM_PENALTY


def score_skill(query: str, hit: SkillHit, body: str) -> float:
    expanded = expanded_query(query)
    query_tokens = tokens(expanded)
    if not query_tokens:
        return 0.0

    name_tokens = tokens(hit.name)
    desc_tokens = tokens(hit.description)
    body_tokens = tokens(body[:12000])

    score = 0.0
    score += 6.0 * len(query_tokens & name_tokens)
    score += 3.0 * len(query_tokens & desc_tokens)
    score += 1.0 * len(query_tokens & body_tokens)

    q_lower = expanded.lower()
    if q_lower and q_lower in hit.name.lower():
        score += 8.0
    if q_lower and q_lower in hit.description.lower():
        score += 5.0
    if hit.name.lower() in q_lower:
        score += 10.0
    if "react" in query_tokens and hit.name.lower().startswith("react-"):
        score += 8.0
    if "n8n" in query_tokens and hit.name.lower().startswith("n8n-"):
        score += 8.0
    return score * ecosystem_factor(tokens(query), hit)


def _clone_hit(hit: SkillHit, *, score: float | None = None) -> SkillHit:
    return SkillHit(
        name=hit.name,
        description=hit.description,
        collection=hit.collection,
        path=hit.path,
        score=float(hit.score if score is None else score),
    )


def _candidate_key(hit: SkillHit) -> str:
    path = str(hit.path or "").strip()
    if path:
        return "path:" + path
    return "name:" + skill_identity(hit.name)


def _set_candidate_metadata(
    hit: SkillHit,
    *,
    sources: Iterable[str],
    lexical_score: float = 0.0,
    vector_score: float = 0.0,
    learning_adjustment: float = 0.0,
    lexical_rank: int | None = None,
    vector_rank: int | None = None,
    rank: int | None = None,
) -> SkillHit:
    clean_sources = tuple(sorted({source for source in sources if source}))
    setattr(hit, "candidate_sources", clean_sources)
    setattr(hit, "lexical_score", round(float(lexical_score), 3))
    setattr(hit, "vector_score", round(float(vector_score), 3))
    setattr(hit, "learning_adjustment", round(float(learning_adjustment), 3))
    setattr(hit, "exact_match", "exact_name" in clean_sources or "name" in clean_sources)
    setattr(hit, "learning_boost", float(learning_adjustment) > 0.0)
    setattr(hit, "learning_demotion", float(learning_adjustment) < 0.0)
    if lexical_rank is not None:
        setattr(hit, "lexical_rank", int(lexical_rank))
    if vector_rank is not None:
        setattr(hit, "vector_rank", int(vector_rank))
    if rank is not None:
        setattr(hit, "candidate_rank", int(rank))
        setattr(hit, "final_rank", int(rank))
        setattr(hit, "hybrid_or_fusion_rank", int(rank))
    return hit


def candidate_sources(hit: SkillHit) -> tuple[str, ...]:
    value = getattr(hit, "candidate_sources", ())
    return tuple(str(item) for item in value if str(item))


def candidate_debug_payload(hit: SkillHit) -> dict[str, object]:
    """Comparable retrieval explanation fields for search/suggest verifiers."""
    payload: dict[str, object] = {
        "candidate_sources": list(candidate_sources(hit)),
        "exact_match": bool(getattr(hit, "exact_match", False)),
        "lexical_score": round(float(getattr(hit, "lexical_score", 0.0) or 0.0), 3),
        "vector_score": round(float(getattr(hit, "vector_score", 0.0) or 0.0), 3),
        "learning_boost": bool(getattr(hit, "learning_boost", False)),
        "learning_demotion": bool(getattr(hit, "learning_demotion", False)),
        "confidence": score_bucket(float(getattr(hit, "score", 0.0) or 0.0)),
    }
    for source_attr, output_key in (
        ("lexical_rank", "lexical_rank"),
        ("vector_rank", "vector_rank"),
        ("hybrid_or_fusion_rank", "hybrid_or_fusion_rank"),
        ("final_rank", "final_rank"),
        ("candidate_rank", "candidate_rank"),
    ):
        value = getattr(hit, source_attr, None)
        if value is not None:
            payload[output_key] = int(value)
    return payload


def _source_markers(query: str, hit: SkillHit, body: str) -> set[str]:
    expanded = expanded_query(query)
    base_tokens = tokens(query)
    expanded_tokens = tokens(expanded)
    skill_name_tokens = tokens(hit.name)
    description_tokens = tokens(hit.description)
    body_tokens = tokens(body[:12000])
    markers: set[str] = set()
    if base_tokens & skill_name_tokens:
        markers.add("name")
    if base_tokens & description_tokens:
        markers.add("description")
    if base_tokens & body_tokens:
        markers.add("body")
    if (expanded_tokens - base_tokens) & (skill_name_tokens | description_tokens | body_tokens):
        markers.add("query_expansion")
    q_lower = (query or "").lower()
    expanded_lower = expanded.lower()
    name_lower = (hit.name or "").lower()
    if name_lower and (name_lower in q_lower or skill_identity(hit.name).replace("-", " ") in expanded_lower):
        markers.add("exact_name")
    if not markers:
        markers.add("lexical")
    return markers


def _read_learning_adjustments(root: Path, query: str) -> dict[str, float]:
    from .learning_ranker import learning_adjustments_for_query

    return learning_adjustments_for_query(root, query)


def shared_candidate_family(
    root: Path,
    query: str,
    limit: int,
    *,
    collection: str | None = None,
    fresh: bool = False,
    vector_hits: Iterable[SkillHit] | None = None,
    vector_weight: float = VECTOR_SCORE_WEIGHT,
) -> list[SkillHit]:
    """Merge and rank every supported retrieval source through one family.

    The function is intentionally cheap when ``vector_hits`` is omitted: it
    imports no embedding dependencies and uses the same lexical index as the
    fast ``suggest`` path. Callers with vector results pass them in, and the
    same merge/rank/source metadata is used by search, suggest, and hooks.
    """
    query = (query or "").strip()
    if not query:
        return []
    requested = max(int(limit or 1), 1)
    scan_limit = max(requested * 3, 12)
    adjustments = _read_learning_adjustments(root, query)
    merged: dict[str, SkillHit] = {}
    meta: dict[str, dict[str, object]] = {}
    lexical_order: list[str] = []
    vector_order: list[str] = []

    for hit, body in load_records(root, fresh=fresh):
        if collection and hit.collection != collection:
            continue
        lexical_score = score_skill(query, hit, body)
        if lexical_score <= 0.0:
            continue
        item = _clone_hit(hit, score=lexical_score)
        key = _candidate_key(item)
        learning_adjustment = adjustments.get(skill_identity(item.name), 0.0)
        item.score = max(0.0, lexical_score + learning_adjustment)
        sources = _source_markers(query, item, body)
        sources.add("lexical")
        if learning_adjustment > 0:
            sources.add("learning_boost")
        elif learning_adjustment < 0:
            sources.add("learning_demotion")
        merged[key] = item
        meta[key] = {
            "sources": sources,
            "lexical_score": lexical_score,
            "vector_score": 0.0,
            "learning_adjustment": learning_adjustment,
        }
        lexical_order.append(key)

    for raw_vector_hit in vector_hits or []:
        if collection and raw_vector_hit.collection != collection:
            continue
        key = _candidate_key(raw_vector_hit)
        vector_score = float(getattr(raw_vector_hit, "score", 0.0) or 0.0)
        if vector_score <= 0.0:
            continue
        learning_adjustment = adjustments.get(skill_identity(raw_vector_hit.name), 0.0)
        weighted = vector_score * vector_weight
        if key in merged:
            merged[key].score = max(0.0, float(merged[key].score) + weighted)
            row = meta[key]
            row["vector_score"] = vector_score
            sources = set(row.get("sources") or ())
            sources.add("vector")
            row["sources"] = sources
        else:
            item = _clone_hit(raw_vector_hit, score=max(0.0, weighted + learning_adjustment))
            merged[key] = item
            sources = {"vector"}
            if learning_adjustment > 0:
                sources.add("learning_boost")
            elif learning_adjustment < 0:
                sources.add("learning_demotion")
            meta[key] = {
                "sources": sources,
                "lexical_score": 0.0,
                "vector_score": vector_score,
                "learning_adjustment": learning_adjustment,
            }
        vector_order.append(key)

    hits = list(merged.values())
    hits.sort(key=lambda item: (-item.score, item.collection, item.name))
    lexical_ranks = {
        key: rank
        for rank, key in enumerate(
            sorted(
                lexical_order,
                key=lambda candidate_key: (
                    -float(meta[candidate_key].get("lexical_score") or 0.0),
                    merged[candidate_key].collection,
                    merged[candidate_key].name,
                ),
            ),
            start=1,
        )
    }
    vector_ranks = {
        key: rank
        for rank, key in enumerate(
            sorted(
                vector_order,
                key=lambda candidate_key: (
                    -float(meta[candidate_key].get("vector_score") or 0.0),
                    merged[candidate_key].collection,
                    merged[candidate_key].name,
                ),
            ),
            start=1,
        )
    }
    for rank, hit in enumerate(hits[:scan_limit], start=1):
        key = _candidate_key(hit)
        row = meta.get(key, {})
        _set_candidate_metadata(
            hit,
            sources=row.get("sources") or (),
            lexical_score=float(row.get("lexical_score") or 0.0),
            vector_score=float(row.get("vector_score") or 0.0),
            learning_adjustment=float(row.get("learning_adjustment") or 0.0),
            lexical_rank=lexical_ranks.get(key),
            vector_rank=vector_ranks.get(key),
            rank=rank,
        )
    return hits[:requested]


def find_by_name(root: Path, name: str) -> Path | None:
    wanted = name.lower()
    candidates = []
    for hit, _ in iter_skills(root):
        if hit.name.lower() == wanted or Path(hit.path).parent.name.lower() == wanted:
            candidates.append(Path(hit.path))
    candidates.sort(key=lambda path: (len(str(path)), str(path).lower()))
    return candidates[0] if candidates else None


def lexical_search(root: Path, query: str, limit: int, collection: str | None = None, fresh: bool = False) -> list[SkillHit]:
    return shared_candidate_family(root, query, limit, collection=collection, fresh=fresh)


def _salt_path() -> Path:
    """Machine-local home for the private salt (sibling of the library root)."""
    return DEFAULT_ROOT.parent / SESSION_SALT_FILE


def _local_salt() -> str:
    """Read-or-create the machine-local private salt — never printed or uploaded.

    Stable on this machine (so a session correlates across suggest -> view ->
    use) but random per machine (so the correlation token is not a portable
    fingerprint). Falls back to an in-memory salt if the home is read-only.
    """
    global _SALT_CACHE
    if _SALT_CACHE is not None:
        return _SALT_CACHE
    override = os.environ.get(SESSION_SALT_ENV)
    if override and override.strip():
        _SALT_CACHE = override.strip()
        return _SALT_CACHE
    path = _salt_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            _SALT_CACHE = existing
            return _SALT_CACHE
    except OSError:
        pass
    salt = secrets.token_hex(16)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(salt, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        pass  # read-only home: the in-memory salt still scopes this process
    _SALT_CACHE = salt
    return _SALT_CACHE


def hash_session_id(session_id: object, salt: str | None = None) -> str | None:
    """Short SALTED sha256 of a session id — a correlation token, never the raw id.

    The id is hashed with the machine-local private salt (:func:`_local_salt`),
    so the token is non-reversible and not stable across machines. Returns None
    for an empty/missing id.
    """
    normalized = str(session_id or "").strip()
    if not normalized:
        return None
    salt = _local_salt() if salt is None else salt
    digest = hashlib.sha256(f"{salt}\x1f{normalized}".encode("utf-8")).hexdigest()
    return digest[:SESSION_HASH_LEN]


def _run_correlation_id() -> str:
    """Per-process correlation id used when no harness session id is present.

    Lets the suggest -> view -> use chain correlate within a single local
    invocation without fabricating a stable cross-session/cross-machine
    fingerprint. The underlying token is process-ephemeral and salted.
    """
    global _RUN_CORRELATION_CACHE
    if _RUN_CORRELATION_CACHE is None:
        token = f"{_local_salt()}\x1frun\x1f{secrets.token_hex(16)}"
        _RUN_CORRELATION_CACHE = hashlib.sha256(token.encode("utf-8")).hexdigest()[:SESSION_HASH_LEN]
    return _RUN_CORRELATION_CACHE


def session_correlation_id() -> str | None:
    """Salted correlation token for the current session, never None in practice.

    Sources, in order: ``UNLIMITED_SKILLS_SESSION_ID`` (set by the
    UserPromptSubmit hook for its probe subprocess) and ``CLAUDE_SESSION_ID``
    (when the agent harness exports it to shell commands), each salted-hashed
    via :func:`hash_session_id`. When neither is present the value degrades to a
    per-process run id (:func:`_run_correlation_id`) so a standalone invocation
    still correlates its own events. The raw session id is never logged.
    """
    for env_name in (SESSION_ID_ENV, SESSION_ID_FALLBACK_ENV):
        value = os.environ.get(env_name)
        if value and value.strip():
            return hash_session_id(value)
    return _run_correlation_id()


def score_bucket(score: float | None) -> str:
    """Coarse band for a top hit's score — never the raw value, never the query.

    Bands track the frozen-eval calibration: the floor sits at 12, true
    positives run 12-51, and the tier-3 card threshold is high. Buckets let the
    effectiveness summary describe match strength without logging exact scores
    that could, in aggregate, fingerprint a private query set.
    """
    if score is None:
        return "none"
    s = float(score)
    if s < 12.0:
        return "below_floor"
    if s < 18.0:
        return "low"
    if s < 25.0:
        return "medium"
    if s < 40.0:
        return "high"
    return "very_high"


def margin_bucket(top: float | None, runner_up: float | None) -> str:
    """Coarse band for the top/runner-up score ratio (tier-3 margin gate input).

    ``no_runner_up`` when there is no second hit above the floor; otherwise the
    ratio is bucketed around the 1.5x high-confidence margin so the summary can
    show how often rankings were contested vs dominant.
    """
    if top is None or runner_up is None or float(runner_up) <= 0.0:
        return "no_runner_up"
    ratio = float(top) / float(runner_up)
    if ratio < 1.1:
        return "contested"
    if ratio < 1.5:
        return "slim"
    if ratio < 2.0:
        return "clear"
    if ratio < 3.0:
        return "strong"
    return "dominant"


def _relative_library_path(root: Path, path_text: object) -> str:
    """Return a library-relative path, never an absolute local path."""
    text = str(path_text or "").strip()
    if not text:
        return ""
    try:
        return Path(text).resolve().relative_to(Path(root).resolve()).as_posix()
    except (OSError, ValueError):
        return ""


def _notes_bucket(text: object) -> str:
    length = len(str(text or ""))
    if length <= 0:
        return "empty"
    if length <= 80:
        return "short"
    if length <= 400:
        return "medium"
    return "long"


def _safe_hit_payload(root: Path, raw: object) -> dict:
    if isinstance(raw, SkillHit):
        source = {
            "name": raw.name,
            "collection": raw.collection,
            "description": raw.description,
            "score": raw.score,
            "path": raw.path,
        }
    elif isinstance(raw, dict):
        source = raw
    else:
        return {}
    payload = {
        "name": str(source.get("name") or ""),
        "collection": str(source.get("collection") or source.get("source") or ""),
    }
    if source.get("description"):
        payload["description"] = str(source.get("description") or "")
    if "score" in source:
        try:
            payload["score_bucket"] = score_bucket(float(source.get("score")))
        except (TypeError, ValueError):
            payload["score_bucket"] = "none"
    library_path = _relative_library_path(root, source.get("path") or source.get("library_path"))
    if library_path:
        payload["library_path"] = library_path
    return {key: value for key, value in payload.items() if value not in {"", None}}


def event_safe_payload(root: Path, event_type: str, payload: dict) -> dict:
    """Sanitize local event payloads before writing ``events.jsonl``.

    Local event logs are diagnostics, not support artifacts. They must never
    persist raw task/query text, freeform notes, or absolute filesystem paths.
    """
    safe = dict(payload)
    for field in ("query", "task", "filter"):
        value = safe.pop(field, "")
        if value:
            safe[f"{field}_summary_hash"] = task_summary_hash(value)
            safe[f"{field}_present"] = True
            if field == "query":
                safe["query_token_hashes"] = [token_summary_hash(token) for token in sorted(tokens(str(value)))[:40]]
    notes = safe.pop("notes", "")
    if notes:
        safe["notes_present"] = True
        safe["notes_length_bucket"] = _notes_bucket(notes)
    path_value = safe.pop("path", "")
    library_path = _relative_library_path(root, path_value)
    if library_path:
        safe["library_path"] = library_path
    if isinstance(safe.get("hits"), list):
        safe["hits"] = [_safe_hit_payload(root, hit) for hit in safe["hits"]]
    return safe


def log_event(root: Path, event_type: str, payload: dict) -> None:
    # A3.1.1: stamp every event with the hashed session id (when the harness
    # exports one) so suggest -> view -> use can be correlated within a session
    # WITHOUT ever storing the raw id. Env-gated: outside a session no key is
    # added, so callers and tests that don't set it see the original payload.
    enriched = event_safe_payload(root, event_type, payload)
    correlation = session_correlation_id()
    if correlation and "session_correlation_id" not in enriched:
        enriched = {**enriched, "session_correlation_id": correlation}
    write_jsonl(
        root / ".learning" / EVENT_LOG,
        {"ts": time.time(), "type": event_type, "payload": enriched},
    )


def read_router_metrics(root: Path) -> dict:
    """Read the internal router-invocation counter, or ``{}``. Never raises.

    The meter lives at ``<root>/.learning/router-metrics.json`` and answers the
    operational question "is the router actually being called, and when last?".
    """
    path = Path(root) / ".learning" / ROUTER_METRICS
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_router_call(
    root: Path,
    *,
    elapsed_ms: float | None = None,
    reason_code: str = "",
    path: str = "",
    injected: bool = False,
    delivery_tier: int | None = None,
    top_skill: str = "",
    top_score: float | None = None,
) -> None:
    """Bump the router-invocation counter and stamp the last call. Best-effort.

    Every ``suggest`` invocation (the router probe) — whether fired by the
    UserPromptSubmit hook or run directly — flows through here, so
    ``total_invocations`` is the true "how many times the router was called"
    count and ``last_call`` is the timing of the most recent one. The write is
    atomic (temp file + ``os.replace``) and any failure is swallowed: the meter
    must never block or break the probe.

    Privacy mirrors :func:`event_safe_payload`: the meter stores ONLY a skill
    NAME, a numeric score, and outcome/timing codes — never the query/task
    text, never a filesystem path.
    """
    try:
        ts = time.time()
        iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
        day = time.strftime("%Y-%m-%d", time.gmtime(ts))
        data = read_router_metrics(root)
        total = int(data.get("total_invocations", 0) or 0) + 1
        by_day = data.get("by_day")
        if not isinstance(by_day, dict):
            by_day = {}
        try:
            by_day[day] = int(by_day.get(day, 0) or 0) + 1
        except (TypeError, ValueError):
            by_day[day] = 1
        if len(by_day) > ROUTER_METRICS_MAX_DAYS:
            for stale in sorted(by_day)[:-ROUTER_METRICS_MAX_DAYS]:
                by_day.pop(stale, None)
        last_call = {"ts": round(ts, 3), "iso": iso, "reason_code": reason_code, "injected": bool(injected)}
        if path:
            last_call["path"] = path
        if elapsed_ms is not None:
            last_call["elapsed_ms"] = round(float(elapsed_ms), 1)
        if delivery_tier is not None:
            last_call["delivery_tier"] = delivery_tier
        if top_skill:
            last_call["top_skill"] = top_skill
        if top_score is not None:
            last_call["top_score"] = round(float(top_score), 1)
        out = {
            "total_invocations": total,
            "first_call_iso": data.get("first_call_iso") or iso,
            "updated_iso": iso,
            "last_call": last_call,
            "by_day": by_day,
        }
        path = Path(root) / ".learning" / ROUTER_METRICS
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(ROUTER_METRICS + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(out, handle, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError):
        pass
