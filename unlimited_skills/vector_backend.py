"""Opt-in, process-local acceleration for the authoritative JSON sidecar.

The compressed index selects candidates; original float32 vectors rerank them
so downstream cosine thresholds retain their meaning. No sidecar is rewritten.
"""
from __future__ import annotations

import os
import threading
from functools import lru_cache
from pathlib import Path


def selected_backend() -> str:
    backend = os.environ.get("UNLIMITED_SKILLS_VECTOR_BACKEND", "python").strip().lower()
    if backend not in {"python", "numpy", "turbovec"}:
        raise RuntimeError("UNLIMITED_SKILLS_VECTOR_BACKEND must be python, numpy or turbovec")
    return backend


class VectorIndex:
    """Immutable snapshot, with collection filtering before candidate selection."""

    def __init__(self, payload: dict, backend: str = "turbovec") -> None:
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("Install acceleration with pip install 'unlimited-skills[turbovec]'") from exc
        self.backend = backend
        self.dim = int(payload["embedding_dimensions"])
        records = payload["records"]
        self.records = [{k: v for k, v in row.items() if k != "embedding"} for row in records]
        self.query_embeddings = payload.get("query_embeddings", {})
        self.vectors = np.asarray([row["embedding"] for row in records], dtype=np.float32).reshape(-1, self.dim)
        if not np.isfinite(self.vectors).all():
            raise RuntimeError("Vector sidecar contains non-finite coordinates")
        norms = np.linalg.norm(self.vectors, axis=1, keepdims=True)
        if not np.isfinite(norms).all():
            raise RuntimeError("Vector sidecar coordinates exceed the supported numeric range")
        self.vectors = np.ascontiguousarray(self.vectors / np.where(norms > 0, norms, 1))
        self.index = None
        self._search_lock = threading.Lock()
        if backend == "turbovec":
            try:
                from turbovec import IdMapIndex
            except ImportError as exc:
                raise RuntimeError("Install acceleration with pip install 'unlimited-skills[turbovec]'") from exc
            # TurboQuant requires dimensions divisible by eight. Zero padding
            # preserves cosine and lets existing low-dimensional fixtures work.
            padded_dim = (self.dim + 7) // 8 * 8
            if padded_dim > 16384:
                raise RuntimeError("turbovec supports at most 16384 dimensions")
            self.index = IdMapIndex(dim=padded_dim, bit_width=4)
            if records:
                matrix = np.pad(self.vectors, ((0, 0), (0, padded_dim - self.dim)))
                self.index.add_with_ids(matrix, np.arange(len(records), dtype=np.uint64))
                self.index.prepare()

    def search(self, query: list[float], limit: int, collection: str | None = None):
        import numpy as np
        from .search_core import SkillHit

        if limit <= 0 or not self.records:
            return []
        vector = np.asarray(query, dtype=np.float32)
        if vector.shape != (self.dim,) or not np.isfinite(vector).all():
            raise RuntimeError("Query embedding has invalid dimensions or non-finite coordinates")
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm):
            raise RuntimeError("Query embedding exceeds the supported numeric range")
        if not norm:
            return []
        vector = vector / norm
        allowed = np.asarray([i for i, row in enumerate(self.records)
                              if not collection or row.get("collection", "") == collection], dtype=np.uint64)
        if not len(allowed):
            return []
        candidates = allowed
        if self.index is not None:
            padded = np.pad(vector, (0, self.index.dim - self.dim)).reshape(1, -1)
            # Rerank enough candidates to protect top-k quality from 4-bit noise.
            candidate_count = min(len(allowed), max(64, limit * 4))
            with self._search_lock:
                _, ids = self.index.search(padded, k=candidate_count, allowlist=allowed)
            candidates = ids[0]
        scores = self.vectors[candidates.astype(np.intp)] @ vector
        hits = []
        for idx, score in zip(candidates, scores):
            if score <= 0:
                continue
            row = self.records[int(idx)]
            hits.append(SkillHit(name=str(row.get("name") or ""),
                                 description=str(row.get("description") or ""),
                                 collection=str(row.get("collection") or ""),
                                 path=str(row.get("path") or ""), score=float(score)))
        hits.sort(key=lambda hit: (-hit.score, hit.collection, hit.name))
        return hits[:limit]


def _file_identity(path: Path) -> tuple:
    info = path.stat()
    return str(path.resolve()), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@lru_cache(maxsize=2)
def _cached_index(root: str, model: str, backend: str, identity: tuple) -> VectorIndex:
    from .cli import load_vector_sidecar_payload, vector_meta_path, vector_sidecar_path
    path = Path(root)
    payload = load_vector_sidecar_payload(path, model)
    if payload is None:
        raise RuntimeError("Vector sidecar is missing; run unlimited-skills vector-reindex")
    index = VectorIndex(payload, backend)
    if identity != (_file_identity(vector_sidecar_path(path)), _file_identity(vector_meta_path(path))):
        raise RuntimeError("Vector sidecar changed while loading; retry the search")
    return index


def accelerated_search(root: Path, query: str, limit: int, model: str,
                       collection: str | None, backend: str):
    from .cli import (embed_texts, load_vector_sidecar_payload, task_summary_hash,
                      vector_meta_path, vector_sidecar_path, vector_sidecar_status)
    path = vector_sidecar_path(root)
    # Freshness and model checks remain mandatory even on cache hits.
    if not vector_sidecar_status(root, path, model).get("ready"):
        load_vector_sidecar_payload(root, model)  # retain the existing precise errors
        raise RuntimeError("Vector sidecar is missing; run unlimited-skills vector-reindex")
    identity = (_file_identity(path), _file_identity(vector_meta_path(root)))
    index = _cached_index(str(root.resolve()), model, backend, identity)
    embedding = None
    if isinstance(index.query_embeddings, dict):
        for key in (task_summary_hash(query), " ".join(query.split()).lower(), query):
            if isinstance(index.query_embeddings.get(key), list):
                embedding = index.query_embeddings[key]
                break
    if embedding is None:
        embedding = embed_texts([query], model)[0]
    return index.search(embedding, limit, collection)
