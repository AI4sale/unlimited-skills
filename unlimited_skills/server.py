from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from . import __version__
from .daemon_endpoint import RUNTIME_CONTRACT_VERSION
from .cli import (
    DEFAULT_EMBED_MODEL,
    DEFAULT_ROOT,
    atomic_write_text,
    embed_texts,
    find_by_name,
    hybrid_search,
    lexical_search,
    library_generation_hash,
    load_records,
    log_event,
    read_text,
    vector_search,
    vector_sidecar_path,
    vector_meta_path,
    vector_sidecar_status,
    vector_text,
)


ROOT = Path(os.environ.get("UNLIMITED_SKILLS_ROOT", str(DEFAULT_ROOT))).expanduser()
MODEL = os.environ.get("UNLIMITED_SKILLS_EMBED_MODEL", DEFAULT_EMBED_MODEL)
app = FastAPI(title="Unlimited Skills", version=__version__)


class SearchRequest(BaseModel):
    query: str
    mode: Literal["hybrid", "lexical", "vector"] = "hybrid"
    limit: int = Field(default=10, ge=1, le=50)
    collection: str | None = None
    require_vector: bool = False


class FeedbackRequest(BaseModel):
    name: str
    query: str = ""
    verdict: Literal["accepted", "rejected", "neutral"]
    notes: str = ""


class UseRequest(BaseModel):
    name: str
    query: str = ""
    task: str = ""


@app.on_event("startup")
def warm_start() -> None:
    try:
        status = vector_sidecar_status(ROOT, vector_sidecar_path(ROOT), MODEL)
        if not status.get("ready"):
            records = load_records(ROOT)
            sidecar_records: list[dict] = []
            dimensions = 0
            for start in range(0, len(records), 32):
                batch = records[start : start + 32]
                embeddings = embed_texts([vector_text(hit, body) for hit, body in batch], MODEL)
                for (hit, _body), embedding in zip(batch, embeddings):
                    dimensions = len(embedding)
                    sidecar_records.append(
                        {
                            "name": hit.name,
                            "description": hit.description,
                            "collection": hit.collection,
                            "path": hit.path,
                            "embedding": [round(float(value), 8) for value in embedding],
                        }
                    )
            generation = library_generation_hash(ROOT)
            common = {
                "schema_version": 2,
                "model": MODEL,
                "count": len(sidecar_records),
                "embedding_dimensions": dimensions,
                "library_generation_hash": generation,
                "complete": True,
            }
            atomic_write_text(
                vector_sidecar_path(ROOT),
                json.dumps({**common, "records": sidecar_records}, ensure_ascii=False),
            )
            atomic_write_text(vector_meta_path(ROOT), json.dumps(common, ensure_ascii=False))
        vector_search(ROOT, "__warm_start__", 1, MODEL)
    except Exception:
        pass


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "unlimited-skills",
        "protocol": "warm-search-v1",
        "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
        "package_version": __version__,
        "root": str(ROOT),
        "model": MODEL,
    }


@app.post("/search")
def search(request: SearchRequest) -> dict:
    if request.mode == "lexical":
        hits = lexical_search(ROOT, request.query, request.limit, request.collection)
    elif request.mode == "vector":
        hits = vector_search(ROOT, request.query, request.limit, MODEL, request.collection)
    else:
        hits = hybrid_search(ROOT, request.query, request.limit, MODEL, request.collection, require_vector=request.require_vector)
    log_event(ROOT, "daemon_search", {"query": request.query, "mode": request.mode, "hits": [asdict(hit) for hit in hits[:5]]})
    return {"hits": [asdict(hit) for hit in hits]}


@app.get("/skills/{name}")
def skill(name: str) -> dict:
    path = find_by_name(ROOT, name)
    if not path:
        return {"found": False, "name": name}
    log_event(ROOT, "daemon_view", {"name": name, "path": str(path)})
    return {"found": True, "name": name, "path": str(path), "body": read_text(path)}


@app.post("/use")
def use(request: UseRequest) -> dict:
    path = find_by_name(ROOT, request.name)
    payload = {"name": request.name, "query": request.query, "task": request.task, "path": str(path) if path else ""}
    log_event(ROOT, "daemon_skill_used", payload)
    return payload


@app.post("/feedback")
def feedback(request: FeedbackRequest) -> dict:
    payload = request.dict()
    log_event(ROOT, "daemon_feedback", payload)
    return payload
