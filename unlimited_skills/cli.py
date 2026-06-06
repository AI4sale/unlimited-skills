from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .adapters import SKILL_PACKS, adapt_library, apply_agent_adaptation, adaptation_task, install_pack, next_skill_for_agent


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_ROOT = Path(os.environ.get("UNLIMITED_SKILLS_ROOT", Path.home() / ".unlimited-skills" / "library"))
INDEX_NAME = ".unlimited-skills-index.json"
VECTOR_META_NAME = ".unlimited-skills-vector.json"
CHROMA_DIR_NAME = ".chroma-skills"
CHROMA_COLLECTION = "unlimited_skills_v1"
EVENT_LOG = "events.jsonl"
FEEDBACK_LOG = "feedback.jsonl"
WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_+.#/-]*")
IGNORED_SKILL_PATH_PARTS = {
    ".chroma-skills",
    ".git",
    ".learning",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
DEFAULT_EMBED_MODEL = os.environ.get(
    "UNLIMITED_SKILLS_EMBED_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
QUERY_EXPANSIONS = {
    "rerender": "re-render render rendering react component performance memo memoization",
    "re-render": "rerender render rendering react component performance memo memoization",
    "memoization": "memo usememo usecallback react performance",
    "component": "components react jsx tsx frontend",
    "components": "component react jsx tsx frontend",
    "oauth": "auth authentication authorization credentials token secret",
    "\u0442\u043e\u043a\u0435\u043d\u044b": "token tokens oauth credentials auth secret",
    "\u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e": "security secure secrets credentials auth",
    "\u0441\u043a\u0438\u043b": "skill procedure workflow",
    "\u0441\u043a\u0438\u043b\u044b": "skills procedures workflows",
}


@dataclass
class SkillHit:
    name: str
    description: str
    collection: str
    path: str
    score: float = 0.0


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")


def write_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return {}, text

    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key:
            meta[key] = value
    return meta, "\n".join(lines[end + 1 :])


def first_body_line(body: str) -> str:
    for line in body.splitlines():
        line = line.strip(" #\t")
        if line:
            return line[:240]
    return ""


def tokens(text: str) -> set[str]:
    return {m.group(0).lower().strip("-_/") for m in WORD_RE.finditer(text or "") if len(m.group(0)) > 1}


def expanded_query(query: str) -> str:
    q_tokens = tokens(query)
    extras = [QUERY_EXPANSIONS[tok] for tok in q_tokens if tok in QUERY_EXPANSIONS]
    return query + (" " + " ".join(extras) if extras else "")


def collection_for(root: Path, skill_file: Path) -> str:
    rel = skill_file.relative_to(root)
    return rel.parts[0] if len(rel.parts) > 1 else "default"


def iter_skills(root: Path) -> Iterable[tuple[SkillHit, str]]:
    if not root.exists():
        return
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
        yield SkillHit(name=name, description=desc, collection=collection_for(root, skill_file), path=str(skill_file)), body


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


def vector_text(hit: SkillHit, body: str) -> str:
    lines = []
    running_len = 0
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("```"):
            continue
        lines.append(stripped)
        running_len += len(stripped)
        if running_len > 3500:
            break
    return "\n".join(
        [
            f"Skill: {hit.name}",
            f"Collection: {hit.collection}",
            f"Description: {hit.description}",
            "Body:",
            "\n".join(lines),
        ]
    )[:5000]


def ensure_vector_deps():
    try:
        import chromadb  # type: ignore
        from fastembed import TextEmbedding  # type: ignore
        return chromadb, TextEmbedding
    except ImportError as exc:
        raise RuntimeError("Install vector dependencies with: pip install 'unlimited-skills[vector]'") from exc


def chroma_client(root: Path):
    chromadb, _ = ensure_vector_deps()
    return chromadb.PersistentClient(path=str(root / CHROMA_DIR_NAME))


def embed_texts(texts: list[str], model_name: str) -> list[list[float]]:
    _, TextEmbedding = ensure_vector_deps()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*now uses mean pooling.*")
        model = TextEmbedding(model_name=model_name)
    return [vec.tolist() if hasattr(vec, "tolist") else list(vec) for vec in model.embed(texts)]


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
    return score


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


def vector_search(root: Path, query: str, limit: int, model: str, collection_name: str | None = None) -> list[SkillHit]:
    collection = chroma_client(root).get_collection(CHROMA_COLLECTION)
    embedding = embed_texts([query], model)[0]
    result = collection.query(query_embeddings=[embedding], n_results=limit)
    metas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    hits = []
    for idx, meta in enumerate(metas):
        if not isinstance(meta, dict):
            continue
        if collection_name and str(meta.get("collection") or "") != collection_name:
            continue
        distance = float(distances[idx]) if idx < len(distances) else 1.0
        hits.append(
            SkillHit(
                name=str(meta.get("name") or ""),
                description=str(meta.get("description") or ""),
                collection=str(meta.get("collection") or ""),
                path=str(meta.get("path") or ""),
                score=max(0.0, 1.0 - distance),
            )
        )
    return hits


def hybrid_search(
    root: Path,
    query: str,
    limit: int,
    model: str,
    collection_name: str | None = None,
    fresh: bool = False,
    require_vector: bool = False,
) -> list[SkillHit]:
    merged = {hit.path: hit for hit in lexical_search(root, query, limit=max(limit * 3, 12), collection=collection_name, fresh=fresh)}
    try:
        for hit in vector_search(root, query, limit=max(limit * 3, 12), model=model, collection_name=collection_name):
            hit.score *= 20.0
            if hit.path in merged:
                merged[hit.path].score += hit.score
            else:
                merged[hit.path] = hit
    except Exception:
        if require_vector:
            raise
    hits = list(merged.values())
    hits.sort(key=lambda item: (-item.score, item.collection, item.name))
    return hits[:limit]


def emit_hits(hits: list[SkillHit], as_json: bool) -> int:
    if as_json:
        print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
        return 0
    if not hits:
        print("No matching skills found.")
        return 0
    for hit in hits:
        score = f" score={hit.score:.2f}" if hit.score else ""
        print(f"{hit.name} [{hit.collection}]{score}")
        if hit.description:
            print(f"  {hit.description}")
        print(f"  {hit.path}")
    return 0


def list_skills(root: Path, collection: str | None = None, filter_text: str = "", fresh: bool = False) -> list[SkillHit]:
    filter_tokens = tokens(filter_text)
    filter_lower = filter_text.lower().strip()
    hits = []
    for hit, body in load_records(root, fresh=fresh):
        if collection and hit.collection != collection:
            continue
        if filter_tokens:
            haystack = f"{hit.name}\n{hit.description}\n{body[:12000]}".lower()
            if filter_lower not in haystack and not (filter_tokens & tokens(haystack)):
                continue
        hits.append(hit)
    hits.sort(key=lambda item: (item.collection, item.name))
    return hits


def collection_counts(hits: list[SkillHit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit.collection] = counts.get(hit.collection, 0) + 1
    return dict(sorted(counts.items()))


def log_event(root: Path, event_type: str, payload: dict) -> None:
    write_jsonl(
        root / ".learning" / EVENT_LOG,
        {"ts": time.time(), "type": event_type, "payload": payload},
    )


def cmd_reindex(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    path = save_index(root)
    count = len(json.loads(read_text(path)))
    print(f"Indexed {count} skills: {path}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if args.mode == "lexical":
        hits = lexical_search(root, args.query, args.limit, args.collection, args.fresh)
    elif args.mode == "vector":
        hits = vector_search(root, args.query, args.limit, args.model, args.collection)
    else:
        hits = hybrid_search(root, args.query, args.limit, args.model, args.collection, args.fresh, args.require_vector)
    log_event(root, "search", {"query": args.query, "mode": args.mode, "hits": [asdict(hit) for hit in hits[:5]]})
    return emit_hits(hits, args.json)


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    hits = list_skills(root, collection=args.collection, filter_text=args.filter, fresh=args.fresh)
    shown = hits[: args.limit] if args.limit > 0 else hits
    payload = {
        "root": str(root),
        "total": len(hits),
        "shown": len(shown),
        "collections": collection_counts(hits),
        "skills": [asdict(hit) for hit in shown],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"Total skills: {payload['total']}")
    if payload["collections"]:
        print("Collections: " + ", ".join(f"{name}={count}" for name, count in payload["collections"].items()))
    if len(shown) < len(hits):
        print(f"Showing first {len(shown)} skills. Use --limit 0 to show all.")
    for hit in shown:
        if args.names_only:
            print(hit.name)
            continue
        print(f"{hit.name} [{hit.collection}]")
        if hit.description:
            print(f"  {hit.description}")
        if args.paths:
            print(f"  {hit.path}")
    log_event(root, "list", {"collection": args.collection or "", "filter": args.filter, "shown": len(shown), "total": len(hits)})
    return 0


def cmd_vector_reindex(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    records = load_records(root, fresh=args.fresh)
    client = chroma_client(root)
    try:
        client.delete_collection(CHROMA_COLLECTION)
    except Exception:
        pass
    collection = client.get_or_create_collection(name=CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"})
    batch_size = max(1, min(args.batch_size, 128))
    total = 0
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        ids = []
        docs = []
        metas = []
        for hit, body in batch:
            ids.append(str(Path(hit.path)).lower().replace("\\", "/"))
            docs.append(vector_text(hit, body))
            metas.append({"name": hit.name, "description": hit.description, "collection": hit.collection, "path": hit.path})
        collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embed_texts(docs, args.model))
        total += len(batch)
        if args.verbose:
            print(f"Indexed {total}/{len(records)}")
    (root / VECTOR_META_NAME).write_text(
        json.dumps(
            {"collection": CHROMA_COLLECTION, "model": args.model, "count": total, "chroma_path": str(root / CHROMA_DIR_NAME)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Vector-indexed {total} skills with {args.model}: {root / CHROMA_DIR_NAME}")
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    path = find_by_name(root, args.name)
    if not path:
        print(f"Skill not found: {args.name}", file=sys.stderr)
        return 2
    print(read_text(path))
    log_event(root, "view", {"name": args.name, "path": str(path)})
    return 0


def cmd_where(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    path = find_by_name(root, args.name)
    if not path:
        print(f"Skill not found: {args.name}", file=sys.stderr)
        return 2
    print(path)
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    path = find_by_name(root, args.name)
    payload = {"name": args.name, "query": args.query, "task": args.task, "path": str(path) if path else ""}
    log_event(root, "skill_used", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    row = {
        "ts": time.time(),
        "name": args.name,
        "query": args.query,
        "verdict": args.verdict,
        "notes": args.notes,
    }
    write_jsonl(root / ".learning" / FEEDBACK_LOG, row)
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


def cmd_learning_summary(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    feedback_path = root / ".learning" / FEEDBACK_LOG
    counts: dict[str, dict[str, int]] = {}
    if feedback_path.is_file():
        for line in feedback_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = str(row.get("name") or "")
            verdict = str(row.get("verdict") or "")
            counts.setdefault(name, {"accepted": 0, "rejected": 0, "neutral": 0})
            if verdict in counts[name]:
                counts[name][verdict] += 1
    print(json.dumps(counts, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_draft_skill(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", args.name.strip().lower()).strip("-") or "new-skill"
    body = "\n".join(
        [
            "---",
            f"name: {slug}",
            f"description: {args.description}",
            "---",
            "",
            f"# {args.name}",
            "",
            "Use this skill when the task matches the description above.",
            "",
            "## Workflow",
            "",
            "1. Inspect the task context and confirm that this skill is relevant.",
            "2. Follow the project-specific conventions before introducing new patterns.",
            "3. Verify the result on the real artifact or route when practical.",
            "",
            "## Evidence",
            "",
            args.evidence or "No evidence notes were provided.",
            "",
        ]
    )
    if args.write:
        target = root / "generated" / "skills" / slug / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        print(target)
    else:
        print(body)
    return 0


def cmd_adapt(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    results = adapt_library(
        root,
        collection=args.collection,
        source_pack=args.source_pack,
        source_repo=args.source_repo,
        force=args.force,
        dry_run=args.dry_run,
    )
    changed = [item for item in results if item.changed]
    payload = {
        "root": str(root),
        "collection": args.collection,
        "dry_run": args.dry_run,
        "count": len(results),
        "changed": len(changed),
        "items": [asdict(item) for item in changed[: args.limit]],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_packs(args: argparse.Namespace) -> int:
    print(json.dumps(SKILL_PACKS, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_install_pack(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    results = install_pack(root, args.pack, ref=args.ref, keep_clone=Path(args.keep_clone).expanduser() if args.keep_clone else None)
    save_index(root)
    payload = {
        "root": str(root),
        "pack": args.pack,
        "count": len(results),
        "items": [asdict(item) for item in results[: args.limit]],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def resolve_skill_path(root: Path, name_or_path: str) -> Path | None:
    candidate = Path(name_or_path).expanduser()
    if candidate.is_file():
        return candidate
    if candidate.is_dir() and (candidate / "SKILL.md").is_file():
        return candidate / "SKILL.md"
    return find_by_name(root, name_or_path)


def cmd_adapt_one(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    path = resolve_skill_path(root, args.name_or_path)
    if not path:
        print(f"Skill not found: {args.name_or_path}", file=sys.stderr)
        return 2
    print(json.dumps(adaptation_task(path, root=root, source_pack=args.source_pack, source_repo=args.source_repo), ensure_ascii=False, indent=2))
    return 0


def cmd_adapt_next(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    path = next_skill_for_agent(root, collection=args.collection)
    if not path:
        print(json.dumps({"status": "done", "message": "No unprocessed skills found."}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(adaptation_task(path, root=root, source_pack=args.source_pack, source_repo=args.source_repo), ensure_ascii=False, indent=2))
    return 0


def cmd_apply_adaptation(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    data = json.loads(read_text(Path(args.input).expanduser()))
    path_value = args.path or data.get("source_path") or data.get("path")
    if not path_value:
        print("Adaptation JSON must include source_path, or pass --path.", file=sys.stderr)
        return 2
    path = resolve_skill_path(root, str(path_value))
    if not path:
        print(f"Skill not found: {path_value}", file=sys.stderr)
        return 2
    result = apply_agent_adaptation(
        path,
        root=root,
        data=data,
        source_pack=args.source_pack,
        source_repo=args.source_repo,
        dry_run=args.dry_run,
    )
    if not args.dry_run:
        save_index(root)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install server dependencies with: pip install 'unlimited-skills[server]'") from exc
    os.environ["UNLIMITED_SKILLS_ROOT"] = str(Path(args.root).expanduser())
    os.environ["UNLIMITED_SKILLS_EMBED_MODEL"] = args.model
    uvicorn.run("unlimited_skills.server:app", host=args.host, port=args.port, log_level=args.log_level)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search, load, and learn from large local skill libraries.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Skill library root.")
    sub = parser.add_subparsers(dest="command", required=True)

    reindex = sub.add_parser("reindex", help="Rebuild the lexical JSON index.")
    reindex.set_defaults(func=cmd_reindex)

    vector_reindex = sub.add_parser("vector-reindex", help="Rebuild the Chroma vector index.")
    vector_reindex.add_argument("--model", default=DEFAULT_EMBED_MODEL)
    vector_reindex.add_argument("--batch-size", type=int, default=32)
    vector_reindex.add_argument("--fresh", action="store_true")
    vector_reindex.add_argument("--verbose", action="store_true")
    vector_reindex.set_defaults(func=cmd_vector_reindex)

    search = sub.add_parser("search", help="Search skills.")
    search.add_argument("query")
    search.add_argument("--mode", choices=["hybrid", "lexical", "vector"], default="hybrid")
    search.add_argument("--model", default=DEFAULT_EMBED_MODEL)
    search.add_argument("--collection")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--json", action="store_true")
    search.add_argument("--fresh", action="store_true")
    search.add_argument("--require-vector", action="store_true")
    search.set_defaults(func=cmd_search)

    list_parser = sub.add_parser("list", help="List available skills in the library.")
    list_parser.add_argument("--collection", help="Only list one collection.")
    list_parser.add_argument("--filter", default="", help="Filter by name, description, or body text.")
    list_parser.add_argument("--limit", type=int, default=80, help="Maximum skills to print. Use 0 for all.")
    list_parser.add_argument("--names-only", action="store_true", help="Print only skill names.")
    list_parser.add_argument("--paths", action="store_true", help="Include SKILL.md paths in text output.")
    list_parser.add_argument("--json", action="store_true")
    list_parser.add_argument("--fresh", action="store_true")
    list_parser.set_defaults(func=cmd_list)

    view = sub.add_parser("view", help="Print full SKILL.md for a skill.")
    view.add_argument("name")
    view.set_defaults(func=cmd_view)

    where = sub.add_parser("where", help="Print a SKILL.md path.")
    where.add_argument("name")
    where.set_defaults(func=cmd_where)

    use = sub.add_parser("use", help="Record that the agent used a skill.")
    use.add_argument("name")
    use.add_argument("--query", default="")
    use.add_argument("--task", default="")
    use.set_defaults(func=cmd_use)

    feedback = sub.add_parser("feedback", help="Record accepted/rejected feedback for a skill match.")
    feedback.add_argument("name")
    feedback.add_argument("--query", default="")
    feedback.add_argument("--verdict", choices=["accepted", "rejected", "neutral"], required=True)
    feedback.add_argument("--notes", default="")
    feedback.set_defaults(func=cmd_feedback)

    summary = sub.add_parser("learning-summary", help="Summarize learning-loop feedback.")
    summary.set_defaults(func=cmd_learning_summary)

    draft = sub.add_parser("draft-skill", help="Draft a new SKILL.md from task evidence.")
    draft.add_argument("name")
    draft.add_argument("--description", required=True)
    draft.add_argument("--evidence", default="")
    draft.add_argument("--write", action="store_true")
    draft.set_defaults(func=cmd_draft_skill)

    adapt = sub.add_parser("adapt", help="Adapt existing SKILL.md files for Unlimited Skills retrieval and learning.")
    adapt.add_argument("--collection", help="Only adapt one collection under the library root.")
    adapt.add_argument("--source-pack", default="", help="Set or override the source_pack metadata.")
    adapt.add_argument("--source-repo", default="", help="Set or override the source_repo metadata.")
    adapt.add_argument("--force", action="store_true", help="Rewrite skills even when already adapted.")
    adapt.add_argument("--dry-run", action="store_true", help="Print what would change without writing files.")
    adapt.add_argument("--limit", type=int, default=20, help="Maximum changed items to include in JSON output.")
    adapt.set_defaults(func=cmd_adapt)

    packs = sub.add_parser("packs", help="List known upstream skill packs.")
    packs.set_defaults(func=cmd_packs)

    install_pack_parser = sub.add_parser("install-pack", help="Clone, import, and adapt a known upstream skill pack.")
    install_pack_parser.add_argument("pack", choices=sorted(SKILL_PACKS))
    install_pack_parser.add_argument("--ref", default="", help="Optional git ref to import.")
    install_pack_parser.add_argument("--keep-clone", default="", help="Optional path where the upstream clone should be kept.")
    install_pack_parser.add_argument("--limit", type=int, default=20, help="Maximum imported items to include in JSON output.")
    install_pack_parser.set_defaults(func=cmd_install_pack)

    adapt_one = sub.add_parser("adapt-one", help="Print an agent adaptation task for one skill.")
    adapt_one.add_argument("name_or_path", help="Skill name, SKILL.md path, or skill directory path.")
    adapt_one.add_argument("--source-pack", default="", help="Source pack metadata override.")
    adapt_one.add_argument("--source-repo", default="", help="Source repository metadata override.")
    adapt_one.set_defaults(func=cmd_adapt_one)

    adapt_next = sub.add_parser("adapt-next", help="Print an agent adaptation task for the next unprocessed skill.")
    adapt_next.add_argument("--collection", help="Only process one collection.")
    adapt_next.add_argument("--source-pack", default="", help="Source pack metadata override.")
    adapt_next.add_argument("--source-repo", default="", help="Source repository metadata override.")
    adapt_next.set_defaults(func=cmd_adapt_next)

    apply_adaptation = sub.add_parser("apply-adaptation", help="Apply one agent-produced action-memory JSON adaptation.")
    apply_adaptation.add_argument("input", help="JSON file produced by the current agent for one source skill.")
    apply_adaptation.add_argument("--path", default="", help="Override source skill path/name.")
    apply_adaptation.add_argument("--source-pack", default="", help="Source pack metadata override.")
    apply_adaptation.add_argument("--source-repo", default="", help="Source repository metadata override.")
    apply_adaptation.add_argument("--dry-run", action="store_true", help="Validate and print result without writing.")
    apply_adaptation.set_defaults(func=cmd_apply_adaptation)

    serve = sub.add_parser("serve", help="Run the experimental warm search daemon.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--model", default=DEFAULT_EMBED_MODEL)
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
