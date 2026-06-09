from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import warnings
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .adapters import SKILL_PACKS, adapt_library, apply_agent_adaptation, adaptation_task, install_pack, next_skill_for_agent
from .community import (
    CommunityClient,
    build_submission_draft,
    confirm_upload_or_fail,
    list_installed_community_items,
    remove_community_item,
)
from .doctor import build_doctor_report, doctor_json, format_doctor_text
from .hub import (
    HUB_DEFAULT_PORT,
    cmd_hub_clients,
    cmd_hub_doctor,
    cmd_hub_init,
    cmd_hub_serve,
    cmd_hub_status,
    cmd_hub_sync,
    cmd_hub_token_create,
    cmd_hub_token_list,
    cmd_hub_token_revoke,
    cmd_remote_configure,
    cmd_remote_capabilities,
    cmd_remote_install_plan,
    cmd_remote_resolve,
    cmd_remote_search,
    cmd_remote_status,
    cmd_remote_view,
    cmd_trust_import,
    cmd_trust_keys,
    cmd_trust_revoke,
    cmd_trust_status,
    cmd_trust_verify,
    redacted_runtime_error,
)
from .registration import (
    DEFAULT_SERVICE_URL,
    load_registration,
    registration_path,
    redacted_status,
    register_installation,
    save_registration,
    set_telemetry,
)
from .native import DEFAULT_AGENT_ORDER, sync_native_sources
from .self_update import DEFAULT_PUBLIC_REPO, apply_public_repo_update, check_public_repo_update
from .team import (
    TeamClient,
    TeamError,
    collection_to_json,
    load_team_state,
    member_to_json,
    parse_duration_hours,
    redacted_team_status,
    save_team_state,
    team_state_path,
    team_state_with_mode,
    write_team_audit,
)
from .updates import UpdateClient


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_ROOT = Path(os.environ.get("UNLIMITED_SKILLS_ROOT", Path.home() / ".unlimited-skills" / "library"))
INDEX_NAME = ".unlimited-skills-index.json"
VECTOR_META_NAME = ".unlimited-skills-vector.json"
VECTOR_SIDECAR_NAME = ".unlimited-skills-vectors.json"
CHROMA_DIR_NAME = ".chroma-skills"
CHROMA_COLLECTION = "unlimited_skills_v1"
EVENT_LOG = "events.jsonl"
FEEDBACK_LOG = "feedback.jsonl"
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
    result: set[str] = set()
    for match in WORD_RE.finditer(text or ""):
        raw = match.group(0).lower().strip("-_/")
        if len(raw) > 1:
            result.add(raw)
        for part in re.split(r"[-_/]+", raw):
            if len(part) > 1:
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


def ensure_embedding_deps():
    try:
        from fastembed import TextEmbedding  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install vector dependencies with: pip install 'unlimited-skills[vector]'") from exc
    return TextEmbedding


def ensure_chroma_deps():
    try:
        import chromadb  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install vector dependencies with: pip install 'unlimited-skills[vector]'") from exc
    return chromadb


def chroma_client(root: Path):
    chromadb = ensure_chroma_deps()
    return chromadb.PersistentClient(path=str(root / CHROMA_DIR_NAME))


def embed_texts(texts: list[str], model_name: str) -> list[list[float]]:
    model = embedding_model(model_name)
    return [vec.tolist() if hasattr(vec, "tolist") else list(vec) for vec in model.embed(texts)]


@lru_cache(maxsize=4)
def embedding_model(model_name: str):
    TextEmbedding = ensure_embedding_deps()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*now uses mean pooling.*")
        return TextEmbedding(model_name=model_name)


def vector_sidecar_path(root: Path) -> Path:
    return root / VECTOR_SIDECAR_NAME


def vector_meta_path(root: Path) -> Path:
    return root / VECTOR_META_NAME


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for l_value, r_value in zip(left, right):
        dot += l_value * r_value
        left_norm += l_value * l_value
        right_norm += r_value * r_value
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


def load_vector_sidecar(root: Path, model: str) -> list[dict] | None:
    path = vector_sidecar_path(root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Vector sidecar is invalid JSON: {path}") from exc
    if str(payload.get("model") or "") != model:
        return None
    records = payload.get("records")
    if not isinstance(records, list):
        raise RuntimeError(f"Vector sidecar has no records list: {path}")
    return records


def vector_search_sidecar(root: Path, query: str, limit: int, model: str, collection_name: str | None = None) -> list[SkillHit] | None:
    records = load_vector_sidecar(root, model)
    if records is None:
        return None
    query_embedding = embed_texts([query], model)[0]
    scored: list[SkillHit] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        collection = str(record.get("collection") or "")
        if collection_name and collection != collection_name:
            continue
        embedding = record.get("embedding")
        if not isinstance(embedding, list):
            continue
        score = cosine_similarity(query_embedding, [float(value) for value in embedding])
        if score <= 0.0:
            continue
        scored.append(
            SkillHit(
                name=str(record.get("name") or ""),
                description=str(record.get("description") or ""),
                collection=collection,
                path=str(record.get("path") or ""),
                score=score,
            )
        )
    scored.sort(key=lambda item: (-item.score, item.collection, item.name))
    return scored[:limit]


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
    sidecar_hits = vector_search_sidecar(root, query, limit, model, collection_name=collection_name)
    if sidecar_hits is not None:
        return sidecar_hits
    try:
        collection = chroma_client(root).get_collection(CHROMA_COLLECTION)
    except Exception as exc:
        raise RuntimeError(
            "Vector index is not ready. Run `unlimited-skills vector-reindex` to build the fast local vector sidecar."
        ) from exc
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


def _native_sync_disabled(args: argparse.Namespace) -> bool:
    env_value = os.environ.get("UNLIMITED_SKILLS_DISABLE_NATIVE_SYNC", "").strip().lower()
    return bool(getattr(args, "no_native_sync", False) or env_value in {"1", "true", "yes", "on"})


def maybe_sync_native(args: argparse.Namespace, root: Path) -> list[dict]:
    if _native_sync_disabled(args):
        return []
    agents = getattr(args, "native_agent", None) or None
    results = sync_native_sources(root, agents=agents, apply=True, refresh_collection=True)
    if any(item.imported_count for item in results):
        save_index(root)
    return [asdict(item) for item in results]


def cmd_reindex(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    native_sync = maybe_sync_native(args, root)
    path = save_index(root)
    count = len(json.loads(read_text(path)))
    if args.json:
        print(json.dumps({"root": str(root), "indexed": count, "index": str(path), "native_sync": native_sync}, ensure_ascii=False, indent=2))
    else:
        print(f"Indexed {count} skills: {path}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    maybe_sync_native(args, root)
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
    maybe_sync_native(args, root)
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
    maybe_sync_native(args, root)
    records = load_records(root, fresh=args.fresh)
    client = chroma_client(root)
    try:
        client.delete_collection(CHROMA_COLLECTION)
    except Exception:
        pass
    collection = client.get_or_create_collection(name=CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"})
    batch_size = max(1, min(args.batch_size, 128))
    total = 0
    sidecar_records: list[dict] = []
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        ids = []
        docs = []
        metas = []
        for hit, body in batch:
            ids.append(str(Path(hit.path)).lower().replace("\\", "/"))
            docs.append(vector_text(hit, body))
            metas.append({"name": hit.name, "description": hit.description, "collection": hit.collection, "path": hit.path})
        embeddings = embed_texts(docs, args.model)
        collection.add(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
        for meta, embedding in zip(metas, embeddings):
            sidecar_records.append({**meta, "embedding": [round(float(value), 8) for value in embedding]})
        total += len(batch)
        if args.verbose:
            print(f"Indexed {total}/{len(records)}")
    vector_sidecar_path(root).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "collection": CHROMA_COLLECTION,
                "model": args.model,
                "count": total,
                "generated_at": time.time(),
                "records": sidecar_records,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    vector_meta_path(root).write_text(
        json.dumps(
            {
                "collection": CHROMA_COLLECTION,
                "model": args.model,
                "count": total,
                "chroma_path": str(root / CHROMA_DIR_NAME),
                "sidecar_path": str(vector_sidecar_path(root)),
                "query_fast_path": "sidecar",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Vector-indexed {total} skills with {args.model}: {vector_sidecar_path(root)}")
    print(f"Chroma compatibility index: {root / CHROMA_DIR_NAME}")
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    maybe_sync_native(args, root)
    path = find_by_name(root, args.name)
    if not path:
        print(f"Skill not found: {args.name}", file=sys.stderr)
        return 2
    print(read_text(path))
    log_event(root, "view", {"name": args.name, "path": str(path)})
    return 0


def cmd_where(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    maybe_sync_native(args, root)
    path = find_by_name(root, args.name)
    if not path:
        print(f"Skill not found: {args.name}", file=sys.stderr)
        return 2
    print(path)
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    maybe_sync_native(args, root)
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


def cmd_sync_native(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    agents = args.agent or list(DEFAULT_AGENT_ORDER)
    results = sync_native_sources(root, agents=agents, apply=not args.dry_run, refresh_collection=not args.no_refresh)
    reindexed = False
    if not args.dry_run and not args.skip_reindex:
        save_index(root)
        reindexed = True
    payload = {
        "root": str(root),
        "dry_run": args.dry_run,
        "agents": agents,
        "reindexed": reindexed,
        "results": [asdict(item) for item in results],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    for item in results:
        status = "skipped" if item.skipped else f"{item.imported_count} skills"
        suffix = f" ({item.reason})" if item.reason else ""
        print(f"{item.collection}: {status}{suffix}")
        print(f"  source: {item.source_root}")
    if reindexed:
        print("Lexical index rebuilt.")
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


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    report = build_doctor_report(root, agent=args.agent)
    print(doctor_json(report) if args.json else format_doctor_text(report))
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    state = load_registration()
    skill_count = sum(1 for _ in iter_skills(root))
    state = register_installation(
        state,
        server_url=args.server_url,
        agent=args.agent,
        skill_count=skill_count,
        telemetry="on" if args.telemetry else "off",
        timeout=args.timeout,
    )
    path = save_registration(state)
    payload = redacted_status(state)
    payload["registration_file"] = str(path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_license_status(args: argparse.Namespace) -> int:
    state = load_registration()
    payload = redacted_status(state)
    payload["registration_file"] = str(registration_path())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print("Registered: " + ("yes" if payload["registered"] else "no"))
    print(f"Plan: {payload['plan']}")
    print(f"Install ID: {payload['install_id'] or '(not created)'}")
    print(f"Server: {payload['server_url']}")
    print(f"Telemetry: {payload['telemetry']}")
    print("Hosted token: " + ("present" if payload["license_token"] else "missing"))
    print(f"Device key: {payload['key_thumbprint'] or '(not created)'}")
    print("Proof required: " + ("yes" if payload["proof_required"] else "no"))
    return 0


def cmd_telemetry(args: argparse.Namespace) -> int:
    state = load_registration()
    if args.telemetry_command in {"on", "off"}:
        state = set_telemetry(state, args.telemetry_command)
        save_registration(state)
    payload = redacted_status(state)
    print(json.dumps({"telemetry": payload["telemetry"], "registered": payload["registered"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_updates_check(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout)
    updates = client.check(root)
    if args.collection:
        updates = [item for item in updates if item.collection == args.collection]
    payload = {"root": str(root), "count": len(updates), "updates": [item.__dict__ for item in updates]}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif updates:
        for item in updates:
            print(f"{item.collection}: {item.version} ({item.notes or 'update available'})")
    else:
        print("No hosted collection updates available.")
    return 0


def cmd_updates_apply(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout)
    updates = client.check(root)
    if args.collection:
        updates = [item for item in updates if item.collection == args.collection]
    if args.dry_run:
        print(json.dumps({"root": str(root), "dry_run": True, "count": len(updates), "updates": [item.__dict__ for item in updates]}, ensure_ascii=False, indent=2))
        return 0
    applied = [client.apply(root, item) for item in updates]
    if applied and not args.skip_reindex:
        save_index(root)
    print(json.dumps({"root": str(root), "applied": applied, "reindexed": bool(applied and not args.skip_reindex)}, ensure_ascii=False, indent=2))
    return 0


def cmd_catalog_list(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout)
    payload = client.catalog(root)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split(",") if item.strip())


def _emit_community_items(items, *, as_json: bool) -> int:
    payload = {"count": len(items), "items": [asdict(item) for item in items]}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not items:
        print("No community skills found.")
        return 0
    for item in items:
        label = item.display_name or item.name
        version = f" {item.version}" if item.version else ""
        print(f"{item.item_id}: {label}{version} [{item.kind}]")
        if item.description:
            print(f"  {item.description}")
        if item.publisher:
            print(f"  publisher: {item.publisher}")
    return 0


def cmd_community_list(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = CommunityClient(load_registration(), timeout=args.timeout)
    items = client.list_community_items(root, limit=args.limit, compatible_agent=args.compatible_agent, tags=_split_csv(args.tags))
    return _emit_community_items(items, as_json=args.json)


def cmd_community_search(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = CommunityClient(load_registration(), timeout=args.timeout)
    items = client.search_community_items(
        root,
        query=args.query,
        tags=_split_csv(args.tags),
        compatible_agent=args.compatible_agent,
        limit=args.limit,
    )
    return _emit_community_items(items, as_json=args.json)


def cmd_community_preview(args: argparse.Namespace) -> int:
    client = CommunityClient(load_registration(), timeout=args.timeout)
    preview = client.preview_community_item(args.catalog_item_id)
    payload = asdict(preview)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    item = preview.item
    print(f"{item.item_id}: {item.display_name or item.name} [{item.kind}]")
    if preview.description or item.description:
        print(preview.description or item.description)
    if preview.included_skill_names:
        print("Skills: " + ", ".join(preview.included_skill_names))
    if preview.warnings:
        print("Warnings: " + "; ".join(preview.warnings))
    return 0


def cmd_community_install(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = CommunityClient(load_registration(), timeout=args.timeout)
    if not args.dry_run and not args.yes:
        if not sys.stdin.isatty():
            raise RuntimeError("Community install requires --yes in non-interactive mode.")
        typed = input("Type INSTALL to install this community item: ")
        if typed.strip() != "INSTALL":
            raise RuntimeError("Community install cancelled.")
    result = client.install_community_item(
        root,
        item_id=args.catalog_item_id,
        target_collection=args.collection,
        dry_run=args.dry_run,
        force=args.force,
    )
    reindexed = False
    if not args.dry_run and not args.skip_reindex:
        save_index(root)
        reindexed = True
    payload = {"result": asdict(result), "reindexed": reindexed}
    if args.json or args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Installed {payload['result']['collection']} {payload['result']['version']}")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0


def cmd_community_submit(args: argparse.Namespace) -> int:
    draft = build_submission_draft(
        Path(args.path),
        name=args.name,
        description=args.description,
        tags=_split_csv(args.tags),
        compatible_agents=tuple(args.compatible_agent or ()),
        visibility=args.visibility,
    )
    payload = {
        "preview_path": draft.preview_path,
        "name": draft.name,
        "description": draft.description,
        "skills": list(draft.skills),
        "files": [{key: value for key, value in row.items() if key != "content_base64"} for row in draft.files],
        "total_bytes": draft.total_bytes,
        "warnings": list(draft.warnings),
        "note": "Community submission uploads the selected skill/pack content for maintainer review.",
    }
    if args.dry_run:
        payload["result"] = asdict(CommunityClient(load_registration(), timeout=args.timeout).submit_community_skill(draft, dry_run=True))
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    client = CommunityClient(load_registration(), timeout=args.timeout)
    confirm = confirm_upload_or_fail(args.yes)
    result = client.submit_community_skill(draft, confirm=confirm)
    payload["result"] = asdict(result)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_community_submission_status(args: argparse.Namespace) -> int:
    client = CommunityClient(load_registration(), timeout=args.timeout)
    payload = client.get_submission_status(args.submission_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_community_installed(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    installed = list_installed_community_items(root)
    payload = {"root": str(root), "count": len(installed), "items": [asdict(item) for item in installed]}
    if args.refresh:
        client = CommunityClient(load_registration(), timeout=args.timeout)
        payload["refresh"] = {"available_count": len(client.list_community_items(root, limit=1))}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not installed:
        print("No installed community skills found.")
        return 0
    for item in installed:
        print(f"{item.collection}: {item.name} {item.version} [{item.source}]")
    return 0


def cmd_community_remove(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    result = remove_community_item(root, args.collection_or_skill_name, dry_run=args.dry_run or not args.yes, force=args.force)
    reindexed = False
    if result.get("removed") and not args.skip_reindex:
        save_index(root)
        reindexed = True
    payload = {"result": result, "reindexed": reindexed}
    if args.json or result.get("dry_run"):
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Removed {result['collection']}")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0


def cmd_enhance_download(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout)
    target_dir = Path(args.target_dir).expanduser() if args.target_dir else None
    path = client.download_enhancement_script(root, target_dir=target_dir)
    payload = {"root": str(root), "script": str(path)}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(path)
    return 0


def cmd_enhance_run(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout)
    target_dir = Path(args.target_dir).expanduser() if args.target_dir else None
    return client.run_enhancement_script(root, apply=args.apply, limit=args.limit, target_dir=target_dir)


def _confirm_or_fail(flag: bool, phrase: str, message: str) -> None:
    if flag:
        return
    if not sys.stdin.isatty():
        raise RuntimeError(f"{message} Pass --yes to confirm in non-interactive mode.")
    typed = input(f"Type {phrase} to continue: ")
    if typed.strip() != phrase:
        raise RuntimeError("Operation cancelled.")


def _reason_or_prompt(reason: str) -> str:
    if reason:
        return reason
    if not sys.stdin.isatty():
        raise RuntimeError("This command requires --reason in non-interactive mode.")
    typed = input("Reason: ").strip()
    if not typed:
        raise RuntimeError("Reason is required.")
    return typed


def cmd_team_status(args: argparse.Namespace) -> int:
    team = load_team_state()
    registration = load_registration()
    payload = redacted_team_status(team, registration)
    if getattr(args, "refresh", False):
        client = TeamClient(registration, timeout=args.timeout)
        refreshed = client.status(team)
        payload["refresh"] = refreshed
        payload["member_count"] = int(refreshed.get("member_count") or payload["member_count"])
        payload["pending_count"] = int(refreshed.get("pending_count") or payload["pending_count"])
        if isinstance(refreshed.get("limits"), dict):
            payload["limits"] = refreshed["limits"]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print("Registered: " + ("yes" if payload["registered"] else "no"))
    print(f"Team: {payload['team_name'] or '(none)'} ({payload['team_id'] or 'no team id'})")
    print(f"Role: {payload['role']} / status: {payload['status'] or 'none'}")
    print(f"Approval mode: {payload['approval_mode']}")
    if payload["auto_approval_expires_at"]:
        print(f"Auto approval expires: {payload['auto_approval_expires_at']}")
    print(f"Last sync: {payload['last_sync_at'] or '(never)'}")
    if payload["recommendations"]:
        print("Recommendations: " + " ".join(payload["recommendations"]))
    return 0


def cmd_team_create(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    name = args.name_option or args.name
    if not name:
        raise RuntimeError("Team name is required.")
    registration = load_registration()
    client = TeamClient(registration, timeout=args.timeout)
    team, response = client.create(root, name=name)
    path = save_team_state(team)
    payload = redacted_team_status(team, registration)
    payload["team_file"] = str(path)
    if "join_code" in response:
        payload["join_code"] = response["join_code"]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_team_join(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    registration = load_registration()
    client = TeamClient(registration, timeout=args.timeout)
    team, _ = client.join(root, join_code=args.join_code, display_name=args.display_name, agent_surfaces=tuple(args.agent_surface or ()))
    path = save_team_state(team)
    payload = redacted_team_status(team, registration)
    payload["team_file"] = str(path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_team_sync(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    registration = load_registration()
    team = load_team_state()
    team_client = TeamClient(registration, timeout=args.timeout)
    plan = team_client.sync_manifest(root, team)
    updates = plan.updates
    if args.collection:
        updates = [item for item in updates if item.collection == args.collection]
    if args.dry_run:
        payload = plan.dry_run_payload(root)
        if args.collection:
            payload["collections"] = [item for item in payload["collections"] if item["collection"] == args.collection]
        write_team_audit("team_sync_dry_run", team=team, registration=registration, request_id=plan.request_id)
        print(json.dumps({"root": str(root), "dry_run": True, "plan": payload}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    _confirm_or_fail(args.yes, "SYNC", "Team sync may change local team-owned skill collections.")
    update_client = UpdateClient(registration, timeout=args.timeout)
    applied = [update_client.apply(root, item) for item in updates]
    reindexed = False
    if not args.skip_reindex:
        save_index(root)
        reindexed = True
    team = team_client.mark_synced(team)
    save_team_state(team)
    write_team_audit("team_sync_applied", team=team, registration=registration, result=f"{len(applied)} applied", request_id=plan.request_id)
    print(json.dumps({"root": str(root), "applied": applied, "reindexed": reindexed, "team": redacted_team_status(team, registration)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_members(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    members = client.members(team, include_all=args.all, pending_only=args.pending)
    payload = {"count": len(members), "members": [member_to_json(member, full_id=args.full_id) for member in members]}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    for member in payload["members"]:
        print(f"{member['install_id']}: {member['display_name'] or '(unnamed)'} [{member['role']}/{member['status']}]")
    return 0


def cmd_team_pending(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    payload = client.pending(team)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    items = payload.get("items") or payload.get("members") or []
    for item in items if isinstance(items, list) else []:
        install_id = str(item.get("install_id") or "")
        short = install_id if args.full_id or len(install_id) <= 16 else f"{install_id[:12]}..."
        print(f"{short}: {item.get('display_name') or '(unnamed)'} {item.get('client_version') or ''}")
    return 0


def cmd_team_approve(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    print(json.dumps(client.approve(team, member_install_id=args.install_id), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_reject(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    reason = _reason_or_prompt(args.reason)
    print(json.dumps(client.reject(team, member_install_id=args.install_id, reason=reason), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_revoke(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    _confirm_or_fail(args.yes, "REVOKE", "Team revoke removes hosted team access for that instance.")
    print(json.dumps(client.revoke(team, member_install_id=args.install_id, reason=args.reason), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_mode(args: argparse.Namespace) -> int:
    team = load_team_state()
    registration = load_registration()
    client = TeamClient(registration, timeout=args.timeout)
    duration = f"{args.hours}h" if getattr(args, "hours", 0) else args.duration
    hours = parse_duration_hours(duration, plan=(registration.plan or "team-free")) if args.mode == "auto" else 0
    response = client.set_mode(team, mode=args.mode, hours=hours)
    save_team_state(team_state_with_mode(team, response, mode=args.mode, hours=hours))
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_collections(args: argparse.Namespace) -> int:
    team = load_team_state()
    client = TeamClient(load_registration(), timeout=args.timeout)
    collections = client.collections(team)
    payload = {"count": len(collections), "collections": [collection_to_json(item) for item in collections]}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_team_leave(args: argparse.Namespace) -> int:
    team = load_team_state()
    registration = load_registration()
    client = TeamClient(registration, timeout=args.timeout)
    _confirm_or_fail(args.yes, "LEAVE", "Leaving the team stops hosted team sync for this installation.")
    response = client.leave(team)
    left = client.left_state(team)
    save_team_state(left)
    print(json.dumps({"result": response, "team": redacted_team_status(left, registration)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_self_update_check(args: argparse.Namespace) -> int:
    status = check_public_repo_update(repo=args.repo, install_root=Path(args.install_root).expanduser() if args.install_root else None, timeout=args.timeout)
    payload = status.to_json()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"Install root: {status.install_root}")
    print(f"Public repo: {status.repo}")
    print(f"Current version: {status.current_version}")
    print(f"Latest release: {status.latest_tag} ({status.latest_version})")
    print(f"Git checkout: {'yes' if status.is_git_checkout else 'no'}")
    if status.is_git_checkout:
        print(f"Current ref: {status.current_ref or '(unknown)'}")
        print(f"Dirty: {'yes' if status.dirty else 'no'}")
    print(f"Update available: {'yes' if status.update_available else 'no'}")
    if status.release_url:
        print(f"Release: {status.release_url}")
    return 0


def cmd_self_update_apply(args: argparse.Namespace) -> int:
    status = check_public_repo_update(repo=args.repo, install_root=Path(args.install_root).expanduser() if args.install_root else None, timeout=args.timeout)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "status": status.to_json()}, ensure_ascii=False, indent=2))
        return 0
    result = apply_public_repo_update(status, allow_dirty=args.allow_dirty, method=args.method, timeout=args.timeout)
    router_refreshed = refresh_codex_router_skill(Path(result.install_root).expanduser()) if result.reindex_recommended and not args.skip_router_refresh else ""
    reindexed = False
    if result.reindex_recommended and not args.skip_reindex:
        save_index(Path(args.root).expanduser())
        reindexed = True
    print(json.dumps({"result": result.to_json(), "reindexed": reindexed, "router_refreshed": router_refreshed}, ensure_ascii=False, indent=2))
    return 0


def refresh_codex_router_skill(install_root: Path) -> str:
    source = install_root / "skills" / "skill-router" / "SKILL.md"
    target = Path.home() / ".codex" / "skills" / "unlimited-skills" / "SKILL.md"
    if not source.is_file() or not target.parent.is_dir():
        return ""
    target.write_text(read_text(source), encoding="utf-8")
    return str(target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search, load, and learn from large local skill libraries.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Skill library root.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_native_sync_options(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--native-agent",
            action="append",
            choices=list(DEFAULT_AGENT_ORDER),
            help="Native agent skill root to sync before this command. Repeat for multiple agents. Defaults to all known agents.",
        )
        command.add_argument("--no-native-sync", action="store_true", help="Skip automatic sync from native agent skill roots.")

    reindex = sub.add_parser("reindex", help="Rebuild the lexical JSON index.")
    add_native_sync_options(reindex)
    reindex.add_argument("--json", action="store_true")
    reindex.set_defaults(func=cmd_reindex)

    vector_reindex = sub.add_parser("vector-reindex", help="Rebuild the Chroma vector index.")
    vector_reindex.add_argument("--model", default=DEFAULT_EMBED_MODEL)
    vector_reindex.add_argument("--batch-size", type=int, default=32)
    vector_reindex.add_argument("--fresh", action="store_true")
    vector_reindex.add_argument("--verbose", action="store_true")
    add_native_sync_options(vector_reindex)
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
    add_native_sync_options(search)
    search.set_defaults(func=cmd_search)

    list_parser = sub.add_parser("list", help="List available skills in the library.")
    list_parser.add_argument("--collection", help="Only list one collection.")
    list_parser.add_argument("--filter", default="", help="Filter by name, description, or body text.")
    list_parser.add_argument("--limit", type=int, default=80, help="Maximum skills to print. Use 0 for all.")
    list_parser.add_argument("--names-only", action="store_true", help="Print only skill names.")
    list_parser.add_argument("--paths", action="store_true", help="Include SKILL.md paths in text output.")
    list_parser.add_argument("--json", action="store_true")
    list_parser.add_argument("--fresh", action="store_true")
    add_native_sync_options(list_parser)
    list_parser.set_defaults(func=cmd_list)

    view = sub.add_parser("view", help="Print full SKILL.md for a skill.")
    view.add_argument("name")
    add_native_sync_options(view)
    view.set_defaults(func=cmd_view)

    where = sub.add_parser("where", help="Print a SKILL.md path.")
    where.add_argument("name")
    add_native_sync_options(where)
    where.set_defaults(func=cmd_where)

    use = sub.add_parser("use", help="Record that the agent used a skill.")
    use.add_argument("name")
    use.add_argument("--query", default="")
    use.add_argument("--task", default="")
    add_native_sync_options(use)
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

    sync_native = sub.add_parser("sync-native", help="Mirror native agent skill roots into the Unlimited Skills library.")
    sync_native.add_argument("--agent", action="append", choices=list(DEFAULT_AGENT_ORDER), help="Agent to sync. Repeat for multiple agents. Defaults to all.")
    sync_native.add_argument("--dry-run", action="store_true", help="Report what would be imported without writing files.")
    sync_native.add_argument("--no-refresh", action="store_true", help="Keep existing mirrored skill files untouched; native sync is overlay-only by default.")
    sync_native.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after syncing.")
    sync_native.add_argument("--json", action="store_true")
    sync_native.set_defaults(func=cmd_sync_native)

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

    hub = sub.add_parser("hub", help="Registered Local Skill Hub contract and alpha commands.")
    hub_sub = hub.add_subparsers(dest="hub_command", required=True)
    hub_init = hub_sub.add_parser("init", help="Initialize local Local Skill Hub contract state.")
    hub_init.add_argument("--allowlist", default="", help="Validate and cache a local hub allowlist fixture.")
    hub_init.add_argument("--json", action="store_true")
    hub_init.set_defaults(func=cmd_hub_init)
    hub_status = hub_sub.add_parser("status", help="Show Local Skill Hub status without hosted calls.")
    hub_status.add_argument("--json", action="store_true")
    hub_status.set_defaults(func=cmd_hub_status)
    hub_serve = hub_sub.add_parser("serve", help="Run the registered Local Skill Hub alpha service.")
    hub_serve.add_argument("--host", default="127.0.0.1")
    hub_serve.add_argument("--port", type=int, default=HUB_DEFAULT_PORT)
    hub_serve.add_argument("--log-level", default="info")
    hub_serve.add_argument("--allowlist", default="", help="Path to allowlist.v1.json. Defaults to cached ~/.unlimited-skills/hub/allowlist.v1.json.")
    hub_serve.add_argument("--allow-lan", action="store_true", help="Allow binding Local Skill Hub to a non-localhost address when an active hub token exists.")
    hub_serve.set_defaults(func=cmd_hub_serve)
    hub_clients = hub_sub.add_parser("clients", help="List Local Skill Hub clients.")
    hub_clients.set_defaults(func=cmd_hub_clients)
    hub_sync = hub_sub.add_parser("sync", help="Refresh registered Local Skill Hub allowlist/catalog metadata.")
    hub_sync.add_argument("--dry-run", action="store_true")
    hub_sync.add_argument("--json", action="store_true")
    hub_sync.add_argument("--timeout", type=float, default=30.0)
    hub_sync.set_defaults(func=cmd_hub_sync)
    hub_token = hub_sub.add_parser("token", help="Manage Local Skill Hub client tokens.")
    hub_token_sub = hub_token.add_subparsers(dest="hub_token_command", required=True)
    hub_token_create = hub_token_sub.add_parser("create", help="Create a Local Skill Hub client token.")
    hub_token_create.add_argument("--label", default="default")
    hub_token_create.add_argument("--json", action="store_true")
    hub_token_create.set_defaults(func=cmd_hub_token_create)
    hub_token_list = hub_token_sub.add_parser("list", help="List Local Skill Hub client tokens without showing raw token values.")
    hub_token_list.add_argument("--json", action="store_true")
    hub_token_list.set_defaults(func=cmd_hub_token_list)
    hub_token_revoke = hub_token_sub.add_parser("revoke", help="Revoke a Local Skill Hub client token by token id.")
    hub_token_revoke.add_argument("token_id")
    hub_token_revoke.add_argument("--json", action="store_true")
    hub_token_revoke.set_defaults(func=cmd_hub_token_revoke)
    hub_doctor = hub_sub.add_parser("doctor", help="Inspect Local Skill Hub contract readiness.")
    hub_doctor.set_defaults(func=cmd_hub_doctor)

    trust = sub.add_parser("trust", help="Inspect and verify signed hosted manifest trust configuration.")
    trust_sub = trust.add_subparsers(dest="trust_command", required=True)
    trust_status = trust_sub.add_parser("status", help="Show signed manifest trust status without printing key material.")
    trust_status.add_argument("--json", action="store_true")
    trust_status.set_defaults(func=cmd_trust_status)
    trust_keys = trust_sub.add_parser("keys", help="List trusted manifest public key ids.")
    trust_keys.add_argument("--json", action="store_true")
    trust_keys.set_defaults(func=cmd_trust_keys)
    trust_verify = trust_sub.add_parser("verify", help="Verify a signed hosted manifest JSON file.")
    trust_verify.add_argument("manifest")
    trust_verify.add_argument("--scope", default="", help="Expected manifest scope, such as hub-allowlist or catalog-updates.")
    trust_verify.add_argument("--registry-url", default="", help="Expected registry URL for key origin pinning.")
    trust_verify.add_argument("--json", action="store_true")
    trust_verify.set_defaults(func=cmd_trust_verify)
    trust_import = trust_sub.add_parser("import", help="Import a public key manifest into the local trust store.")
    trust_import.add_argument("manifest")
    trust_import.add_argument("--replace", action="store_true", help="Replace the local trust store instead of merging keys.")
    trust_import.add_argument("--json", action="store_true")
    trust_import.set_defaults(func=cmd_trust_import)
    trust_revoke = trust_sub.add_parser("revoke", help="Mark a manifest signing key id as revoked in the local trust store.")
    trust_revoke.add_argument("key_id")
    trust_revoke.add_argument("--reason", default="")
    trust_revoke.add_argument("--json", action="store_true")
    trust_revoke.set_defaults(func=cmd_trust_revoke)

    remote = sub.add_parser("remote", help="Configure or query a registered Local Skill Hub.")
    remote_sub = remote.add_subparsers(dest="remote_command", required=True)
    remote_configure = remote_sub.add_parser("configure", help="Configure a remote Local Skill Hub endpoint.")
    remote_configure.add_argument("--url", required=True, help="Local/LAN hub URL, for example http://127.0.0.1:8766.")
    remote_configure.add_argument("--token", default="", help="Client token. Stored in remote.json with private permissions; prefer --token-env.")
    remote_configure.add_argument("--token-env", default="", help="Environment variable containing the hub token, for example ULS_HUB_TOKEN.")
    remote_configure.add_argument("--fallback", dest="fallback_mode", choices=["local_allowed", "hub_required"], default="local_allowed")
    remote_configure.add_argument("--fallback-mode", choices=["local_allowed", "hub_required"], default="local_allowed")
    remote_configure.add_argument("--timeout", type=float, default=10)
    remote_configure.set_defaults(func=cmd_remote_configure)
    remote_status = remote_sub.add_parser("status", help="Show remote hub configuration.")
    remote_status.add_argument("--json", action="store_true")
    remote_status.set_defaults(func=cmd_remote_status)
    remote_capabilities = remote_sub.add_parser("capabilities", help="Print local client capabilities sent to remote resolve.")
    remote_capabilities.add_argument("--agent", default="unknown")
    remote_capabilities.add_argument("--capabilities-json", default="")
    remote_capabilities.add_argument("--json", action="store_true")
    remote_capabilities.set_defaults(func=cmd_remote_capabilities)
    remote_search = remote_sub.add_parser("search", help="Search configured remote hub.")
    remote_search.add_argument("query")
    remote_search.add_argument("--mode", choices=["hybrid", "lexical", "vector"], default="hybrid")
    remote_search.add_argument("--collection", default="")
    remote_search.add_argument("--limit", type=int, default=8)
    remote_search.add_argument("--json", action="store_true")
    remote_search.set_defaults(func=cmd_remote_search)
    remote_resolve = remote_sub.add_parser("resolve", help="Resolve task-relevant skill bodies from configured remote hub.")
    remote_resolve.add_argument("query")
    remote_resolve.add_argument("--collection", default="")
    remote_resolve.add_argument("--max-skills", type=int, default=2)
    remote_resolve.add_argument("--max-chars", type=int, default=12000)
    remote_resolve.add_argument("--agent", choices=["codex", "claude-code", "hermes", "openclaw", "vellum-ai", "unknown"], default="unknown")
    remote_resolve.add_argument("--capabilities-json", default="")
    remote_resolve.add_argument("--json", action="store_true")
    remote_resolve.set_defaults(func=cmd_remote_resolve)
    remote_view = remote_sub.add_parser("view", help="View a skill from configured remote hub.")
    remote_view.add_argument("skill_name")
    remote_view.add_argument("--json", action="store_true")
    remote_view.set_defaults(func=cmd_remote_view)
    remote_install_plan = remote_sub.add_parser("install-plan", help="Show a dry-run local install plan for a remote hub skill.")
    remote_install_plan.add_argument("skill_name")
    remote_install_plan.add_argument("--dry-run", action="store_true", default=True)
    remote_install_plan.add_argument("--json", action="store_true")
    remote_install_plan.set_defaults(func=cmd_remote_install_plan)

    doctor = sub.add_parser("doctor", help="Inspect local Unlimited Skills setup without hosted calls or registration.")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable diagnostics.")
    doctor.add_argument("--agent", choices=["codex", "claude-code", "hermes", "openclaw", "all"], default="all", help="Limit agent diagnostics.")
    doctor.set_defaults(func=cmd_doctor)

    register = sub.add_parser("register", help="Self-register this installation for hosted catalog and adapted collection updates.")
    register.add_argument("--server-url", default=DEFAULT_SERVICE_URL, help="Registration and update service URL.")
    register.add_argument("--agent", default="", help="Optional agent surface label, for example codex, claude-code, hermes, or openclaw.")
    register.add_argument("--telemetry", action="store_true", help="Opt in to minimal operational telemetry.")
    register.add_argument("--timeout", type=float, default=30.0)
    register.set_defaults(func=cmd_register)

    license_parser = sub.add_parser("license", help="Inspect registration and hosted service access.")
    license_sub = license_parser.add_subparsers(dest="license_command", required=True)
    license_status = license_sub.add_parser("status", help="Show current license and registration status.")
    license_status.add_argument("--json", action="store_true")
    license_status.set_defaults(func=cmd_license_status)

    telemetry = sub.add_parser("telemetry", help="Inspect or change minimal telemetry preference.")
    telemetry_sub = telemetry.add_subparsers(dest="telemetry_command", required=True)
    for name in ("status", "on", "off"):
        telemetry_item = telemetry_sub.add_parser(name)
        telemetry_item.set_defaults(func=cmd_telemetry)

    updates = sub.add_parser("updates", help="Check or apply hosted adapted collection updates.")
    updates_sub = updates.add_subparsers(dest="updates_command", required=True)
    updates_check = updates_sub.add_parser("check", help="Check registered hosted collection updates.")
    updates_check.add_argument("--collection", default="", help="Only check one collection.")
    updates_check.add_argument("--json", action="store_true")
    updates_check.add_argument("--timeout", type=float, default=30.0)
    updates_check.set_defaults(func=cmd_updates_check)
    updates_apply = updates_sub.add_parser("apply", help="Download, verify, and install registered hosted collection updates.")
    updates_apply.add_argument("--collection", default="", help="Only apply one collection.")
    updates_apply.add_argument("--dry-run", action="store_true", help="Show available updates without downloading archives.")
    updates_apply.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after applying updates.")
    updates_apply.add_argument("--timeout", type=float, default=30.0)
    updates_apply.set_defaults(func=cmd_updates_apply)

    catalog = sub.add_parser("catalog", help="Query the registered hosted adapted-skill catalog.")
    catalog_sub = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_list = catalog_sub.add_parser("list", help="List the hosted adapted-skill catalog for this registered installation.")
    catalog_list.add_argument("--timeout", type=float, default=30.0)
    catalog_list.set_defaults(func=cmd_catalog_list)

    community = sub.add_parser("community", help="Browse, install, submit, and manage registered community skills.")
    community_sub = community.add_subparsers(dest="community_command", required=True)
    community_list = community_sub.add_parser("list", help="List registered community catalog skills.")
    community_list.add_argument("--limit", type=int, default=50)
    community_list.add_argument("--tags", default="", help="Comma-separated tag filter.")
    community_list.add_argument("--compatible-agent", default="", choices=["", "codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    community_list.add_argument("--json", action="store_true")
    community_list.add_argument("--timeout", type=float, default=30.0)
    community_list.set_defaults(func=cmd_community_list)
    community_search = community_sub.add_parser("search", help="Search registered community skills.")
    community_search.add_argument("query")
    community_search.add_argument("--limit", type=int, default=20)
    community_search.add_argument("--tags", default="", help="Comma-separated tag filter.")
    community_search.add_argument("--compatible-agent", default="", choices=["", "codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    community_search.add_argument("--json", action="store_true")
    community_search.add_argument("--timeout", type=float, default=30.0)
    community_search.set_defaults(func=cmd_community_search)
    community_preview = community_sub.add_parser("preview", help="Preview sanitized community skill metadata and install warnings.")
    community_preview.add_argument("catalog_item_id")
    community_preview.add_argument("--json", action="store_true")
    community_preview.add_argument("--timeout", type=float, default=30.0)
    community_preview.set_defaults(func=cmd_community_preview)
    community_install = community_sub.add_parser("install", help="Install a registered community skill or pack.")
    community_install.add_argument("catalog_item_id")
    community_install.add_argument("--collection", default="", help="Override local target collection.")
    community_install.add_argument("--dry-run", action="store_true", help="Show server install plan without downloading or writing.")
    community_install.add_argument("--force", action="store_true", help="Allow overwriting the target collection when the service plan permits it.")
    community_install.add_argument("--yes", action="store_true", help="Confirm install in non-interactive mode.")
    community_install.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after install.")
    community_install.add_argument("--json", action="store_true")
    community_install.add_argument("--timeout", type=float, default=30.0)
    community_install.set_defaults(func=cmd_community_install)
    community_submit = community_sub.add_parser("submit", help="Preview and submit a selected local skill or pack for community review.")
    community_submit.add_argument("path")
    community_submit.add_argument("--name", default="")
    community_submit.add_argument("--description", default="")
    community_submit.add_argument("--tags", default="", help="Comma-separated submission tags.")
    community_submit.add_argument("--compatible-agent", action="append", choices=["codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    community_submit.add_argument("--visibility", default="registered-community", choices=["registered-community", "team-free", "pro", "enterprise"])
    community_submit.add_argument("--dry-run", action="store_true", help="Validate and write preview without uploading.")
    community_submit.add_argument("--yes", action="store_true", help="Confirm upload in non-interactive mode.")
    community_submit.add_argument("--json", action="store_true", help="Accepted for consistency; submit output is JSON.")
    community_submit.add_argument("--timeout", type=float, default=30.0)
    community_submit.set_defaults(func=cmd_community_submit)
    community_status = community_sub.add_parser("submission-status", help="Show one submission status, or recent submissions when no id is provided.")
    community_status.add_argument("submission_id", nargs="?", default="")
    community_status.add_argument("--timeout", type=float, default=30.0)
    community_status.set_defaults(func=cmd_community_submission_status)
    community_installed = community_sub.add_parser("installed", help="List locally installed community skills without hosted calls by default.")
    community_installed.add_argument("--refresh", action="store_true", help="Check hosted service for refresh metadata; requires registration.")
    community_installed.add_argument("--json", action="store_true")
    community_installed.add_argument("--timeout", type=float, default=30.0)
    community_installed.set_defaults(func=cmd_community_installed)
    community_remove = community_sub.add_parser("remove", help="Remove a locally installed community item.")
    community_remove.add_argument("collection_or_skill_name")
    community_remove.add_argument("--dry-run", action="store_true", help="Show what would be removed.")
    community_remove.add_argument("--force", action="store_true", help="Allow removal when the item is not marked as community-installed.")
    community_remove.add_argument("--yes", action="store_true", help="Actually remove without interactive confirmation.")
    community_remove.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after removal.")
    community_remove.add_argument("--json", action="store_true")
    community_remove.set_defaults(func=cmd_community_remove)

    enhance = sub.add_parser("enhance", help="Download or run the registered local skill enhancement script.")
    enhance_sub = enhance.add_subparsers(dest="enhance_command", required=True)
    enhance_download = enhance_sub.add_parser("download", help="Download the registered local enhancement script without running it.")
    enhance_download.add_argument("--target-dir", default="", help="Optional script cache directory.")
    enhance_download.add_argument("--json", action="store_true")
    enhance_download.add_argument("--timeout", type=float, default=30.0)
    enhance_download.set_defaults(func=cmd_enhance_download)
    enhance_run = enhance_sub.add_parser("run", help="Download and run the registered local enhancement script. Dry-run unless --apply is passed.")
    enhance_run.add_argument("--target-dir", default="", help="Optional script cache directory.")
    enhance_run.add_argument("--apply", action="store_true", help="Write enhanced SKILL.md files. Without this flag the enhancer is a dry run.")
    enhance_run.add_argument("--limit", type=int, default=0, help="Maximum skills to inspect. Use 0 for all.")
    enhance_run.add_argument("--timeout", type=float, default=30.0)
    enhance_run.set_defaults(func=cmd_enhance_run)

    team = sub.add_parser("team", help="Register and synchronize team skill collections.")
    team_sub = team.add_subparsers(dest="team_command", required=True)
    team_status = team_sub.add_parser("status", help="Show local team registration state.")
    team_status.add_argument("--refresh", action="store_true", help="Refresh hosted team status; requires registration.")
    team_status.add_argument("--json", action="store_true")
    team_status.add_argument("--timeout", type=float, default=30.0)
    team_status.set_defaults(func=cmd_team_status)
    team_create = team_sub.add_parser("create", help="Create a registered team and join this installation as owner.")
    team_create.add_argument("name", nargs="?", default="", help="Team name.")
    team_create.add_argument("--name", dest="name_option", default="", help="Team name.")
    team_create.add_argument("--timeout", type=float, default=30.0)
    team_create.set_defaults(func=cmd_team_create)
    team_join = team_sub.add_parser("join", help="Join an existing registered team with a join code.")
    team_join.add_argument("join_code", help="Team join code from the owner/admin.")
    team_join.add_argument("--display-name", default="", help="Display name for this instance.")
    team_join.add_argument("--agent-surface", action="append", choices=["codex", "claude-code", "hermes", "openclaw", "vellum-ai"], help="Agent surface on this instance. Repeat for multiple.")
    team_join.add_argument("--timeout", type=float, default=30.0)
    team_join.set_defaults(func=cmd_team_join)
    team_members = team_sub.add_parser("members", help="List approved team members.")
    team_members.add_argument("--all", action="store_true", help="Include all member statuses.")
    team_members.add_argument("--pending", action="store_true", help="Show pending members only.")
    team_members.add_argument("--full-id", action="store_true", help="Show full install ids.")
    team_members.add_argument("--json", action="store_true")
    team_members.add_argument("--timeout", type=float, default=30.0)
    team_members.set_defaults(func=cmd_team_members)
    team_sync = team_sub.add_parser("sync", help="Download and install skill collections assigned to this team.")
    team_sync.add_argument("--collection", default="", help="Only sync one assigned collection.")
    team_sync.add_argument("--dry-run", action="store_true", help="Show assigned updates without downloading archives.")
    team_sync.add_argument("--force", action="store_true", help="Reserved for server-side install policy compatibility.")
    team_sync.add_argument("--yes", action="store_true", help="Confirm local collection changes in non-interactive mode.")
    team_sync.add_argument("--json", action="store_true")
    team_sync.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after syncing.")
    team_sync.add_argument("--timeout", type=float, default=30.0)
    team_sync.set_defaults(func=cmd_team_sync)
    team_pending = team_sub.add_parser("pending", help="List pending join requests for the master instance.")
    team_pending.add_argument("--full-id", action="store_true", help="Show full install ids.")
    team_pending.add_argument("--json", action="store_true")
    team_pending.add_argument("--timeout", type=float, default=30.0)
    team_pending.set_defaults(func=cmd_team_pending)
    team_approve = team_sub.add_parser("approve", help="Approve a pending team instance by install_id.")
    team_approve.add_argument("install_id", help="Pending installation id to approve.")
    team_approve.add_argument("--json", action="store_true")
    team_approve.add_argument("--timeout", type=float, default=30.0)
    team_approve.set_defaults(func=cmd_team_approve)
    team_reject = team_sub.add_parser("reject", help="Reject a pending team instance by install_id.")
    team_reject.add_argument("install_id", help="Pending installation id to reject.")
    team_reject.add_argument("--reason", default="", help="Reason for rejection. Required in non-interactive mode.")
    team_reject.add_argument("--json", action="store_true")
    team_reject.add_argument("--timeout", type=float, default=30.0)
    team_reject.set_defaults(func=cmd_team_reject)
    team_revoke = team_sub.add_parser("revoke", help="Revoke hosted team access for an approved instance.")
    team_revoke.add_argument("install_id", help="Approved installation id to revoke.")
    team_revoke.add_argument("--reason", default="", help="Reason for revocation.")
    team_revoke.add_argument("--yes", action="store_true", help="Confirm revocation in non-interactive mode.")
    team_revoke.add_argument("--json", action="store_true")
    team_revoke.add_argument("--timeout", type=float, default=30.0)
    team_revoke.set_defaults(func=cmd_team_revoke)
    team_mode = team_sub.add_parser("mode", help="Set team join approval mode. Default mode is manual.")
    team_mode.add_argument("mode", choices=["manual", "auto"])
    team_mode.add_argument("--duration", default="24h", help="Auto-approval duration, for example 1h, 6h, or 24h.")
    team_mode.add_argument("--hours", type=int, default=0, help="Legacy alias for --duration in hours.")
    team_mode.add_argument("--json", action="store_true")
    team_mode.add_argument("--timeout", type=float, default=30.0)
    team_mode.set_defaults(func=cmd_team_mode)
    team_collections = team_sub.add_parser("collections", help="List team-assigned collections.")
    team_collections.add_argument("--json", action="store_true")
    team_collections.add_argument("--timeout", type=float, default=30.0)
    team_collections.set_defaults(func=cmd_team_collections)
    team_leave = team_sub.add_parser("leave", help="Leave the current team. Does not delete local skills.")
    team_leave.add_argument("--yes", action="store_true", help="Confirm leave in non-interactive mode.")
    team_leave.add_argument("--json", action="store_true")
    team_leave.add_argument("--timeout", type=float, default=30.0)
    team_leave.set_defaults(func=cmd_team_leave)

    self_update = sub.add_parser("self-update", help="Check or apply public repo releases for the local Unlimited Skills core.")
    self_update_sub = self_update.add_subparsers(dest="self_update_command", required=True)
    self_update_check = self_update_sub.add_parser("check", help="Check the latest public Unlimited Skills release.")
    self_update_check.add_argument("--repo", default=DEFAULT_PUBLIC_REPO, help="GitHub repo in owner/name form.")
    self_update_check.add_argument("--install-root", default="", help="Override the detected Unlimited Skills source checkout.")
    self_update_check.add_argument("--json", action="store_true")
    self_update_check.add_argument("--timeout", type=float, default=30.0)
    self_update_check.set_defaults(func=cmd_self_update_check)
    self_update_apply = self_update_sub.add_parser("apply", help="Update the local Unlimited Skills core to the latest public release.")
    self_update_apply.add_argument("--repo", default=DEFAULT_PUBLIC_REPO, help="GitHub repo in owner/name form.")
    self_update_apply.add_argument("--install-root", default="", help="Override the detected Unlimited Skills source checkout.")
    self_update_apply.add_argument("--method", choices=["auto", "git", "archive"], default="auto", help="Use git checkout when possible, or source archive fallback.")
    self_update_apply.add_argument("--allow-dirty", action="store_true", help="Allow updating a dirty git checkout.")
    self_update_apply.add_argument("--dry-run", action="store_true", help="Show the planned update without changing files.")
    self_update_apply.add_argument("--skip-router-refresh", action="store_true", help="Do not refresh the installed Codex router SKILL.md after updating.")
    self_update_apply.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the local skill index after updating.")
    self_update_apply.add_argument("--timeout", type=float, default=30.0)
    self_update_apply.set_defaults(func=cmd_self_update_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(redacted_runtime_error(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
