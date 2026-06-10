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

from . import __version__
from .adapters import SKILL_PACKS, adapt_library, apply_agent_adaptation, adaptation_task, import_github_repo, import_skill_dirs, install_pack, next_skill_for_agent
from .catalog_browser import CatalogBrowserClient
from .catalog_feedback import CatalogFeedbackClient, build_feedback_payload
from .catalog_quality import CatalogQualityClient, dumps_status
from .community import (
    CommunityClient,
    build_submission_draft,
    confirm_upload_or_fail,
    list_installed_community_items,
    remove_community_item,
)
from .billing_status import doctor as billing_doctor
from .billing_status import format_billing_status, redacted_billing_summary, refresh_billing_status
from .doctor import build_doctor_report, doctor_json, format_doctor_text
from .frontmatter import split_frontmatter as _shared_split_frontmatter
from .hub import (
    HUB_DEFAULT_PORT,
    cmd_hub_clients,
    cmd_hub_doctor,
    cmd_hub_heartbeat,
    cmd_hub_init,
    cmd_hub_license_refresh,
    cmd_hub_license_status,
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
from .maintainer_queue_status import MaintainerQueueStatusClient, dumps_queue
from .registration import (
    DEFAULT_SERVICE_URL,
    load_registration,
    registration_path,
    redacted_status,
    register_installation,
    save_registration,
    set_telemetry,
)
from .recommendation_preview import build_policy_aware_preview, dumps_preview, fixture_preview
from .service_diagnostics import (
    configure_service,
    doctor as service_doctor,
    local_status as service_status,
    registration_dry_run,
    test_proof as service_test_proof,
    verify_trust as service_verify_trust,
)
from .setup_wizard import build_setup_report, format_setup_text
from .skill_improvements import SkillImprovementClient, dumps_improvement
from .support_bundle import build_bundle_report, format_bundle_text
from .native import DEFAULT_AGENT_ORDER, sync_native_sources
from .org_status import local_org_status, refresh_org_status
from .plan_status import doctor as plan_doctor
from .plan_status import explain_feature, format_plan_status, redacted_plan_summary, refresh_plan_status
from .policy import explain_policy, install_policy, load_policy, policy_summary, read_policy_file, remove_policy, verify_policy_payload
from .policy_enforcement import enforce_local_root
from .policy_sync import managed_policy_status, sync_managed_policy
from .private_pack_diagnostics import private_pack_doctor
from .private_packs import PrivatePackClient, list_installed_private_packs, remove_private_pack
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
from .updates import UpdateClient, load_release_channel, rollback_collection, save_release_channel


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


class VectorModelMismatch(RuntimeError):
    """The on-disk vector index was built with a different embedding model."""


def _model_mismatch_error(built_with: str, requested: str, index_path: Path) -> VectorModelMismatch:
    return VectorModelMismatch(
        f"Vector index was built with embedding model '{built_with}' but the current model is '{requested}' "
        f"({index_path}). Run `unlimited-skills vector-reindex` to rebuild the index with the current model."
    )


def load_vector_sidecar(root: Path, model: str) -> list[dict] | None:
    path = vector_sidecar_path(root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Vector sidecar is invalid JSON: {path}") from exc
    built_with = str(payload.get("model") or "")
    if built_with != model:
        # Embeddings from different models are not comparable; falling back to
        # stale vectors would silently return garbage rankings.
        raise _model_mismatch_error(built_with or "<unknown>", model, path)
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
    meta_path = vector_meta_path(root)
    if meta_path.is_file():
        try:
            meta = json.loads(read_text(meta_path))
        except json.JSONDecodeError:
            meta = {}
        built_with = str(meta.get("model") or "")
        if built_with and built_with != model:
            raise _model_mismatch_error(built_with, model, meta_path)
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
    except VectorModelMismatch as exc:
        if require_vector:
            raise
        # Degrading to lexical-only must not be silent: results change quality.
        print(f"[unlimited-skills] vector search skipped: {exc}", file=sys.stderr)
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
    enforce_local_root(root, action="reindex library root")
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
    enforce_local_root(root, action="search library root")
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
    enforce_local_root(root, action="list library root")
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
    enforce_local_root(root, action="vector reindex library root")
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
    enforce_local_root(root, action="view library root")
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
    enforce_local_root(root, action="where library root")
    maybe_sync_native(args, root)
    path = find_by_name(root, args.name)
    if not path:
        print(f"Skill not found: {args.name}", file=sys.stderr)
        return 2
    print(path)
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    enforce_local_root(root, action="use library root")
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


def _print_import_report(report, *, as_json: bool) -> None:
    from dataclasses import asdict as _asdict

    if as_json:
        print(json.dumps(_asdict(report), ensure_ascii=False, indent=2))
        return
    verb = "Would import" if report.dry_run else "Imported"
    print(f"{verb} {len(report.imported)} skill(s) into local/{report.collection}")
    print(f"  source: {report.source}")
    if report.skipped_identical:
        print(f"  skipped (identical): {len(report.skipped_identical)}")
    if report.conflicts:
        print(f"  conflicts (same name, different content): {len(report.conflicts)}")
        for conflict in report.conflicts:
            print(f"    - {conflict.name}: {conflict.reason}")
            print(f"      incoming: {conflict.source_path}")
            print(f"      existing: {conflict.existing_path}")
        if not report.dry_run:
            print("  conflicting skills were copied to the collection's duplicates/ folder.")


def cmd_import_dir(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    source = Path(args.path).expanduser()
    if not source.is_dir():
        print(f"Source directory not found: {source}", file=sys.stderr)
        return 1
    report = import_skill_dirs(source, root, args.collection, dry_run=args.dry_run)
    if not args.dry_run and not args.skip_reindex and report.imported:
        save_index(root)
    _print_import_report(report, as_json=args.json)
    return 0


def cmd_import_github(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    collection = args.collection or _collection_from_repo(args.repo)
    try:
        report = import_github_repo(
            root,
            args.repo,
            collection,
            ref=args.ref or "",
            subdir=args.subdir or "",
            dry_run=args.dry_run,
        )
    except (RuntimeError, OSError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    if not args.dry_run and not args.skip_reindex and report.imported:
        save_index(root)
    _print_import_report(report, as_json=args.json)
    return 0


def _collection_from_repo(repo: str) -> str:
    tail = repo.rstrip("/").split("/")[-1]
    return re.sub(r"[^a-z0-9._-]+", "-", tail.removesuffix(".git").lower()).strip("-.") or "imported"


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


def cmd_setup(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    mode = "overview"
    if getattr(args, "setup_command", "") == "doctor":
        mode = "overview"
    elif args.local_only:
        mode = "local-only"
    elif args.registered:
        mode = "registered"
    elif args.hub:
        mode = "hub"
    elif args.enterprise:
        mode = "enterprise"
    elif args.private_packs:
        mode = "private-packs"
    payload = build_setup_report(root, mode=mode, dry_run=args.dry_run, agent=getattr(args, "agent", "all"))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_setup_text(payload))
    return 0


def cmd_support_bundle(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    out = Path(args.out).expanduser() if args.out else None
    report = build_bundle_report(
        root,
        out=out,
        dry_run=args.dry_run,
        include_paths=args.include_paths,
        include_private_pack_refs=args.include_private_pack_refs,
    )
    if args.json:
        print(json.dumps(report["manifest"], ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_bundle_text(report))
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


def cmd_service_configure(args: argparse.Namespace) -> int:
    payload = configure_service(args.url, allow_insecure_localhost=args.allow_insecure_localhost)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_service_status(args: argparse.Namespace) -> int:
    payload = service_status(refresh=args.refresh, timeout=args.timeout)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_service_doctor(args: argparse.Namespace) -> int:
    payload = service_doctor(service_url=args.url or None, timeout=args.timeout)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_service_verify_trust(args: argparse.Namespace) -> int:
    payload = service_verify_trust(service_url=args.url or None, timeout=args.timeout)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_service_test_registration(args: argparse.Namespace) -> int:
    if not args.dry_run:
        raise RuntimeError("service test-registration currently supports only --dry-run.")
    payload = registration_dry_run(service_url=args.url or None, agent=args.agent, telemetry="on" if args.telemetry else "off")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_service_test_proof(args: argparse.Namespace) -> int:
    payload = service_test_proof(service_url=args.url or None)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_policy_status(args: argparse.Namespace) -> int:
    payload = policy_summary(load_policy())
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_policy_verify(args: argparse.Namespace) -> int:
    payload = verify_policy_payload(read_policy_file(Path(args.policy_json).expanduser()))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_policy_install(args: argparse.Namespace) -> int:
    payload = install_policy(Path(args.policy_json).expanduser())
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_policy_remove(args: argparse.Namespace) -> int:
    payload = remove_policy(yes=args.yes)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_policy_explain(args: argparse.Namespace) -> int:
    print(explain_policy(load_policy()))
    return 0


def cmd_policy_sync(args: argparse.Namespace) -> int:
    payload = sync_managed_policy(root=args.root, dry_run=args.dry_run, timeout=args.timeout)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        state = payload["managed_state"]
        print("Managed policy sync: " + ("dry-run" if payload["dry_run"] else "applied"))
        print(f"Action: {state.get('action')}")
        print(f"Changed: {str(payload.get('changed')).lower()}")
        if state.get("policy_id"):
            print(f"Policy: {state.get('policy_id')}")
        if state.get("path"):
            print(f"Path: {state.get('path')}")
    return 0


def cmd_policy_managed_status(args: argparse.Namespace) -> int:
    payload = managed_policy_status()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        managed = payload["managed_state"]
        installed = payload["installed_policy"]
        print("Managed: " + ("yes" if managed.get("managed") else "no"))
        print("Last sync: " + (managed.get("last_sync_at") or "never"))
        print("Installed policy: " + (installed.get("policy_id") or "(none)"))
        print("Mode: " + str(installed.get("mode") or "disabled"))
    return 0


def cmd_updates_check(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout, channel=args.channel)
    updates = client.check(root)
    if args.collection:
        updates = [item for item in updates if item.collection == args.collection]
    payload = {"root": str(root), "channel": client.channel, "count": len(updates), "updates": [item.__dict__ for item in updates]}
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
    client = UpdateClient(load_registration(), timeout=args.timeout, channel=args.channel)
    updates = client.check(root)
    if args.collection:
        updates = [item for item in updates if item.collection == args.collection]
    if args.dry_run:
        print(json.dumps({"root": str(root), "channel": client.channel, "dry_run": True, "count": len(updates), "updates": [item.__dict__ for item in updates]}, ensure_ascii=False, indent=2))
        return 0
    applied = [client.apply(root, item) for item in updates]
    if applied and not args.skip_reindex:
        save_index(root)
    print(json.dumps({"root": str(root), "channel": client.channel, "applied": applied, "reindexed": bool(applied and not args.skip_reindex)}, ensure_ascii=False, indent=2))
    return 0


def cmd_updates_rollback(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if not args.yes and not args.dry_run:
        _confirm_or_fail(False, "ROLLBACK", "Update rollback will replace the active collection with the latest rollback snapshot.")
    if args.dry_run:
        payload = {"root": str(root), "collection": args.collection, "dry_run": True}
    else:
        payload = {"root": str(root), "dry_run": False, "result": rollback_collection(root, args.collection)}
        if not args.skip_reindex:
            save_index(root)
            payload["reindexed"] = True
        else:
            payload["reindexed"] = False
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_catalog_list(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = UpdateClient(load_registration(), timeout=args.timeout, channel=args.channel)
    payload = client.catalog(root)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _emit_catalog_browser_items(items, *, as_json: bool, show_quality: bool = False) -> int:
    payload = {"count": len(items), "items": [asdict(item) for item in items]}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not items:
        print("No catalog items found.")
        return 0
    for item in items:
        label = item.pack_id or item.item_id
        suffix = f" {item.version}" if item.version else ""
        status = item.review_status
        marker = "installable" if item.installable else "not-installable"
        print(f"{item.item_id}: {label}{suffix} [{item.source}/{status}/{marker}]")
        if item.description:
            print(f"  {item.description}")
        if item.warnings:
            print("  warnings: " + ", ".join(item.warnings))
        if show_quality and item.quality_grade:
            print(f"  quality: {item.quality_grade.upper()} / {item.score_band or 'unknown'}")
            if item.last_eval_at:
                print(f"  last eval: {item.last_eval_at}")
            if item.blockers:
                print("  blockers: " + ", ".join(item.blockers))
            if item.compatibility_notes:
                print("  compatibility: " + ", ".join(item.compatibility_notes))
            if item.feedback_issue_categories:
                print("  feedback issues: " + ", ".join(item.feedback_issue_categories))
    return 0


def _catalog_client(args: argparse.Namespace) -> CatalogBrowserClient:
    return CatalogBrowserClient(load_registration(), timeout=args.timeout)


def _catalog_feedback_client(args: argparse.Namespace) -> CatalogFeedbackClient:
    return CatalogFeedbackClient(load_registration(), timeout=args.timeout)


def _catalog_quality_client(args: argparse.Namespace) -> CatalogQualityClient:
    return CatalogQualityClient(load_registration(), timeout=args.timeout)


def _skill_improvement_client(args: argparse.Namespace) -> SkillImprovementClient:
    return SkillImprovementClient(load_registration(), timeout=args.timeout)


def _maintainer_queue_client(args: argparse.Namespace) -> MaintainerQueueStatusClient:
    return MaintainerQueueStatusClient(load_registration(), timeout=args.timeout)


def cmd_catalog_browse(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    items = _catalog_client(args).browse(
        root,
        channel=args.channel,
        source=args.source,
        compatible_agent=args.compatible_agent,
        skill_kind=args.skill_kind,
        category=args.category,
        include_deprecated=args.include_deprecated,
        show_quality=args.show_quality,
        limit=args.limit,
    )
    return _emit_catalog_browser_items(items, as_json=args.json, show_quality=args.show_quality)


def cmd_catalog_search(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    items = _catalog_client(args).search(
        root,
        query=args.query,
        channel=args.channel,
        source=args.source,
        compatible_agent=args.compatible_agent,
        skill_kind=args.skill_kind,
        category=args.category,
        include_deprecated=args.include_deprecated,
        show_quality=args.show_quality,
        limit=args.limit,
    )
    return _emit_catalog_browser_items(items, as_json=args.json, show_quality=args.show_quality)


def cmd_catalog_filters(args: argparse.Namespace) -> int:
    payload = _catalog_client(args).filters(channel=args.channel)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_catalog_preview(args: argparse.Namespace) -> int:
    payload = _catalog_client(args).preview(args.item_id, channel=args.channel)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    item = payload["item"]
    preview = item.get("preview", {}) if isinstance(item.get("preview"), dict) else {}
    print(f"{item.get('item_id')}: {item.get('pack_id')} {item.get('version', '')} [{item.get('source')}/{item.get('review_status')}]")
    if preview.get("description") or item.get("description"):
        print(preview.get("description") or item.get("description"))
    if preview.get("requirements"):
        print("Requirements: " + ", ".join(str(value) for value in preview["requirements"]))
    if item.get("warnings"):
        print("Warnings: " + ", ".join(str(value) for value in item["warnings"]))
    return 0


def cmd_catalog_recommendation_preview(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if args.fixture_case:
        payload = fixture_preview(args.fixture_case)
    else:
        if not args.item_id:
            raise RuntimeError("catalog recommendation-preview requires item_id unless --fixture-case is used.")
        state = load_registration()
        if not state.registered:
            payload = build_policy_aware_preview(
                catalog_item={
                    "item_id": args.item_id,
                    "source_type": "hosted_official",
                    "review_status": "registration_required",
                    "requires_registration": True,
                    "installable": False,
                },
                registered=False,
                signed_metadata=True,
                active_agent=args.agent,
                channel=args.channel or "stable",
                entitlement_status=redacted_plan_summary(state=state),
                policy_status=policy_summary(load_policy()),
            )
        else:
            catalog_payload = _catalog_client(args).preview(args.item_id, channel=args.channel)
            item = catalog_payload.get("item") if isinstance(catalog_payload.get("item"), dict) else {}
            quality_status = None
            improvement_status = None
            for label, loader in (
                ("quality", lambda: _catalog_quality_client(args).quality(args.item_id)),
                ("improvement", lambda: _skill_improvement_client(args).improvement_status(root, args.item_id)),
            ):
                try:
                    if label == "quality":
                        quality_status = loader()
                    else:
                        improvement_status = loader()
                except Exception:
                    if args.strict_supplemental:
                        raise
            payload = build_policy_aware_preview(
                catalog_item=item,
                signed_metadata=True,
                registered=True,
                active_agent=args.agent,
                channel=args.channel or str(item.get("channel") or "stable"),
                quality_status=quality_status,
                improvement_status=improvement_status,
                entitlement_status=redacted_plan_summary(state=state),
                policy_status=policy_summary(load_policy()),
            )
    if args.json:
        print(dumps_preview(payload))
        return 0
    decision = payload["decision"]
    print(f"Item: {payload['item_id']}")
    print("Preview only: yes")
    print(f"Outcome: {decision['outcome']}")
    print(f"Reason: {decision['reason']}")
    print(f"Next: {decision['next_command']}")
    if decision.get("refusal_code"):
        print(f"Refusal: {decision['refusal_code']}")
        print(f"Owner: {decision.get('owner') or '(unknown)'}")
        print(f"Fallback: {decision.get('fallback') or '(none)'}")
    print("No install, update, remove, rewrite, telemetry, or catalog distribution was performed.")
    return 0


def cmd_catalog_install(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if not args.dry_run and not args.yes:
        if not sys.stdin.isatty():
            raise RuntimeError("Catalog install requires --yes in non-interactive mode.")
        typed = input("Type INSTALL to install this signed catalog item: ")
        if typed.strip() != "INSTALL":
            raise RuntimeError("Catalog install cancelled.")
    result = _catalog_client(args).install(
        root,
        item_id=args.item_id,
        dry_run=args.dry_run,
        yes=args.yes,
        target_collection=args.collection,
        skip_reindex=args.skip_reindex,
    )
    reindexed = False
    if isinstance(result, dict) and result.get("installed") and not args.skip_reindex:
        save_index(root)
        reindexed = True
        result["reindexed"] = True
    if args.json or args.dry_run:
        payload = asdict(result) if hasattr(result, "__dataclass_fields__") else result
        if isinstance(payload, dict) and "reindexed" not in payload:
            payload["reindexed"] = reindexed
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Installed catalog item {args.item_id}")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0


def _catalog_feedback_detail_from_args(args: argparse.Namespace) -> dict[str, object]:
    detail: dict[str, object] = {}
    for key, attr in (
        ("agent", "agent"),
        ("client_version", "client_version"),
        ("core_version", "core_version"),
        ("os", "os"),
        ("command", "command"),
        ("error_code", "error_code"),
        ("expected_behavior", "expected_behavior"),
        ("actual_behavior", "actual_behavior"),
        ("reproduction_hint", "reproduction_hint"),
    ):
        value = getattr(args, attr, "")
        if value:
            detail[key] = value
    if args.http_status:
        detail["http_status"] = int(args.http_status)
    return detail


def cmd_catalog_feedback(args: argparse.Namespace) -> int:
    payload = build_feedback_payload(
        item_id=args.item_id,
        feedback_type=args.type,
        severity=args.severity,
        title=args.title,
        detail=_catalog_feedback_detail_from_args(args),
    )
    if args.dry_run:
        print(json.dumps({"dry_run": True, "payload": payload.to_json(), "privacy": {"automatic_telemetry": False}}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            raise RuntimeError("Catalog feedback submit requires --yes in non-interactive mode.")
        typed = input("Type SEND to submit this redacted catalog feedback: ")
        if typed.strip() != "SEND":
            raise RuntimeError("Catalog feedback cancelled.")
    response = _catalog_feedback_client(args).submit(payload)
    if args.json:
        print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Catalog feedback submitted: {response.get('feedback_id', '')}")
    return 0


def cmd_catalog_feedback_status(args: argparse.Namespace) -> int:
    response = _catalog_feedback_client(args).status(args.item_id, limit=args.limit)
    if args.json:
        print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Feedback count: {response.get('feedback_count', 0)}")
        for key, value in sorted((response.get("counts_by_status") or {}).items()):
            print(f"{key}: {value}")
    return 0


def cmd_catalog_quality(args: argparse.Namespace) -> int:
    status = _catalog_quality_client(args).quality(args.item_id)
    if args.json:
        print(dumps_status(status))
        return 0
    print(f"Item: {status.item_id}")
    print(f"Quality: {status.quality_grade.upper()} ({status.score_band})")
    print(f"Last eval: {status.last_eval_at or '(unknown)'}")
    print(f"Install risk: {status.install_risk}")
    print(f"Deprecation: {status.deprecation_status}")
    if status.blockers:
        print("Blockers: " + ", ".join(status.blockers))
    if status.warnings:
        print("Warnings: " + ", ".join(status.warnings))
    if status.compatibility_notes:
        print("Compatibility: " + ", ".join(status.compatibility_notes))
    if status.feedback_issue_categories:
        print("Feedback issues: " + ", ".join(status.feedback_issue_categories))
    return 0


def cmd_catalog_eval_status(args: argparse.Namespace) -> int:
    status = _catalog_quality_client(args).eval_status(args.item_id)
    if args.json:
        print(dumps_status(status))
        return 0
    print(f"Item: {status.item_id}")
    print(f"Evaluation: {status.evaluation_status}")
    print(f"Quality: {status.quality_grade.upper()} ({status.score_band})")
    print(f"Last eval: {status.last_eval_at or '(unknown)'}")
    if status.next_eval_at:
        print(f"Next eval: {status.next_eval_at}")
    if status.blockers:
        print("Blockers: " + ", ".join(status.blockers))
    if status.warnings:
        print("Warnings: " + ", ".join(status.warnings))
    if status.compatibility_notes:
        print("Compatibility: " + ", ".join(status.compatibility_notes))
    if status.feedback_issue_categories:
        print("Feedback issues: " + ", ".join(status.feedback_issue_categories))
    return 0


def cmd_catalog_explain_risk(args: argparse.Namespace) -> int:
    payload = _catalog_quality_client(args).explain_risk(args.item_id)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    status = payload["quality_status"]
    print(f"Item: {payload['item_id']}")
    print(f"Quality: {str(status.get('quality_grade') or 'unknown').upper()} ({status.get('score_band') or 'unknown'})")
    print("Blocked: " + ("yes" if payload["blocked"] else "no"))
    print("Warning: " + ("yes" if payload["warning"] else "no"))
    print(payload["message"])
    blockers = status.get("blockers") or []
    warnings = status.get("warnings") or []
    if blockers:
        print("Blockers: " + ", ".join(str(item) for item in blockers))
    if warnings:
        print("Warnings: " + ", ".join(str(item) for item in warnings))
    return 0


def cmd_catalog_improvement_status(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    status = _skill_improvement_client(args).improvement_status(root, args.item_id)
    queue_status = _maintainer_queue_client(args).status(root, args.item_id) if getattr(args, "include_queue", False) else None
    if args.json:
        payload = status.to_json()
        if queue_status is not None:
            payload["maintainer_queue"] = queue_status.to_json()
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"Item: {status.item_id}")
    print(f"Installed version: {status.installed_version or '(unknown)'}")
    print(f"Recommended: {status.recommended_version or '(none)'} on {status.recommended_channel}")
    print(f"Open issues: {status.open_issue_count}")
    if status.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(status.severity_summary.items())))
    print(f"Fix status: {status.fix_status}")
    print("Stale installed version: " + ("yes" if status.stale_installed_version else "no"))
    print(f"Recommended action: {status.recommended_action}")
    print("Deprecated: " + ("yes" if status.deprecated else "no"))
    print("Retired: " + ("yes" if status.retired else "no"))
    if status.deprecation_reason:
        print(f"Deprecation reason: {status.deprecation_reason}")
    if status.retirement_reason:
        print(f"Retirement reason: {status.retirement_reason}")
    if status.compatibility_notes:
        print("Compatibility: " + ", ".join(status.compatibility_notes))
    if queue_status is not None:
        print(f"Queue status: {queue_status.queue_status}")
        print(f"Maintainer state: {queue_status.maintainer_state}")
        if queue_status.severity_summary:
            print("Queue severity: " + ", ".join(f"{key}={value}" for key, value in sorted(queue_status.severity_summary.items())))
        if queue_status.fixed_pending_eval_evidence_ref:
            print(f"Fixed pending eval evidence: {queue_status.fixed_pending_eval_evidence_ref}")
        if queue_status.eval_gate_ref:
            print(f"Eval gate: {queue_status.eval_gate_ref}")
        print(f"Queue recommended action: {queue_status.recommended_user_action}")
    return 0


def cmd_catalog_maintainer_status(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    status = _maintainer_queue_client(args).status(root, args.item_id)
    if args.json:
        print(dumps_queue(status))
        return 0
    print(f"Item: {status.item_id}")
    print(f"Queue status: {status.queue_status}")
    print(f"Maintainer state: {status.maintainer_state}")
    if status.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(status.severity_summary.items())))
    if status.issue_categories:
        print("Issue categories: " + ", ".join(status.issue_categories))
    if status.fixed_pending_eval_evidence_ref:
        print(f"Fixed pending eval evidence: {status.fixed_pending_eval_evidence_ref}")
    if status.eval_gate_ref:
        print(f"Eval gate: {status.eval_gate_ref}")
    print(f"Recommended action: {status.recommended_user_action}")
    if status.updated_at:
        print(f"Updated: {status.updated_at}")
    return 0


def cmd_catalog_maintainer_queue_summary(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    summary = _maintainer_queue_client(args).summary(root)
    if args.json:
        print(dumps_queue(summary))
        return 0
    print("Maintainer queue summary")
    print(f"Total: {summary.total_count}")
    if summary.queue_status_counts:
        print("Queue statuses: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.queue_status_counts.items())))
    if summary.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.severity_summary.items())))
    if summary.maintainer_state_counts:
        print("Maintainer states: " + ", ".join(f"{key}={value}" for key, value in sorted(summary.maintainer_state_counts.items())))
    if summary.issue_categories:
        print("Issue categories: " + ", ".join(summary.issue_categories))
    print(f"Fixed pending eval: {summary.fixed_pending_eval_count}")
    print(f"Blocked eval gates: {summary.blocked_eval_gate_count}")
    return 0


def cmd_catalog_fixed_pending_eval(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    status = _maintainer_queue_client(args).fixed_pending_eval(root, args.item_id)
    if args.json:
        print(dumps_queue(status))
        return 0
    print(f"Item: {status.item_id}")
    print("Fixed pending eval: " + ("yes" if status.fixed_pending_eval else "no"))
    print(f"Queue status: {status.queue_status}")
    print(f"Maintainer state: {status.maintainer_state}")
    if status.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(status.severity_summary.items())))
    if status.issue_categories:
        print("Issue categories: " + ", ".join(status.issue_categories))
    if status.evidence_ref:
        print(f"Evidence: {status.evidence_ref}")
    if status.eval_gate_ref:
        print(f"Eval gate: {status.eval_gate_ref}")
    print(f"Recommended action: {status.recommended_user_action}")
    return 0


def cmd_catalog_known_issues(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    status = _skill_improvement_client(args).known_issues(root, args.item_id)
    if args.json:
        print(dumps_improvement(status))
        return 0
    print(f"Item: {status.item_id}")
    print(f"Open issues: {status.open_issue_count}")
    if status.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(status.severity_summary.items())))
    print(f"Fix status: {status.fix_status}")
    for issue in status.issues:
        label = issue.issue_id or "(issue)"
        title = f": {issue.title}" if issue.title else ""
        print(f"- {label} [{issue.severity}/{issue.status}/{issue.fix_status}]{title}")
        if issue.fixed_in_version:
            print(f"  fixed in: {issue.fixed_in_version}")
        if issue.compatibility_notes:
            print("  compatibility: " + ", ".join(issue.compatibility_notes))
    if status.compatibility_notes:
        print("Compatibility: " + ", ".join(status.compatibility_notes))
    return 0


def cmd_catalog_update_recommendations(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    recommendations = _skill_improvement_client(args).update_recommendations(root)
    queue_summary = _maintainer_queue_client(args).summary(root) if getattr(args, "include_queue", False) else None
    queue_by_item = {}
    if getattr(args, "include_queue", False):
        queue_client = _maintainer_queue_client(args)
        for recommendation in recommendations:
            queue_by_item[recommendation.item_id] = queue_client.status(root, recommendation.item_id).to_json()
    recommendation_payloads = []
    for item in recommendations:
        item_payload = item.to_json()
        if item.item_id in queue_by_item:
            item_payload["maintainer_queue_status"] = queue_by_item[item.item_id]
        recommendation_payloads.append(item_payload)
    payload = {
        "schema_version": 1,
        "count": len(recommendations),
        "preview_only": True,
        "automatic_update": False,
        "automatic_install": False,
        "automatic_remove": False,
        "include_queue": bool(getattr(args, "include_queue", False)),
        "recommendations": recommendation_payloads,
    }
    if queue_summary is not None:
        payload["maintainer_queue_summary"] = queue_summary.to_json()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not recommendations:
        print("No skill update recommendations.")
        return 0
    print("Skill update recommendations (preview only):")
    for item in recommendations:
        print(
            f"{item.item_id}: {item.recommended_action} "
            f"{item.installed_version or '(unknown)'} -> {item.recommended_version or '(none)'} "
            f"on {item.recommended_channel}"
        )
        print(f"  stale: {'yes' if item.stale_installed_version else 'no'}; open issues: {item.open_issue_count}; fix status: {item.fix_status}")
        if item.reason:
            print(f"  reason: {item.reason}")
        if item.compatibility_notes:
            print("  compatibility: " + ", ".join(item.compatibility_notes))
        if item.item_id in queue_by_item:
            queue = queue_by_item[item.item_id]
            print(
                "  queue: "
                f"{queue.get('queue_status', 'unknown')}; "
                f"maintainer state: {queue.get('maintainer_state', 'unknown')}; "
                f"recommended action: {queue.get('recommended_user_action', 'none')}"
            )
    if queue_summary is not None:
        print(f"Maintainer queue total: {queue_summary.total_count}")
    return 0


def cmd_catalog_update_preview(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    recommendation = _skill_improvement_client(args).update_preview(root, args.item_id)
    if args.json:
        print(dumps_improvement(recommendation))
        return 0
    print(f"Item: {recommendation.item_id}")
    print("Preview only: yes")
    print(f"Recommended action: {recommendation.recommended_action}")
    print(f"Installed version: {recommendation.installed_version or '(unknown)'}")
    print(f"Recommended: {recommendation.recommended_version or '(none)'} on {recommendation.recommended_channel}")
    print("Stale installed version: " + ("yes" if recommendation.stale_installed_version else "no"))
    print(f"Open issues: {recommendation.open_issue_count}")
    if recommendation.severity_summary:
        print("Severity: " + ", ".join(f"{key}={value}" for key, value in sorted(recommendation.severity_summary.items())))
    print(f"Fix status: {recommendation.fix_status}")
    if recommendation.reason:
        print(f"Reason: {recommendation.reason}")
    if recommendation.compatibility_notes:
        print("Compatibility: " + ", ".join(recommendation.compatibility_notes))
    print("No update, install, or remove operation was performed.")
    return 0


def cmd_catalog_deprecation_status(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    status = _skill_improvement_client(args).deprecation_status(root, args.item_id)
    if args.json:
        print(dumps_improvement(status))
        return 0
    print(f"Item: {status.item_id}")
    print("Deprecated: " + ("yes" if status.deprecated else "no"))
    print("Retired: " + ("yes" if status.retired else "no"))
    if status.deprecation_reason:
        print(f"Deprecation reason: {status.deprecation_reason}")
    if status.retirement_reason:
        print(f"Retirement reason: {status.retirement_reason}")
    if status.replacement_item_id:
        print(f"Replacement: {status.replacement_item_id}")
    print(f"Recommended action: {status.recommended_action}")
    if status.recommended_version:
        print(f"Recommended: {status.recommended_version} on {status.recommended_channel}")
    if status.compatibility_notes:
        print("Compatibility: " + ", ".join(status.compatibility_notes))
    return 0


def cmd_release_status(args: argparse.Namespace) -> int:
    state = load_release_channel()
    client = UpdateClient(load_registration(), timeout=args.timeout, channel=args.channel)
    payload = client.release_channels()
    payload["local_release_channel"] = state.to_json()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"Current local channel: {state.channel} ({'pinned' if state.pinned else 'default'})")
    for item in payload.get("channels", []):
        if isinstance(item, dict):
            marker = "*" if item.get("name") == client.channel else " "
            print(f"{marker} {item.get('name')}: {str(item.get('current_release_id') or '')[:12]} ({item.get('status') or 'active'})")
    return 0


def cmd_release_pin(args: argparse.Namespace) -> int:
    path = save_release_channel(args.channel, pinned=True)
    payload = {"channel": args.channel, "pinned": True, "path": str(path)}
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
    items = client.list_community_items_v2(root, limit=args.limit, compatible_agent=args.compatible_agent, tags=_split_csv(args.tags), channel=args.channel)
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
        payload["result"] = {
            "submission_id": "",
            "status": "draft",
            "preview_path": draft.preview_path,
            "uploaded": False,
            "message": "Dry run: no content uploaded.",
        }
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


def cmd_community_withdraw(args: argparse.Namespace) -> int:
    client = CommunityClient(load_registration(), timeout=args.timeout)
    payload = client.withdraw_submission(args.submission_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_community_review_notes(args: argparse.Namespace) -> int:
    client = CommunityClient(load_registration(), timeout=args.timeout)
    payload = client.review_notes(args.submission_id)
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


def _emit_private_pack_items(items, *, as_json: bool) -> int:
    payload = {"count": len(items), "items": [asdict(item) for item in items]}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not items:
        print("No private team packs found.")
        return 0
    for item in items:
        print(f"{item.pack_id}: {item.name} {item.version} [{item.team_id}]")
    return 0


def cmd_private_packs_list(args: argparse.Namespace) -> int:
    client = PrivatePackClient(load_registration(), timeout=args.timeout)
    return _emit_private_pack_items(client.list(), as_json=args.json)


def cmd_private_packs_preview(args: argparse.Namespace) -> int:
    client = PrivatePackClient(load_registration(), timeout=args.timeout)
    payload = client.preview(args.pack_id)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    pack = payload["pack"]
    print(f"{pack['pack_id']}: {pack['name']} {pack['version']} [{pack['team_id']}]")
    print(f"Archive SHA256: {pack['archive_sha256']}")
    return 0


def cmd_private_packs_install(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = PrivatePackClient(load_registration(), timeout=args.timeout)
    if not args.dry_run:
        _confirm_or_fail(args.yes, "INSTALL", "Private pack install may change registry/private skill files.")
    result = client.install(root, args.pack_id, dry_run=args.dry_run)
    reindexed = False
    if result.installed and not args.skip_reindex:
        save_index(root)
        reindexed = True
    payload = {"result": asdict(result), "reindexed": reindexed}
    if args.json or args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Installed private pack {result.pack_id} {result.version}")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0


def cmd_private_packs_sync(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    client = PrivatePackClient(load_registration(), timeout=args.timeout)
    dry_run = args.dry_run or not args.yes
    if not dry_run:
        _confirm_or_fail(args.yes, "SYNC", "Private pack sync may install or update registry/private skill packs.")
    payload = client.sync(root, dry_run=dry_run)
    reindexed = False
    if payload["applied"] and not args.skip_reindex:
        save_index(root)
        reindexed = True
    payload["reindexed"] = reindexed
    if args.json or dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Private pack sync applied {len(payload['applied'])} change(s).")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0


def cmd_private_packs_installed(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    installed = list_installed_private_packs(root)
    payload = {"root": str(root), "count": len(installed), "items": [asdict(item) for item in installed]}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not installed:
        print("No installed private team packs found.")
        return 0
    for item in installed:
        print(f"{item.pack_id}: {item.name} {item.version} -> {item.target}")
    return 0


def cmd_private_packs_remove(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    result = remove_private_pack(root, args.pack_id, dry_run=args.dry_run or not args.yes)
    reindexed = False
    if result.get("removed") and not args.skip_reindex:
        save_index(root)
        reindexed = True
    payload = {"result": result, "reindexed": reindexed}
    if args.json or result.get("dry_run"):
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Removed private pack {args.pack_id}")
        if reindexed:
            print("Lexical index rebuilt.")
    return 0


def cmd_private_packs_access_check(args: argparse.Namespace) -> int:
    client = PrivatePackClient(load_registration(), timeout=args.timeout)
    payload = client.access_check_diagnostic(args.pack_id)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"Pack: {payload['pack_ref']}")
    print(f"Status: {payload['status']}")
    print("Authorized: " + ("yes" if payload["authorized"] else "no"))
    if payload["denial_reasons"]:
        print("Denial reasons: " + ", ".join(payload["denial_reasons"]))
    if payload["request_id"]:
        print(f"Request: {payload['request_id']}")
    return 0


def cmd_private_packs_doctor(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    payload = private_pack_doctor(root, state=load_registration())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"Status: {payload['status']}")
    print("Registered: " + ("yes" if payload["registered"] else "no"))
    checks = payload["setup"]["checks"]
    print(f"Installed private packs: {checks['installed_count']}")
    print(f"Trust key: {checks['trust_key']}")
    if payload["recommendations"]:
        print("Recommendations: " + " ".join(payload["recommendations"]))
    return 0


def cmd_org_status(args: argparse.Namespace) -> int:
    registration = load_registration()
    if args.refresh:
        payload = refresh_org_status(registration, timeout=args.timeout)
    else:
        payload = local_org_status(registration)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print("Registered: " + ("yes" if payload["registered"] else "no"))
    print(f"Plan: {payload['plan']}")
    org = payload["organization"]
    print(f"Organization: {org.get('name') or '(none)'} ({org.get('status') or 'unknown'}, role: {org.get('role') or 'none'})")
    team = payload["team"]
    print(f"Team: {team.get('team_name') or '(none)'} ({team.get('status') or 'none'}, role: {team.get('role') or 'none'})")
    print(f"Source: {payload['source']}")
    if payload["last_refreshed_at"]:
        print(f"Last refreshed: {payload['last_refreshed_at']}")
    if payload["recommendations"]:
        print("Recommendations: " + " ".join(payload["recommendations"]))
    return 0


def cmd_plan_status(args: argparse.Namespace) -> int:
    payload = redacted_plan_summary()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_plan_status(payload))
    return 0


def cmd_plan_refresh(args: argparse.Namespace) -> int:
    payload = refresh_plan_status(timeout=args.timeout)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_plan_status(payload["plan_status"]))
    return 0


def cmd_plan_explain(args: argparse.Namespace) -> int:
    payload = explain_feature(args.feature)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Feature: {payload['feature']}")
        print("Allowed: " + ("yes" if payload["allowed"] else "no"))
        if payload["denial_reason"]:
            print(f"Denial reason: {payload['denial_reason']}")
            print(payload["message"])
    return 0


def cmd_plan_doctor(args: argparse.Namespace) -> int:
    payload = plan_doctor()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("Plan doctor: " + ("ok" if payload["ok"] else "needs attention"))
        print(format_plan_status(payload["plan_status"]))
        for name, check in payload["checks"].items():
            print(f"{name}: {'ok' if check['ok'] else 'attention'}")
            if check.get("denial_reason"):
                print(f"  denial_reason={check['denial_reason']}")
    return 0


def cmd_billing_status(args: argparse.Namespace) -> int:
    payload = redacted_billing_summary()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_billing_status(payload))
    return 0


def cmd_billing_refresh(args: argparse.Namespace) -> int:
    payload = refresh_billing_status(timeout=args.timeout)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_billing_status(payload["billing_status"]))
    return 0


def cmd_billing_doctor(args: argparse.Namespace) -> int:
    payload = billing_doctor()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("Billing doctor: " + ("ok" if payload["ok"] else "needs attention"))
        print(format_billing_status(payload["billing_status"]))
        for name, check in payload["checks"].items():
            print(f"{name}: {'ok' if check['ok'] else 'attention'}")
            if check.get("denial_reason"):
                print(f"  denial_reason={check['denial_reason']}")
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
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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

    import_dir = sub.add_parser("import-dir", help="Import skills from a local directory into the library with sha256 dedup and conflict reporting.")
    import_dir.add_argument("path", help="Directory to scan recursively for SKILL.md files.")
    import_dir.add_argument("--collection", required=True, help="Library collection name (stored under local/<collection>).")
    import_dir.add_argument("--dry-run", action="store_true", help="Report what would be imported without writing files.")
    import_dir.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after importing.")
    import_dir.add_argument("--json", action="store_true")
    import_dir.set_defaults(func=cmd_import_dir)

    import_github = sub.add_parser("import-github", help="Shallow-clone a GitHub repo and import its skills into the library.")
    import_github.add_argument("repo", help="Repository as 'org/name' or a full git URL.")
    import_github.add_argument("--collection", default="", help="Library collection name. Defaults to the repo name.")
    import_github.add_argument("--ref", default="", help="Git ref (branch, tag, or commit) to check out.")
    import_github.add_argument("--subdir", default="", help="Only import skills under this subdirectory of the repo.")
    import_github.add_argument("--dry-run", action="store_true", help="Report what would be imported without writing files.")
    import_github.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after importing.")
    import_github.add_argument("--json", action="store_true")
    import_github.set_defaults(func=cmd_import_github)

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
    hub_heartbeat = hub_sub.add_parser("heartbeat", help="Send or preview a privacy-safe Local Skill Hub heartbeat.")
    hub_heartbeat.add_argument("--dry-run", action="store_true", help="Print the exact heartbeat payload without contacting the hosted service.")
    hub_heartbeat.add_argument("--json", action="store_true")
    hub_heartbeat.add_argument("--timeout", type=float, default=30.0)
    hub_heartbeat.set_defaults(func=cmd_hub_heartbeat)
    hub_license = hub_sub.add_parser("license", help="Inspect or refresh Local Skill Hub plan entitlements.")
    hub_license_sub = hub_license.add_subparsers(dest="hub_license_command", required=True)
    hub_license_status = hub_license_sub.add_parser("status", help="Show cached Local Skill Hub entitlement status.")
    hub_license_status.add_argument("--json", action="store_true")
    hub_license_status.set_defaults(func=cmd_hub_license_status)
    hub_license_refresh = hub_license_sub.add_parser("refresh", help="Refresh Local Skill Hub plan entitlements from the registration service.")
    hub_license_refresh.add_argument("--json", action="store_true")
    hub_license_refresh.add_argument("--timeout", type=float, default=30.0)
    hub_license_refresh.set_defaults(func=cmd_hub_license_refresh)
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

    setup = sub.add_parser("setup", help="Guided first-run onboarding wizard.")
    setup_modes = setup.add_mutually_exclusive_group()
    setup_modes.add_argument("--local-only", action="store_true", help="Verify local-only Community Core setup without registration.")
    setup_modes.add_argument("--registered", action="store_true", help="Verify registered hosted-service setup boundaries.")
    setup_modes.add_argument("--hub", action="store_true", help="Verify registered Local Skill Hub setup readiness.")
    setup_modes.add_argument("--enterprise", action="store_true", help="Verify Enterprise Skill Lock policy setup status.")
    setup_modes.add_argument("--private-packs", action="store_true", help="Verify hosted private team pack readiness.")
    setup.add_argument("--dry-run", action="store_true", help="Print the setup plan without writing missing local directories.")
    setup.add_argument("--json", action="store_true")
    setup.add_argument("--agent", choices=["codex", "claude-code", "hermes", "openclaw", "all"], default="all", help="Limit embedded doctor diagnostics.")
    setup_sub = setup.add_subparsers(dest="setup_command", required=False)
    setup_doctor = setup_sub.add_parser("doctor", help="Run setup diagnostics in overview mode.")
    setup_doctor.add_argument("--dry-run", action="store_true")
    setup_doctor.add_argument("--json", action="store_true")
    setup_doctor.add_argument("--agent", choices=["codex", "claude-code", "hermes", "openclaw", "all"], default="all", help="Limit embedded doctor diagnostics.")
    setup_doctor.set_defaults(func=cmd_setup, local_only=False, registered=False, hub=False, enterprise=False, private_packs=False)
    setup.set_defaults(func=cmd_setup)

    support = sub.add_parser("support", help="Create redacted support diagnostics.")
    support_sub = support.add_subparsers(dest="support_command", required=True)
    support_bundle = support_sub.add_parser("bundle", help="Create a redacted support diagnostic bundle.")
    support_bundle.add_argument("--out", default="", help="Output zip path. Defaults to a timestamped bundle in the current directory.")
    support_bundle.add_argument("--json", action="store_true", help="Print the redacted manifest as JSON.")
    support_bundle.add_argument("--dry-run", action="store_true", help="Build diagnostics without writing a zip file.")
    support_bundle.add_argument("--include-paths", action="store_true", help="Include local paths in diagnostics. Off by default.")
    support_bundle.add_argument("--include-private-pack-refs", action="store_true", help="Include hashed private pack references. Skill names and bodies are still excluded.")
    support_bundle.set_defaults(func=cmd_support_bundle)

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

    service = sub.add_parser("service", help="Configure and diagnose the registered Unlimited Skills service.")
    service_sub = service.add_subparsers(dest="service_command", required=True)
    service_configure = service_sub.add_parser("configure", help="Store the hosted service URL for onboarding diagnostics.")
    service_configure.add_argument("--url", required=True, help="Service base URL, for example https://unlimited.ai4.sale.")
    service_configure.add_argument("--allow-insecure-localhost", action="store_true", help="Allow http://localhost URLs for local fixture diagnostics only.")
    service_configure.set_defaults(func=cmd_service_configure)
    service_status_parser = service_sub.add_parser("status", help="Show local service configuration and registration state.")
    service_status_parser.add_argument("--refresh", action="store_true", help="Contact health/public-key endpoints; local-only without this flag.")
    service_status_parser.add_argument("--timeout", type=float, default=10.0)
    service_status_parser.set_defaults(func=cmd_service_status)
    service_doctor_parser = service_sub.add_parser("doctor", help="Run privacy-safe service health and trust diagnostics.")
    service_doctor_parser.add_argument("--url", default="", help="Temporarily diagnose this service URL without changing config.")
    service_doctor_parser.add_argument("--timeout", type=float, default=10.0)
    service_doctor_parser.set_defaults(func=cmd_service_doctor)
    service_verify = service_sub.add_parser("verify-trust", help="Fetch public keys and compare them with local trust records.")
    service_verify.add_argument("--url", default="", help="Temporarily verify this service URL without changing config.")
    service_verify.add_argument("--timeout", type=float, default=10.0)
    service_verify.set_defaults(func=cmd_service_verify_trust)
    service_registration = service_sub.add_parser("test-registration", help="Build a redacted registration request without sending it.")
    service_registration.add_argument("--dry-run", action="store_true", required=True, help="Required: print the redacted payload and send nothing.")
    service_registration.add_argument("--url", default="", help="Temporarily use this service URL without changing config.")
    service_registration.add_argument("--agent", default="", help="Optional agent surface label.")
    service_registration.add_argument("--telemetry", action="store_true", help="Preview telemetry opt-in flag in the dry-run payload.")
    service_registration.set_defaults(func=cmd_service_test_registration)
    service_proof = service_sub.add_parser("test-proof", help="Generate a local redacted device-proof header using registration state.")
    service_proof.add_argument("--url", default="", help="Temporarily use this service URL without changing config.")
    service_proof.set_defaults(func=cmd_service_test_proof)

    policy = sub.add_parser("policy", help="Inspect and manage Enterprise Skill Lock local policy.")
    policy_sub = policy.add_subparsers(dest="policy_command", required=True)
    policy_status = policy_sub.add_parser("status", help="Show installed Enterprise Skill Lock policy status.")
    policy_status.set_defaults(func=cmd_policy_status)
    policy_verify = policy_sub.add_parser("verify", help="Verify a signed or hash-pinned Enterprise Skill Lock policy file.")
    policy_verify.add_argument("policy_json")
    policy_verify.set_defaults(func=cmd_policy_verify)
    policy_install = policy_sub.add_parser("install", help="Install a signed or hash-pinned Enterprise Skill Lock policy file.")
    policy_install.add_argument("policy_json")
    policy_install.set_defaults(func=cmd_policy_install)
    policy_remove = policy_sub.add_parser("remove", help="Remove the installed Enterprise Skill Lock policy.")
    policy_remove.add_argument("--yes", action="store_true", help="Confirm policy removal.")
    policy_remove.set_defaults(func=cmd_policy_remove)
    policy_explain = policy_sub.add_parser("explain", help="Explain effective Enterprise Skill Lock behavior.")
    policy_explain.set_defaults(func=cmd_policy_explain)
    policy_sync = policy_sub.add_parser("sync", help="Fetch and apply managed Enterprise Skill Lock policy from the registered registry.")
    policy_sync.add_argument("--dry-run", action="store_true", help="Verify the server assignment without writing local policy state.")
    policy_sync.add_argument("--json", action="store_true", help="Emit JSON output.")
    policy_sync.add_argument("--timeout", type=float, default=30.0)
    policy_sync.set_defaults(func=cmd_policy_sync)
    policy_managed_status = policy_sub.add_parser("managed-status", help="Show last managed Enterprise Skill Lock sync state.")
    policy_managed_status.add_argument("--json", action="store_true", help="Emit JSON output.")
    policy_managed_status.set_defaults(func=cmd_policy_managed_status)

    updates = sub.add_parser("updates", help="Check or apply hosted adapted collection updates.")
    updates_sub = updates.add_subparsers(dest="updates_command", required=True)
    updates_check = updates_sub.add_parser("check", help="Check registered hosted collection updates.")
    updates_check.add_argument("--collection", default="", help="Only check one collection.")
    updates_check.add_argument("--channel", default="", help="Override the pinned release channel for this check.")
    updates_check.add_argument("--json", action="store_true")
    updates_check.add_argument("--timeout", type=float, default=30.0)
    updates_check.set_defaults(func=cmd_updates_check)
    updates_apply = updates_sub.add_parser("apply", help="Download, verify, and install registered hosted collection updates.")
    updates_apply.add_argument("--collection", default="", help="Only apply one collection.")
    updates_apply.add_argument("--channel", default="", help="Override the pinned release channel for this apply.")
    updates_apply.add_argument("--dry-run", action="store_true", help="Show available updates without downloading archives.")
    updates_apply.add_argument("--yes", action="store_true", help="Reserved for non-interactive compatibility.")
    updates_apply.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after applying updates.")
    updates_apply.add_argument("--timeout", type=float, default=30.0)
    updates_apply.set_defaults(func=cmd_updates_apply)
    updates_rollback = updates_sub.add_parser("rollback", help="Rollback a collection to the latest saved pre-update snapshot.")
    updates_rollback.add_argument("collection", help="Collection name to rollback.")
    updates_rollback.add_argument("--dry-run", action="store_true")
    updates_rollback.add_argument("--yes", action="store_true", help="Confirm rollback in non-interactive mode.")
    updates_rollback.add_argument("--skip-reindex", action="store_true")
    updates_rollback.set_defaults(func=cmd_updates_rollback)

    catalog = sub.add_parser("catalog", help="Query the registered hosted adapted-skill catalog and browser.")
    catalog_sub = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_list = catalog_sub.add_parser("list", help="List the hosted adapted-skill catalog for this registered installation.")
    catalog_list.add_argument("--channel", default="", help="Override the pinned release channel for this catalog request.")
    catalog_list.add_argument("--timeout", type=float, default=30.0)
    catalog_list.set_defaults(func=cmd_catalog_list)
    catalog_browse = catalog_sub.add_parser("browse", help="Browse signed reviewed catalog metadata.")
    catalog_browse.add_argument("--channel", default="", choices=["", "stable", "beta", "canary"])
    catalog_browse.add_argument("--source", default="", choices=["", "official", "community", "private-visible"])
    catalog_browse.add_argument("--compatible-agent", default="", choices=["", "codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    catalog_browse.add_argument("--skill-kind", default="")
    catalog_browse.add_argument("--category", default="")
    catalog_browse.add_argument("--include-deprecated", action="store_true")
    catalog_browse.add_argument("--show-quality", action="store_true", help="Include signed quality/evaluation summary fields in browser results.")
    catalog_browse.add_argument("--limit", type=int, default=50)
    catalog_browse.add_argument("--json", action="store_true")
    catalog_browse.add_argument("--timeout", type=float, default=30.0)
    catalog_browse.set_defaults(func=cmd_catalog_browse)
    catalog_search = catalog_sub.add_parser("search", help="Search signed reviewed catalog metadata.")
    catalog_search.add_argument("query")
    catalog_search.add_argument("--channel", default="", choices=["", "stable", "beta", "canary"])
    catalog_search.add_argument("--source", default="", choices=["", "official", "community", "private-visible"])
    catalog_search.add_argument("--compatible-agent", default="", choices=["", "codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    catalog_search.add_argument("--skill-kind", default="")
    catalog_search.add_argument("--category", default="")
    catalog_search.add_argument("--include-deprecated", action="store_true")
    catalog_search.add_argument("--show-quality", action="store_true", help="Include signed quality/evaluation summary fields in search results.")
    catalog_search.add_argument("--limit", type=int, default=20)
    catalog_search.add_argument("--json", action="store_true")
    catalog_search.add_argument("--timeout", type=float, default=30.0)
    catalog_search.set_defaults(func=cmd_catalog_search)
    catalog_filters = catalog_sub.add_parser("filters", help="Show signed catalog browser filter options.")
    catalog_filters.add_argument("--channel", default="", choices=["", "stable", "beta", "canary"])
    catalog_filters.add_argument("--timeout", type=float, default=30.0)
    catalog_filters.set_defaults(func=cmd_catalog_filters)
    catalog_preview = catalog_sub.add_parser("preview", help="Preview signed catalog metadata without skill bodies.")
    catalog_preview.add_argument("item_id")
    catalog_preview.add_argument("--channel", default="", choices=["", "stable", "beta", "canary"])
    catalog_preview.add_argument("--json", action="store_true")
    catalog_preview.add_argument("--timeout", type=float, default=30.0)
    catalog_preview.set_defaults(func=cmd_catalog_preview)
    catalog_recommendation_preview = catalog_sub.add_parser(
        "recommendation-preview",
        help="Build a policy-aware recommendation preview without applying changes.",
    )
    catalog_recommendation_preview.add_argument("item_id", nargs="?", default="")
    catalog_recommendation_preview.add_argument("--fixture-case", default="", help="Use a deterministic recommendation-policy fixture case instead of hosted metadata.")
    catalog_recommendation_preview.add_argument("--agent", default="", choices=["", "codex", "claude-code", "hermes", "openclaw", "vellum-ai"])
    catalog_recommendation_preview.add_argument("--channel", default="", choices=["", "stable", "beta", "canary"])
    catalog_recommendation_preview.add_argument(
        "--strict-supplemental",
        action="store_true",
        help="Fail if supplemental signed quality or improvement metadata cannot be loaded.",
    )
    catalog_recommendation_preview.add_argument("--json", action="store_true")
    catalog_recommendation_preview.add_argument("--timeout", type=float, default=30.0)
    catalog_recommendation_preview.set_defaults(func=cmd_catalog_recommendation_preview)
    catalog_install = catalog_sub.add_parser("install", help="Verify and install a signed approved catalog item.")
    catalog_install.add_argument("item_id")
    catalog_install.add_argument("--collection", default="", help="Override local target collection for delegated community installs.")
    catalog_install.add_argument("--dry-run", action="store_true", help="Verify signed approved metadata without downloading or writing.")
    catalog_install.add_argument("--yes", action="store_true", help="Confirm install in non-interactive mode.")
    catalog_install.add_argument("--skip-reindex", action="store_true")
    catalog_install.add_argument("--json", action="store_true")
    catalog_install.add_argument("--timeout", type=float, default=30.0)
    catalog_install.set_defaults(func=cmd_catalog_install)
    catalog_feedback = catalog_sub.add_parser("feedback", help="Submit explicit redacted feedback for a catalog item.")
    catalog_feedback.add_argument("item_id")
    catalog_feedback.add_argument("--type", required=True, choices=["install_failure", "compatibility_issue", "missing_capability", "documentation_issue", "security_concern"])
    catalog_feedback.add_argument("--severity", default="medium", choices=["low", "medium", "high", "critical"])
    catalog_feedback.add_argument("--title", default="")
    catalog_feedback.add_argument("--agent", default="")
    catalog_feedback.add_argument("--client-version", default="")
    catalog_feedback.add_argument("--core-version", default="")
    catalog_feedback.add_argument("--os", default="")
    catalog_feedback.add_argument("--command", default="")
    catalog_feedback.add_argument("--error-code", default="")
    catalog_feedback.add_argument("--http-status", type=int, default=0)
    catalog_feedback.add_argument("--expected-behavior", default="")
    catalog_feedback.add_argument("--actual-behavior", default="")
    catalog_feedback.add_argument("--reproduction-hint", default="")
    catalog_feedback.add_argument("--dry-run", action="store_true", help="Print the redacted payload without sending it.")
    catalog_feedback.add_argument("--yes", action="store_true", help="Confirm feedback submit in non-interactive mode.")
    catalog_feedback.add_argument("--json", action="store_true")
    catalog_feedback.add_argument("--timeout", type=float, default=30.0)
    catalog_feedback.set_defaults(func=cmd_catalog_feedback)
    catalog_feedback_status = catalog_sub.add_parser("feedback-status", help="Show aggregate feedback status for a catalog item.")
    catalog_feedback_status.add_argument("item_id")
    catalog_feedback_status.add_argument("--limit", type=int, default=100)
    catalog_feedback_status.add_argument("--json", action="store_true")
    catalog_feedback_status.add_argument("--timeout", type=float, default=30.0)
    catalog_feedback_status.set_defaults(func=cmd_catalog_feedback_status)
    catalog_quality = catalog_sub.add_parser("quality", help="Show signed quality status for one catalog item.")
    catalog_quality.add_argument("item_id")
    catalog_quality.add_argument("--json", action="store_true")
    catalog_quality.add_argument("--timeout", type=float, default=30.0)
    catalog_quality.set_defaults(func=cmd_catalog_quality)
    catalog_eval_status = catalog_sub.add_parser("eval-status", help="Show signed evaluation status for one catalog item.")
    catalog_eval_status.add_argument("item_id")
    catalog_eval_status.add_argument("--json", action="store_true")
    catalog_eval_status.add_argument("--timeout", type=float, default=30.0)
    catalog_eval_status.set_defaults(func=cmd_catalog_eval_status)
    catalog_explain_risk = catalog_sub.add_parser("explain-risk", help="Explain signed install-risk warnings for one catalog item.")
    catalog_explain_risk.add_argument("item_id")
    catalog_explain_risk.add_argument("--json", action="store_true")
    catalog_explain_risk.add_argument("--timeout", type=float, default=30.0)
    catalog_explain_risk.set_defaults(func=cmd_catalog_explain_risk)
    catalog_improvement_status = catalog_sub.add_parser("improvement-status", help="Show signed skill improvement and remediation status.")
    catalog_improvement_status.add_argument("item_id")
    catalog_improvement_status.add_argument("--include-queue", action="store_true", help="Include signed maintainer queue status context.")
    catalog_improvement_status.add_argument("--json", action="store_true")
    catalog_improvement_status.add_argument("--timeout", type=float, default=30.0)
    catalog_improvement_status.set_defaults(func=cmd_catalog_improvement_status)
    catalog_maintainer_status = catalog_sub.add_parser("maintainer-status", help="Show signed maintainer queue status for one catalog item.")
    catalog_maintainer_status.add_argument("item_id")
    catalog_maintainer_status.add_argument("--json", action="store_true")
    catalog_maintainer_status.add_argument("--timeout", type=float, default=30.0)
    catalog_maintainer_status.set_defaults(func=cmd_catalog_maintainer_status)
    catalog_maintainer_queue_summary = catalog_sub.add_parser("maintainer-queue-summary", help="Show signed maintainer queue summary counts.")
    catalog_maintainer_queue_summary.add_argument("--json", action="store_true")
    catalog_maintainer_queue_summary.add_argument("--timeout", type=float, default=30.0)
    catalog_maintainer_queue_summary.set_defaults(func=cmd_catalog_maintainer_queue_summary)
    catalog_fixed_pending_eval = catalog_sub.add_parser("fixed-pending-eval", help="Show signed fixed-pending-eval evidence status for one catalog item.")
    catalog_fixed_pending_eval.add_argument("item_id")
    catalog_fixed_pending_eval.add_argument("--json", action="store_true")
    catalog_fixed_pending_eval.add_argument("--timeout", type=float, default=30.0)
    catalog_fixed_pending_eval.set_defaults(func=cmd_catalog_fixed_pending_eval)
    catalog_known_issues = catalog_sub.add_parser("known-issues", help="Show signed known-issue metadata for one catalog item.")
    catalog_known_issues.add_argument("item_id")
    catalog_known_issues.add_argument("--json", action="store_true")
    catalog_known_issues.add_argument("--timeout", type=float, default=30.0)
    catalog_known_issues.set_defaults(func=cmd_catalog_known_issues)
    catalog_update_recommendations = catalog_sub.add_parser("update-recommendations", help="Show preview-only signed update/remove recommendations.")
    catalog_update_recommendations.add_argument("--include-queue", action="store_true", help="Include signed maintainer queue summary and per-item queue status.")
    catalog_update_recommendations.add_argument("--json", action="store_true")
    catalog_update_recommendations.add_argument("--timeout", type=float, default=30.0)
    catalog_update_recommendations.set_defaults(func=cmd_catalog_update_recommendations)
    catalog_update_preview = catalog_sub.add_parser("update-preview", help="Preview a signed update/remove recommendation without applying it.")
    catalog_update_preview.add_argument("item_id")
    catalog_update_preview.add_argument("--json", action="store_true")
    catalog_update_preview.add_argument("--timeout", type=float, default=30.0)
    catalog_update_preview.set_defaults(func=cmd_catalog_update_preview)
    catalog_deprecation_status = catalog_sub.add_parser("deprecation-status", help="Show signed deprecation or retirement status for one catalog item.")
    catalog_deprecation_status.add_argument("item_id")
    catalog_deprecation_status.add_argument("--json", action="store_true")
    catalog_deprecation_status.add_argument("--timeout", type=float, default=30.0)
    catalog_deprecation_status.set_defaults(func=cmd_catalog_deprecation_status)

    release = sub.add_parser("release", help="Inspect and pin hosted registry release channels.")
    release_sub = release.add_subparsers(dest="release_command", required=True)
    release_status = release_sub.add_parser("status", help="Fetch signed release channel status.")
    release_status.add_argument("--channel", default="", help="Temporarily inspect one channel.")
    release_status.add_argument("--json", action="store_true")
    release_status.add_argument("--timeout", type=float, default=30.0)
    release_status.set_defaults(func=cmd_release_status)
    release_pin = release_sub.add_parser("pin", help="Pin this installation to a release channel.")
    release_pin.add_argument("channel", choices=["stable", "beta", "canary"])
    release_pin.set_defaults(func=cmd_release_pin)

    community = sub.add_parser("community", help="Browse, install, submit, and manage registered community skills.")
    community_sub = community.add_subparsers(dest="community_command", required=True)
    community_list = community_sub.add_parser("list", help="List registered community catalog skills.")
    community_list.add_argument("--limit", type=int, default=50)
    community_list.add_argument("--tags", default="", help="Comma-separated tag filter.")
    community_list.add_argument("--channel", default="", choices=["", "canary", "beta", "stable"], help="Filter approved signed community items by release channel.")
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
    community_withdraw = community_sub.add_parser("withdraw", help="Withdraw a pending community submission.")
    community_withdraw.add_argument("submission_id")
    community_withdraw.add_argument("--timeout", type=float, default=30.0)
    community_withdraw.set_defaults(func=cmd_community_withdraw)
    community_review_notes = community_sub.add_parser("review-notes", help="Show maintainer review notes for a community submission.")
    community_review_notes.add_argument("submission_id")
    community_review_notes.add_argument("--timeout", type=float, default=30.0)
    community_review_notes.set_defaults(func=cmd_community_review_notes)
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

    org = sub.add_parser("org", help="Show registered organization and entitlement status.")
    org_sub = org.add_subparsers(dest="org_command", required=True)
    org_status = org_sub.add_parser("status", help="Show cached organization status, or refresh it from the hosted service.")
    org_status.add_argument("--refresh", action="store_true", help="Refresh hosted organization status; requires registration.")
    org_status.add_argument("--json", action="store_true")
    org_status.add_argument("--timeout", type=float, default=30.0)
    org_status.set_defaults(func=cmd_org_status)

    plan = sub.add_parser("plan", help="Inspect registered plan and entitlement status.")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    plan_status = plan_sub.add_parser("status", help="Show cached plan status without hosted calls.")
    plan_status.add_argument("--json", action="store_true")
    plan_status.set_defaults(func=cmd_plan_status)
    plan_refresh = plan_sub.add_parser("refresh", help="Refresh plan status from the registered service.")
    plan_refresh.add_argument("--json", action="store_true")
    plan_refresh.add_argument("--timeout", type=float, default=30.0)
    plan_refresh.set_defaults(func=cmd_plan_refresh)
    plan_explain = plan_sub.add_parser("explain", help="Explain whether the current plan allows a feature.")
    plan_explain.add_argument("feature")
    plan_explain.add_argument("--json", action="store_true")
    plan_explain.set_defaults(func=cmd_plan_explain)
    plan_doctor_parser = plan_sub.add_parser("doctor", help="Run local plan and entitlement diagnostics.")
    plan_doctor_parser.add_argument("--json", action="store_true")
    plan_doctor_parser.set_defaults(func=cmd_plan_doctor)

    billing = sub.add_parser("billing", help="Inspect sandbox billing lifecycle diagnostics.")
    billing_sub = billing.add_subparsers(dest="billing_command", required=True)
    billing_status = billing_sub.add_parser("status", help="Show cached billing lifecycle status without hosted calls.")
    billing_status.add_argument("--json", action="store_true")
    billing_status.set_defaults(func=cmd_billing_status)
    billing_refresh = billing_sub.add_parser("refresh", help="Refresh billing lifecycle status from the registered service.")
    billing_refresh.add_argument("--json", action="store_true")
    billing_refresh.add_argument("--timeout", type=float, default=30.0)
    billing_refresh.set_defaults(func=cmd_billing_refresh)
    billing_doctor_parser = billing_sub.add_parser("doctor", help="Run local billing lifecycle diagnostics.")
    billing_doctor_parser.add_argument("--json", action="store_true")
    billing_doctor_parser.set_defaults(func=cmd_billing_doctor)

    private_packs = sub.add_parser("private-packs", help="Preview, install, sync, and remove registered private team packs.")
    private_packs_sub = private_packs.add_subparsers(dest="private_packs_command", required=True)
    private_packs_list = private_packs_sub.add_parser("list", help="List private team packs authorized for this installation.")
    private_packs_list.add_argument("--json", action="store_true")
    private_packs_list.add_argument("--timeout", type=float, default=30.0)
    private_packs_list.set_defaults(func=cmd_private_packs_list)
    private_packs_preview = private_packs_sub.add_parser("preview", help="Preview redacted private team pack metadata.")
    private_packs_preview.add_argument("pack_id")
    private_packs_preview.add_argument("--json", action="store_true")
    private_packs_preview.add_argument("--timeout", type=float, default=30.0)
    private_packs_preview.set_defaults(func=cmd_private_packs_preview)
    private_packs_install = private_packs_sub.add_parser("install", help="Install one authorized private team pack under registry/private.")
    private_packs_install.add_argument("pack_id")
    private_packs_install.add_argument("--dry-run", action="store_true", help="Verify manifest and show target without downloading or writing.")
    private_packs_install.add_argument("--yes", action="store_true", help="Confirm install in non-interactive mode.")
    private_packs_install.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after install.")
    private_packs_install.add_argument("--json", action="store_true")
    private_packs_install.add_argument("--timeout", type=float, default=30.0)
    private_packs_install.set_defaults(func=cmd_private_packs_install)
    private_packs_sync = private_packs_sub.add_parser("sync", help="Install or update all authorized private team packs.")
    private_packs_sync.add_argument("--dry-run", action="store_true", help="Show planned changes without downloading or writing. This is the default unless --yes is passed.")
    private_packs_sync.add_argument("--yes", action="store_true", help="Apply planned private pack installs and updates.")
    private_packs_sync.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after syncing.")
    private_packs_sync.add_argument("--json", action="store_true")
    private_packs_sync.add_argument("--timeout", type=float, default=30.0)
    private_packs_sync.set_defaults(func=cmd_private_packs_sync)
    private_packs_installed = private_packs_sub.add_parser("installed", help="List locally installed private team packs without hosted calls.")
    private_packs_installed.add_argument("--json", action="store_true")
    private_packs_installed.set_defaults(func=cmd_private_packs_installed)
    private_packs_remove = private_packs_sub.add_parser("remove", help="Remove a locally installed registry-owned private team pack.")
    private_packs_remove.add_argument("pack_id")
    private_packs_remove.add_argument("--dry-run", action="store_true", help="Show what would be removed.")
    private_packs_remove.add_argument("--yes", action="store_true", help="Actually remove without interactive confirmation.")
    private_packs_remove.add_argument("--skip-reindex", action="store_true", help="Do not rebuild the lexical index after removal.")
    private_packs_remove.add_argument("--json", action="store_true")
    private_packs_remove.set_defaults(func=cmd_private_packs_remove)
    private_packs_access_check = private_packs_sub.add_parser("access-check", help="Check this installation's private pack entitlement without downloading the pack.")
    private_packs_access_check.add_argument("pack_id")
    private_packs_access_check.add_argument("--json", action="store_true")
    private_packs_access_check.add_argument("--timeout", type=float, default=30.0)
    private_packs_access_check.set_defaults(func=cmd_private_packs_access_check)
    private_packs_doctor_parser = private_packs_sub.add_parser("doctor", help="Diagnose local private pack setup without downloading skill bodies.")
    private_packs_doctor_parser.add_argument("--json", action="store_true")
    private_packs_doctor_parser.set_defaults(func=cmd_private_packs_doctor)

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
