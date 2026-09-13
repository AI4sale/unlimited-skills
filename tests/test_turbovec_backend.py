from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("turbovec")

from unlimited_skills import cli
from unlimited_skills.vector_backend import VectorIndex, _cached_index, selected_backend
from test_vector_sidecar import write_sidecar


def payload(n=300, dim=384):
    rng = np.random.default_rng(71)
    matrix = rng.normal(size=(n, dim)).astype(np.float32)
    return {"embedding_dimensions": dim, "records": [
        {"name": f"skill-{i:04}", "collection": "a" if i % 2 else "b",
         "description": "fixture", "path": f"/{i}", "embedding": row.tolist()}
        for i, row in enumerate(matrix)]}


def test_real_turbovec_rerank_retains_top_ten():
    data = payload()
    baseline = VectorIndex(data, "numpy")
    turbo = VectorIndex(data)
    for query in np.random.default_rng(25).normal(size=(12, 384)):
        assert [h.name for h in turbo.search(query, 10)] == [h.name for h in baseline.search(query, 10)]
        assert [h.score for h in turbo.search(query, 10)] == pytest.approx(
            [h.score for h in baseline.search(query, 10)], abs=1e-6)


def test_filter_applied_before_shortlist_and_empty_set():
    data = payload(200)
    turbo = VectorIndex(data)
    query = data["records"][1]["embedding"]
    hits = turbo.search(query, 10, "b")
    assert len(hits) == 10 and all(h.collection == "b" for h in hits)
    assert turbo.search(query, 10, "missing") == []


def test_padding_zero_query_and_invalid_query():
    turbo = VectorIndex(payload(20, 3))
    assert turbo.index.dim == 8
    assert turbo.search([0, 0, 0], 5) == []
    assert turbo.search([1, 0, 0], 0) == []
    for query in ([1, 2], [float("nan"), 0, 0], [float("inf"), 0, 0]):
        with pytest.raises(RuntimeError, match="Query embedding"):
            turbo.search(query, 5)


def test_nonfinite_source_fails():
    data = payload(3)
    data["records"][0]["embedding"][0] = float("nan")
    with pytest.raises(RuntimeError, match="non-finite"):
        VectorIndex(data)


def test_persistence_and_concurrent_search(tmp_path):
    from turbovec import IdMapIndex
    turbo = VectorIndex(payload(200))
    query = turbo.vectors[7].tolist()
    expected = turbo.search(query, 10)
    path = tmp_path / "index.tvim"
    turbo.index.write(str(path))
    turbo.index = IdMapIndex.load(str(path))
    assert turbo.search(query, 10) == expected
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(result == expected for result in pool.map(lambda _: turbo.search(query, 10), range(16)))


@pytest.mark.parametrize("backend", ["numpy", "turbovec"])
def test_cli_cache_invalidation_and_collection(tmp_path, monkeypatch, backend):
    write_sidecar(tmp_path)
    monkeypatch.setenv("UNLIMITED_SKILLS_VECTOR_BACKEND", backend)
    monkeypatch.setattr(cli, "embed_texts", lambda *_: [[1, 0, 0]])
    _cached_index.cache_clear()
    assert cli.vector_search(tmp_path, "x", 1, "test-model")[0].name == "security-review"
    assert cli.vector_search(tmp_path, "x", 1, "test-model")[0].name == "security-review"
    assert _cached_index.cache_info().hits == 1
    assert cli.vector_search(tmp_path, "x", 1, "test-model", "unknown") == []
    sidecar = tmp_path / cli.VECTOR_SIDECAR_NAME
    data = json.loads(sidecar.read_text())
    data["records"][0]["embedding"], data["records"][1]["embedding"] = (
        data["records"][1]["embedding"], data["records"][0]["embedding"])
    sidecar.write_text(json.dumps(data))
    assert cli.vector_search(tmp_path, "x", 1, "test-model")[0].name == "design-review"
    with pytest.raises(cli.VectorModelMismatch):
        cli.vector_search(tmp_path, "x", 1, "wrong-model")
    skill = tmp_path / "local/skills/design-review/SKILL.md"
    skill.write_text(skill.read_text() + "changed")
    with pytest.raises(RuntimeError, match="stale_library"):
        cli.vector_search(tmp_path, "x", 1, "test-model")


def test_deleted_record_disappears_after_reindex(tmp_path, monkeypatch):
    write_sidecar(tmp_path)
    monkeypatch.setenv("UNLIMITED_SKILLS_VECTOR_BACKEND", "turbovec")
    monkeypatch.setattr(cli, "embed_texts", lambda *_: [[1, 0.1, 0]])
    assert cli.vector_search(tmp_path, "x", 1, "test-model")[0].name == "security-review"
    (tmp_path / "local/skills/security-review/SKILL.md").unlink()
    for name in (cli.VECTOR_SIDECAR_NAME, cli.VECTOR_META_NAME):
        path = tmp_path / name
        data = json.loads(path.read_text())
        data["count"] = 1
        data["library_generation_hash"] = cli.library_generation_hash(tmp_path)
        if "records" in data:
            data["records"] = data["records"][1:]
        path.write_text(json.dumps(data))
    assert [h.name for h in cli.vector_search(tmp_path, "x", 5, "test-model")] == ["design-review"]


def test_default_and_invalid_configuration(monkeypatch):
    monkeypatch.delenv("UNLIMITED_SKILLS_VECTOR_BACKEND", raising=False)
    assert selected_backend() == "python"
    monkeypatch.setenv("UNLIMITED_SKILLS_VECTOR_BACKEND", "typo")
    with pytest.raises(RuntimeError, match="must be"):
        selected_backend()


def test_trial_probe_rejects_daemon_using_another_backend(tmp_path, monkeypatch):
    from unlimited_skills import suggest
    from unlimited_skills.daemon_endpoint import RUNTIME_CONTRACT_VERSION
    from io import BytesIO
    monkeypatch.setenv("UNLIMITED_SKILLS_VECTOR_BACKEND", "turbovec")
    monkeypatch.setattr(suggest, "warm_daemon_urls", lambda *_: ["http://127.0.0.1:19999"])
    calls = []
    def respond(request, timeout):
        calls.append(request)
        return BytesIO(json.dumps({"ok": True, "service": "unlimited-skills",
            "protocol": "warm-search-v1", "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
            "root": str(tmp_path), "model": cli.DEFAULT_EMBED_MODEL, "vector_backend": "python"}).encode())
    monkeypatch.setattr(suggest.urllib.request, "urlopen", respond)
    assert suggest._warm_daemon_vector_probe(tmp_path, "query", 3) == []
    assert calls == ["http://127.0.0.1:19999/health"]
