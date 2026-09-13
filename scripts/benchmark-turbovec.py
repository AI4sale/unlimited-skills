"""Compare identical embeddings locally. Published output contains aggregates only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from unlimited_skills import cli
from unlimited_skills.vector_backend import VectorIndex
from unlimited_skills.search_core import _deduplicated_skill_count


def metrics(values):
    return {"p50_ms": round(float(np.percentile(values, 50)), 3),
            "p95_ms": round(float(np.percentile(values, 95)), 3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--e2e", action="store_true")
    parser.add_argument("--reuse-baseline", type=Path, help="Reuse an earlier timing baseline; recompute exact reference rankings")
    args = parser.parse_args()
    query_path = Path(__file__).resolve().parents[1] / "evals/turbovec-queries.tsv"
    pairs = list(csv.DictReader(query_path.read_text(encoding="utf-8").splitlines(), delimiter="\t"))
    queries = [(lang, row[lang]) for row in pairs for lang in ("en", "ru")]
    model = cli.DEFAULT_EMBED_MODEL
    payload = cli.load_vector_sidecar_payload(args.root, model)
    cache_key = hashlib.sha256((model + query_path.read_text(encoding="utf-8")).encode()).hexdigest()
    if args.cache.exists():
        cache = json.loads(args.cache.read_text(encoding="utf-8"))
        if cache["key"] != cache_key:
            raise RuntimeError("Embedding cache does not match model and query set")
        embeddings = cache["embeddings"]
    else:
        from fastembed import TextEmbedding
        encoder = TextEmbedding(model_name=model, threads=2)
        embeddings = [row.tolist() for row in encoder.embed([q for _, q in queries])]
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        args.cache.write_text(json.dumps({"key": cache_key, "embeddings": embeddings}), encoding="utf-8")
    original_embed = cli.embed_texts
    query_map = dict(zip([q for _, q in queries], embeddings))
    cli.embed_texts = lambda texts, _: [query_map[q] for q in texts]
    result = {"schema_version": 1, "python": platform.python_version(), "platform": platform.system(),
              "model": model, "corpus_count": len(payload["records"]), "dimensions": payload["embedding_dimensions"],
              "query_count": len(queries), "queries_per_language": len(pairs),
              "query_kind": "authored representative queries, not production log replay",
              "quality_metric": "top10 agreement with exact cosine; not human relevance recall",
              "backend_ms_excludes": "query embedding, HTTP transport and generation",
              "results": {}, "kernel": {}}
    indexes = {name: VectorIndex(payload, name) for name in ("numpy", "turbovec")}
    references = {}
    backends = ("python", "numpy", "turbovec")
    if args.reuse_baseline:
        previous = json.loads(args.reuse_baseline.read_text(encoding="utf-8"))
        for field in ("model", "corpus_count", "dimensions", "query_count"):
            if previous[field] != result[field]:
                raise RuntimeError("Baseline metadata mismatch: " + field)
        result["results"]["python"] = previous["results"]["python"]
        result["baseline_timings_reused"] = True
        backends = ("numpy", "turbovec")
        for (_, query), embedding in zip(queries, embeddings):
            scores = [(cli.cosine_similarity(embedding, row["embedding"]), row)
                      for row in payload["records"]]
            scores.sort(key=lambda item: (-item[0], item[1]["collection"], item[1]["name"]))
            references[query] = [row["name"] for score, row in scores if score > 0][:10]
    for name in backends:
        os.environ["UNLIMITED_SKILLS_VECTOR_BACKEND"] = name
        cli.vector_search(args.root, queries[0][1], 10, model)
        timings, agreement, top1 = [], [], []
        language_agreement = {"en": [], "ru": []}
        for (lang, query), embedding in zip(queries, embeddings):
            if name == "python":
                # Match the pre-trial installed path, which reparses shadowed
                # skill identities each time. No such cache existed there.
                _deduplicated_skill_count.cache_clear()
            started = time.perf_counter()
            hits = cli.vector_search(args.root, query, 10, model)
            timings.append((time.perf_counter() - started) * 1000)
            names = [h.name for h in hits]
            if name == "python":
                references[query] = names
            ref = references[query]
            overlap = len(set(names) & set(ref)) / max(1, len(ref))
            agreement.append(overlap)
            language_agreement[lang].append(overlap)
            top1.append(names[:1] == ref[:1])
        result["results"][name] = {**metrics(timings), "top10_agreement": float(np.mean(agreement)),
                                  "top1_agreement": float(np.mean(top1)),
                                  "by_language": {k: float(np.mean(v)) for k, v in language_agreement.items()}}
        print(name, result["results"][name], flush=True)
    for name, index in indexes.items():
        timings = []
        for _ in range(3):
            for embedding in embeddings:
                started = time.perf_counter()
                index.search(embedding, 10)
                timings.append((time.perf_counter() - started) * 1000)
        result["kernel"][name] = metrics(timings)
    turbo = indexes["turbovec"]
    result["storage"] = {"float32_vectors_bytes": turbo.vectors.nbytes,
                         "compressed_serialized_bytes": len(turbo.index.to_bytes()),
                         "trial_retains_float32_for_rerank": True,
                         "note": "These are vector payload sizes, not process RAM; quantizer runtime overhead is additional."}
    if args.e2e:
        cli.embed_texts = original_embed
        # Same warmed encoder for all engines. Query generation is timed here.
        cli.embed_texts([queries[0][1]], model)
        result["e2e_local_ms"] = {}
        if args.reuse_baseline and "e2e_local_ms" in previous:
            result["e2e_local_ms"]["python"] = previous["e2e_local_ms"]["python"]
        for name in backends:
            os.environ["UNLIMITED_SKILLS_VECTOR_BACKEND"] = name
            timings = []
            for _, query in queries[:20]:
                if name == "python":
                    _deduplicated_skill_count.cache_clear()
                started = time.perf_counter()
                cli.vector_search(args.root, query, 10, model)
                timings.append((time.perf_counter() - started) * 1000)
            result["e2e_local_ms"][name] = metrics(timings)
            print("e2e", name, result["e2e_local_ms"][name], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
