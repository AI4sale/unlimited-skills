"""Language-aware routing for the `suggest` probe (non-English rescue).

Regression guard for the production bug where a non-English (e.g. Russian)
prompt fed straight into the ASCII lexical tokenizer produced an empty query
and therefore zero retrieval. The probe must now:

  1. use cheap lexical retrieval for English;
  2. on a non-English / lexical-empty query, route to the local multilingual
     embedding sidecar when one is installed;
  3. otherwise signal the caller (``needs_english_query``) to re-query with
     English keywords instead of returning silent garbage.
"""
from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills import suggest as suggest_mod
from unlimited_skills.search_core import SkillHit, save_index


def _english_library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    skill = root / "local" / "skills" / "security-review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: security-review\ndescription: Review code for security "
        "vulnerabilities, authentication, injection, and secrets.\n---\n\n# security-review\n",
        encoding="utf-8",
    )
    for index in range(8):
        decoy = root / "local" / "skills" / f"decoy-{index}" / "SKILL.md"
        decoy.parent.mkdir(parents=True)
        decoy.write_text(
            f"---\nname: decoy-{index}\ndescription: Unrelated fixture topic {index}.\n---\n",
            encoding="utf-8",
        )
    save_index(root)
    return root


def _run(argv: list[str], capsys) -> dict | None:
    # retrieval_path / needs_english_query ride the --card channel (the hook's mode).
    rc = suggest_mod.main(argv + ["--card"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


def _mark_sidecar_ready(root: Path) -> None:
    from unlimited_skills import cli

    records = [
        {
            "name": hit.name,
            "description": hit.description,
            "collection": hit.collection,
            "path": hit.path,
            "embedding": [0.0, 1.0],
        }
        for hit, _body in cli.load_records(root)
    ]
    cli.vector_sidecar_path(root).write_text(
        json.dumps(
            {
                "schema_version": 2,
                "model": cli.DEFAULT_EMBED_MODEL,
                "count": len(records),
                "embedding_dimensions": 2,
                "library_generation_hash": cli.library_generation_hash(root),
                "complete": True,
                "records": records,
            }
        ),
        encoding="utf-8",
    )
    cli.vector_meta_path(root).write_text(
        json.dumps(
            {
                "schema_version": 2,
                "model": cli.DEFAULT_EMBED_MODEL,
                "count": sum(1 for _ in root.rglob("SKILL.md")),
                "embedding_dimensions": 2,
                "library_generation_hash": cli.library_generation_hash(root),
                "complete": True,
            }
        ),
        encoding="utf-8",
    )


RU = "проверь безопасность кода и найди уязвимости в аутентификации"
EN = "review code for security vulnerabilities and authentication"


def test_looks_english_detects_language() -> None:
    le = suggest_mod.looks_english
    assert le(EN) is True
    assert le(RU) is False
    assert le("") is True               # nothing to translate → lexical path
    assert le("1234 !!! --- ") is True  # no letters → lexical path
    assert le("review the react component для рендера") is True  # latin-dominant


def test_english_no_match_does_not_flag_needs_english(tmp_path: Path, capsys) -> None:
    root = _english_library(tmp_path)
    payload = _run(["what is the weather in sydney tomorrow", "--root", str(root), "--json"], capsys)
    assert payload["retrieval_path"] == "none"
    assert "needs_english_query" not in payload  # English: stay silent, do not nag


def test_non_english_without_sidecar_flags_needs_english(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _english_library(tmp_path)  # no vector sidecar created
    monkeypatch.setenv("UNLIMITED_SKILLS_NO_VECTOR_FALLBACK", "1")
    payload = _run([RU, "--root", str(root), "--json"], capsys)
    assert payload["needs_english_query"] is True
    assert payload["retrieval_path"] == "none"
    assert payload["top_3_skill_candidates"] == []


def test_mixed_language_weak_lexical_hit_still_requests_english_rescue(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    root = _english_library(tmp_path)
    monkeypatch.setenv("UNLIMITED_SKILLS_NO_VECTOR_FALLBACK", "1")
    query = "проверить security api"
    payload = _run([query, "--root", str(root), "--json"], capsys)
    assert payload["reason_code"] == "low_confidence_candidates"
    assert payload["top_3_skill_candidates"]
    assert payload["needs_english_query"] is True
    assert payload["delivery_tier"] == suggest_mod.TIER_HINT
    assert payload["delivery"]["mode"] == "hint"


def test_non_english_routes_to_vector_when_sidecar_present(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _english_library(tmp_path)
    from unlimited_skills import cli

    _mark_sidecar_ready(root)
    hit = SkillHit(
        name="security-review",
        description="Review code for security issues.",
        collection="local",
        path=str(root / "local" / "skills" / "security-review" / "SKILL.md"),
        score=0.71,
    )
    called: dict = {}

    def fake_vector(r, q, limit, collection_name=None):
        called["q"] = q
        return [hit]

    monkeypatch.setattr(suggest_mod, "vector_probe", fake_vector)
    payload = _run([RU, "--root", str(root), "--json"], capsys)
    assert called.get("q"), "vector_search must run for a non-English prompt when a sidecar exists"
    assert payload["retrieval_path"] == "vector"
    assert payload["top_3_skill_candidates"][0]["name"] == "security-review"
    assert "needs_english_query" not in payload


def test_english_query_never_calls_vector(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _english_library(tmp_path)
    _mark_sidecar_ready(root)

    def boom(*args, **kwargs):
        raise AssertionError("vector_search must not run for an English prompt")

    monkeypatch.setattr(suggest_mod, "vector_probe", boom)
    payload = _run([EN, "--root", str(root), "--json"], capsys)
    assert payload["retrieval_path"] == "lexical"
    assert payload["top_3_skill_candidates"][0]["name"] == "security-review"


def test_above_floor_hint_query_never_calls_vector(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _english_library(tmp_path)
    _mark_sidecar_ready(root)

    def boom(*args, **kwargs):
        raise AssertionError("above-floor lexical hints must stay on the fast path")

    monkeypatch.setattr(suggest_mod, "vector_probe", boom)
    payload = _run(
        [
            "security review",
            "--root",
            str(root),
            "--json",
            "--high-threshold",
            "100",
        ],
        capsys,
    )
    assert payload["reason_code"] == suggest_mod.REASON_MATCH_FOUND
    assert payload["delivery_tier"] == suggest_mod.TIER_HINT
    assert payload["vector_status"] == "not_requested"


def test_exact_skill_identity_skips_vector_even_when_sidecar_is_ready(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    root = _english_library(tmp_path)
    _mark_sidecar_ready(root)

    def boom(*args, **kwargs):
        raise AssertionError("exact identity must not spend the vector budget")

    monkeypatch.setattr(suggest_mod, "vector_probe", boom)
    payload = _run(
        ["use security review for this module", "--root", str(root), "--json"], capsys
    )
    assert payload["delivery_candidates"][0]["name"] == "security-review"
    assert payload["vector_status"] == "not_requested"


def test_vector_probe_rejects_an_incompatible_local_daemon(
    tmp_path: Path, monkeypatch
) -> None:
    root = _english_library(tmp_path)
    _mark_sidecar_ready(root)
    calls: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "ok": True,
                    "service": "not-unlimited-skills",
                    "protocol": "warm-search-v1",
                    "root": str(root),
                    "model": suggest_mod.DEFAULT_EMBED_MODEL,
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append(str(request))
        return Response()

    monkeypatch.setattr(suggest_mod.urllib.request, "urlopen", fake_urlopen)
    assert suggest_mod.vector_probe(root, "semantic query", 3) == []
    assert len(calls) == 2  # preferred + versioned fallback health; never /search


def test_vector_probe_rejects_sidecar_payload_that_disagrees_with_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    root = _english_library(tmp_path)
    from unlimited_skills import cli

    _mark_sidecar_ready(root)
    payload = {
        "schema_version": 2,
        "model": "wrong-model",
        "count": 1,
        "embedding_dimensions": 2,
        "library_generation_hash": cli.library_generation_hash(root),
        "complete": True,
        "query_embeddings": {suggest_mod.task_summary_hash("semantic query"): [1.0, 0.0]},
        "records": [
            {
                "name": "security-review",
                "description": "fixture",
                "collection": "local",
                "path": "unused",
                "embedding": [1.0, 0.0],
            }
        ],
    }
    cli.vector_sidecar_path(root).write_text(json.dumps(payload), encoding="utf-8")

    def boom(*args, **kwargs):
        raise AssertionError("incompatible sidecar must be rejected before daemon I/O")

    monkeypatch.setattr(suggest_mod.urllib.request, "urlopen", boom)
    assert suggest_mod.vector_probe(root, "semantic query", 3) == []
