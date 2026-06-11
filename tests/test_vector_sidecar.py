from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills import cli


def write_sidecar(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / cli.VECTOR_SIDECAR_NAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "collection": cli.CHROMA_COLLECTION,
                "model": "test-model",
                "count": 2,
                "records": [
                    {
                        "name": "security-review",
                        "description": "Review code for auth and secrets risks.",
                        "collection": "local",
                        "path": str(root / "local" / "security-review" / "SKILL.md"),
                        "embedding": [1.0, 0.0, 0.0],
                    },
                    {
                        "name": "design-review",
                        "description": "Review UI layout.",
                        "collection": "local",
                        "path": str(root / "local" / "design-review" / "SKILL.md"),
                        "embedding": [0.0, 1.0, 0.0],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_vector_search_uses_sidecar_without_chroma(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_sidecar(tmp_path)

    def fail_chroma(root: Path):
        raise AssertionError("Chroma should not be initialized when sidecar is present.")

    monkeypatch.setattr(cli, "chroma_client", fail_chroma)
    monkeypatch.setattr(cli, "embed_texts", lambda texts, model: [[0.95, 0.05, 0.0]])

    hits = cli.vector_search(tmp_path, "security auth", 1, "test-model")

    assert [hit.name for hit in hits] == ["security-review"]
    assert hits[0].score > 0.9


def test_vector_search_sidecar_filters_collection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_sidecar(tmp_path)
    monkeypatch.setattr(cli, "embed_texts", lambda texts, model: [[0.95, 0.05, 0.0]])

    assert cli.vector_search(tmp_path, "security auth", 1, "test-model", collection_name="missing") == []


def test_vector_search_sidecar_model_mismatch_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_sidecar(tmp_path)

    def fail_chroma(root: Path):
        raise AssertionError("Chroma must not be consulted when the sidecar model mismatches.")

    monkeypatch.setattr(cli, "chroma_client", fail_chroma)

    with pytest.raises(cli.VectorModelMismatch, match="'test-model'.*'other-model'"):
        cli.vector_search(tmp_path, "security auth", 1, "other-model")


def test_vector_search_chroma_meta_model_mismatch_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / cli.VECTOR_META_NAME).write_text(
        json.dumps({"collection": cli.CHROMA_COLLECTION, "model": "old-model", "count": 1}),
        encoding="utf-8",
    )

    def fail_chroma(root: Path):
        raise AssertionError("Chroma must not be consulted when the meta model mismatches.")

    monkeypatch.setattr(cli, "chroma_client", fail_chroma)

    with pytest.raises(cli.VectorModelMismatch, match="'old-model'.*'new-model'"):
        cli.vector_search(tmp_path, "security auth", 1, "new-model")


def test_hybrid_search_degrades_loudly_on_model_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    write_sidecar(tmp_path)

    hits = cli.hybrid_search(tmp_path, "security auth", 5, "other-model")

    assert "vector search skipped" in capsys.readouterr().err
    assert all(hit.score >= 0 for hit in hits)


def test_hybrid_search_require_vector_raises_on_model_mismatch(tmp_path: Path) -> None:
    write_sidecar(tmp_path)

    with pytest.raises(cli.VectorModelMismatch):
        cli.hybrid_search(tmp_path, "security auth", 5, "other-model", require_vector=True)


def test_embed_texts_reuses_model_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []

    class FakeEmbedding:
        def __init__(self, model_name: str) -> None:
            created.append(model_name)

        def embed(self, texts: list[str]):
            for _text in texts:
                yield [1.0, 0.0]

    cli.embedding_model.cache_clear()
    monkeypatch.setattr(cli, "ensure_embedding_deps", lambda: FakeEmbedding)

    assert cli.embed_texts(["one"], "fake-model") == [[1.0, 0.0]]
    assert cli.embed_texts(["two"], "fake-model") == [[1.0, 0.0]]
    assert created == ["fake-model"]
    cli.embedding_model.cache_clear()
