from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills import cli


def write_sidecar(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in ("security-review", "design-review"):
        skill = root / "local" / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(f"---\nname: {name}\ndescription: fixture\n---\n", encoding="utf-8")
    generation = cli.library_generation_hash(root)
    (root / cli.VECTOR_SIDECAR_NAME).write_text(
        json.dumps(
            {
                "schema_version": 2,
                "collection": cli.CHROMA_COLLECTION,
                "model": "test-model",
                "count": 2,
                "embedding_dimensions": 3,
                "library_generation_hash": generation,
                "complete": True,
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
    (root / cli.VECTOR_META_NAME).write_text(
        json.dumps(
            {
                "schema_version": 2,
                "collection": cli.CHROMA_COLLECTION,
                "model": "test-model",
                "count": 2,
                "embedding_dimensions": 3,
                "library_generation_hash": generation,
                "complete": True,
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


def test_vector_search_rejects_non_numeric_sidecar_metadata(tmp_path: Path) -> None:
    write_sidecar(tmp_path)
    sidecar = json.loads((tmp_path / cli.VECTOR_SIDECAR_NAME).read_text(encoding="utf-8"))
    sidecar["embedding_dimensions"] = "not-a-number"
    (tmp_path / cli.VECTOR_SIDECAR_NAME).write_text(json.dumps(sidecar), encoding="utf-8")

    with pytest.raises(RuntimeError, match="metadata is invalid"):
        cli.vector_search(tmp_path, "security auth", 1, "test-model")


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


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda root: (root / cli.VECTOR_META_NAME).write_text("{bad json", encoding="utf-8"), "invalid_json"),
        (
            lambda root: (root / cli.VECTOR_META_NAME).write_text(
                json.dumps({"schema_version": 2, "model": "wrong", "count": 2, "embedding_dimensions": 3, "library_generation_hash": cli.library_generation_hash(root), "complete": True}),
                encoding="utf-8",
            ),
            "model_mismatch",
        ),
        (
            lambda root: (root / "local" / "skills" / "new-skill" / "SKILL.md").parent.mkdir(parents=True)
            or (root / "local" / "skills" / "new-skill" / "SKILL.md").write_text("---\nname: new-skill\n---\n", encoding="utf-8"),
            "stale_library",
        ),
    ],
)
def test_vector_sidecar_status_rejects_corrupt_wrong_model_and_stale_library(
    tmp_path: Path, mutation, reason: str
) -> None:
    write_sidecar(tmp_path)
    mutation(tmp_path)
    status = cli.vector_sidecar_status(tmp_path, cli.vector_sidecar_path(tmp_path), "test-model")
    assert status["ready"] is False
    assert status["reason"] == reason


def test_chroma_fallback_closes_client_when_collection_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class MissingCollectionClient:
        closed = False

        def get_collection(self, _name: str):
            raise RuntimeError("missing")

        def close(self) -> None:
            self.closed = True

    client = MissingCollectionClient()
    monkeypatch.setattr(cli, "chroma_client", lambda _root: client)

    with pytest.raises(RuntimeError, match="Vector index is not ready"):
        cli.vector_search(tmp_path, "security auth", 1, "test-model")

    assert client.closed is True


def test_chroma_fallback_closes_client_after_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Collection:
        def query(self, **_kwargs):
            return {
                "metadatas": [[{"name": "security-review", "description": "", "collection": "ecc", "path": ""}]],
                "distances": [[0.2]],
            }

    class Client:
        closed = False

        def get_collection(self, _name: str):
            return Collection()

        def close(self) -> None:
            self.closed = True

    client = Client()
    monkeypatch.setattr(cli, "chroma_client", lambda _root: client)
    monkeypatch.setattr(cli, "embed_texts", lambda _texts, _model: [[0.1, 0.2]])

    hits = cli.vector_search(tmp_path, "security auth", 1, "test-model")

    assert [hit.name for hit in hits] == ["security-review"]
    assert client.closed is True
