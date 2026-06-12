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

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .frontmatter import split_frontmatter as _shared_split_frontmatter

DEFAULT_ROOT = Path(os.environ.get("UNLIMITED_SKILLS_ROOT", Path.home() / ".unlimited-skills" / "library"))
INDEX_NAME = ".unlimited-skills-index.json"
EVENT_LOG = "events.jsonl"
WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_+.#/-]*")
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
    "токены": "token tokens oauth credentials auth secret",
    "безопасно": "security secure secrets credentials auth",
    "скил": "skill procedure workflow",
    "скилы": "skills procedures workflows",
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


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").lstrip("﻿")


def write_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


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
    q_tokens = tokens(query)
    extras = [QUERY_EXPANSIONS[tok] for tok in q_tokens if tok in QUERY_EXPANSIONS]
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


def find_by_name(root: Path, name: str) -> Path | None:
    wanted = name.lower()
    candidates = []
    for hit, _ in iter_skills(root):
        if hit.name.lower() == wanted or Path(hit.path).parent.name.lower() == wanted:
            candidates.append(Path(hit.path))
    candidates.sort(key=lambda path: (len(str(path)), str(path).lower()))
    return candidates[0] if candidates else None


def lexical_search(root: Path, query: str, limit: int, collection: str | None = None, fresh: bool = False) -> list[SkillHit]:
    hits = []
    for hit, body in load_records(root, fresh=fresh):
        if collection and hit.collection != collection:
            continue
        hit.score = score_skill(query, hit, body)
        if hit.score > 0:
            hits.append(hit)
    hits.sort(key=lambda item: (-item.score, item.collection, item.name))
    return hits[:limit]


def log_event(root: Path, event_type: str, payload: dict) -> None:
    write_jsonl(
        root / ".learning" / EVENT_LOG,
        {"ts": time.time(), "type": event_type, "payload": payload},
    )
