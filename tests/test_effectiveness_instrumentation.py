"""A3.1.1 effectiveness v2 instrumentation: buckets, session correlation,
env-gated event stamping, suggest enrichment, and the suggest->view->use funnel.

Privacy is the load-bearing invariant: only a short hash of the session id is
ever written, never the raw id, the query text, skill bodies, or paths.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from unlimited_skills import cli as _cli
from unlimited_skills import suggest
from unlimited_skills.commands.library import compute_event_metrics
from unlimited_skills.search_core import (
    EVENT_LOG,
    SESSION_ID_ENV,
    SESSION_ID_FALLBACK_ENV,
    SESSION_SALT_ENV,
    _run_correlation_id,
    hash_session_id,
    log_event,
    margin_bucket,
    save_index,
    score_bucket,
    session_correlation_id,
)


def write_skill(root: Path, name: str, description: str, body: str = "") -> None:
    skill_dir = root / "local" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    write_skill(root, "python-patterns", "Pythonic idioms, PEP 8 standards, and code review best practices for Python.")
    write_skill(root, "gardening-basics", "Watering schedules for houseplants.")
    save_index(root)
    return root


# --- buckets -------------------------------------------------------------

def test_score_bucket_boundaries() -> None:
    assert score_bucket(None) == "none"
    assert score_bucket(0) == "below_floor"
    assert score_bucket(11.9) == "below_floor"
    assert score_bucket(12) == "low"
    assert score_bucket(17.9) == "low"
    assert score_bucket(18) == "medium"
    assert score_bucket(24.9) == "medium"
    assert score_bucket(25) == "high"
    assert score_bucket(39.9) == "high"
    assert score_bucket(40) == "very_high"


def test_margin_bucket_boundaries() -> None:
    assert margin_bucket(30, None) == "no_runner_up"
    assert margin_bucket(30, 0) == "no_runner_up"
    assert margin_bucket(10, 10) == "contested"   # ratio 1.0
    assert margin_bucket(10.9, 10) == "contested"  # 1.09
    assert margin_bucket(12, 10) == "slim"   # 1.2
    assert margin_bucket(18, 10) == "clear"  # 1.8
    assert margin_bucket(20, 10) == "strong"  # 2.0
    assert margin_bucket(29, 10) == "strong"  # 2.9
    assert margin_bucket(30, 10) == "dominant"  # 3.0


# --- session correlation: short hash, never the raw id -------------------

def test_hash_session_id_is_short_salted_and_not_reversible(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    import unlimited_skills.search_core as _sc

    monkeypatch.setenv(SESSION_SALT_ENV, "unit-test-pinned-salt")
    monkeypatch.setattr(_sc, "_SALT_CACHE", None)  # force re-read of the pinned salt
    raw = "super-secret-session-id-123"
    digest = hash_session_id(raw)
    assert digest is not None and len(digest) == 12
    assert raw not in digest
    assert digest.split("super")[0] == digest  # the raw token is absent
    # SALTED: not the plain unsalted sha256 of the raw id, so the token is not a
    # globally-stable fingerprint (Hermes A3.1.1: unsalted hash is Unacceptable).
    assert digest != hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    assert hash_session_id(raw) == digest       # deterministic within a salt
    assert hash_session_id("") is None
    assert hash_session_id(None) is None


def test_session_correlation_id_reads_env_with_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SESSION_ID_ENV, raising=False)
    monkeypatch.delenv(SESSION_ID_FALLBACK_ENV, raising=False)
    # No harness session id -> degrade to a per-process local run correlation id
    # (Hermes A3.1.1: "missing session id degrades to a generated local run id").
    assert session_correlation_id() == _run_correlation_id()
    monkeypatch.setenv(SESSION_ID_FALLBACK_ENV, "claude-session-xyz")
    assert session_correlation_id() == hash_session_id("claude-session-xyz")
    monkeypatch.setenv(SESSION_ID_ENV, "hook-session-abc")
    assert session_correlation_id() == hash_session_id("hook-session-abc")  # primary wins


# --- log_event session-id stamping (salted; run-id fallback) --------------

def test_log_event_degrades_to_run_id_without_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SESSION_ID_ENV, raising=False)
    monkeypatch.delenv(SESSION_ID_FALLBACK_ENV, raising=False)
    root = tmp_path / "lib"
    (root / ".learning").mkdir(parents=True)
    log_event(root, "suggest", {"a": 1})
    rec = json.loads((root / ".learning" / EVENT_LOG).read_text(encoding="utf-8").strip())
    # Spec: a standalone invocation still correlates its own events via a stable
    # per-process run id (never None, never the raw id).
    assert rec["payload"]["session_correlation_id"] == _run_correlation_id()


def test_log_event_stamps_hash_never_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "raw-secret-session-id-987654321"
    monkeypatch.setenv(SESSION_ID_ENV, raw)
    root = tmp_path / "lib"
    (root / ".learning").mkdir(parents=True)
    log_event(root, "view", {"name": "python-patterns"})
    text = (root / ".learning" / EVENT_LOG).read_text(encoding="utf-8")
    assert raw not in text  # the raw id is never persisted
    rec = json.loads(text.strip())
    assert rec["payload"]["session_correlation_id"] == hash_session_id(raw)


# --- suggest event enrichment (event log only, not stdout) ---------------

def _clear_session_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SESSION_ID_ENV, raising=False)
    monkeypatch.delenv(SESSION_ID_FALLBACK_ENV, raising=False)


def test_suggest_event_has_injected_and_buckets(library: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    _clear_session_env(monkeypatch)
    suggest.main(["--root", str(library), "python code review best practices", "--json"])
    capsys.readouterr()
    last = (library / ".learning" / EVENT_LOG).read_text(encoding="utf-8").strip().splitlines()[-1]
    payload = json.loads(last)["payload"]
    assert payload["injected"] is False  # non-card mode never injects a card
    assert payload["score_bucket"] in {"below_floor", "low", "medium", "high", "very_high"}
    assert "margin_bucket" in payload


def test_suggest_stdout_contract_unchanged_in_non_card(library: Path, capsys: pytest.CaptureFixture) -> None:
    suggest.main(["--root", str(library), "python code review best practices", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"task_summary_hash", "top_3_skill_candidates", "reason_code", "recommended_next_action", "latency_ms"}
    assert "injected" not in out and "score_bucket" not in out  # new fields stay in the local log only


# --- funnel metrics ------------------------------------------------------

def _write_events(root: Path, rows: list[dict]) -> None:
    learning = root / ".learning"
    learning.mkdir(parents=True, exist_ok=True)
    (learning / EVENT_LOG).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_compute_event_metrics_funnel(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    rows = [
        # session A: card injected -> view -> use
        {"ts": 1.0, "type": "suggest", "payload": {"delivery_tier": 3, "injected": True, "score_bucket": "very_high", "margin_bucket": "dominant", "session_correlation_id": "A"}},
        {"ts": 2.0, "type": "view", "payload": {"session_correlation_id": "A"}},
        {"ts": 3.0, "type": "skill_used", "payload": {"session_correlation_id": "A"}},
        # session B: card injected -> use WITHOUT a view (card consumed directly)
        {"ts": 1.0, "type": "suggest", "payload": {"delivery_tier": 3, "injected": True, "score_bucket": "high", "margin_bucket": "clear", "session_correlation_id": "B"}},
        {"ts": 2.0, "type": "skill_used", "payload": {"session_correlation_id": "B"}},
        # session C: hint, no follow-up (missed after hint)
        {"ts": 1.0, "type": "suggest", "payload": {"delivery_tier": 2, "injected": False, "score_bucket": "low", "margin_bucket": "slim", "session_correlation_id": "C"}},
        # session-less suggest: counted at suggest level, not attributed to a funnel
        {"ts": 1.0, "type": "suggest", "payload": {"delivery_tier": 1, "injected": False, "score_bucket": "below_floor", "margin_bucket": "no_runner_up"}},
    ]
    _write_events(root, rows)
    m = compute_event_metrics(root)
    assert m["suggest_count"] == 4
    assert m["carded_suggest_count"] == 4
    assert m["injected_count"] == 2
    assert m["injection_rate"] == 0.5
    assert m["tier_counts"] == {"3": 2, "2": 1, "1": 1}
    assert m["score_bucket_counts"] == {"very_high": 1, "high": 1, "low": 1, "below_floor": 1}
    assert m["attributed_sessions"] == 3
    assert m["suggest_sessions"] == 3
    assert m["post_suggest_view_rate"] == round(1 / 3, 3)   # only A had a view
    assert m["post_suggest_use_rate"] == round(2 / 3, 3)    # A and B used a skill
    assert m["card_to_action_proxy_rate"] == 1.0            # both card sessions acted
    assert m["card_used_without_view"] == 1                 # session B
    assert m["missed_after_hint_rate"] == 1.0               # session C never followed up


def test_compute_event_metrics_empty_is_safe(tmp_path: Path) -> None:
    m = compute_event_metrics(tmp_path / "does-not-exist")
    assert m["suggest_count"] == 0
    assert m["injection_rate"] is None
    assert m["post_suggest_view_rate"] is None
    assert m["card_used_without_view"] == 0


def test_view_before_suggest_does_not_count_as_post(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    rows = [
        {"ts": 5.0, "type": "view", "payload": {"session_correlation_id": "Z"}},  # BEFORE the suggest
        {"ts": 6.0, "type": "suggest", "payload": {"delivery_tier": 2, "injected": False, "session_correlation_id": "Z"}},
    ]
    _write_events(root, rows)
    m = compute_event_metrics(root)
    assert m["post_suggest_view_rate"] == 0.0  # the view preceded the suggest
    assert m["missed_after_hint_rate"] == 1.0


def test_learning_summary_default_output_is_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "lib"
    learning = root / ".learning"
    learning.mkdir(parents=True)
    (learning / "feedback.jsonl").write_text(
        json.dumps({"name": "python-patterns", "verdict": "accepted"}) + "\n",
        encoding="utf-8",
    )
    _write_events(
        root,
        [
            {
                "ts": 1.0,
                "type": "suggest",
                "payload": {
                    "query": "private task text",
                    "delivery_tier": 3,
                    "session_correlation_id": "abc123",
                },
            }
        ],
    )

    _cli.main(["--root", str(root), "learning-summary"])

    assert json.loads(capsys.readouterr().out) == {
        "python-patterns": {"accepted": 1, "neutral": 0, "rejected": 0}
    }


def test_learning_summary_events_output_is_aggregate_only(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "lib"
    raw_session = "raw-session-id-that-must-not-appear"
    hashed = hash_session_id(raw_session)
    assert hashed is not None
    _write_events(
        root,
        [
            {
                "ts": 1.0,
                "type": "suggest",
                "payload": {
                    "query": "private task text",
                    "delivery_tier": 3,
                    "injected": True,
                    "score_bucket": "high",
                    "margin_bucket": "clear",
                    "session_correlation_id": hashed,
                },
            },
            {"ts": 2.0, "type": "skill_used", "payload": {"session_correlation_id": hashed}},
        ],
    )

    _cli.main(["--root", str(root), "learning-summary", "--events"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["feedback"] == {}
    assert payload["effectiveness"]["suggest_count"] == 1
    assert payload["effectiveness"]["post_suggest_use_rate"] == 1.0
    assert "private task text" not in output
    assert raw_session not in output
    assert hashed not in output


# --- privacy grep gate (Hermes A3.1.1 required evidence) -----------------

def test_events_jsonl_leaks_no_raw_identifiers(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The event log must never contain the raw session id, the raw query/task
    text, an env value, or a local absolute path — only the salted correlation
    token and coarse buckets. This is the privacy gate, asserted by grep."""
    raw_session = "raw-session-id-DO-NOT-PERSIST-42"
    query_needle = "zphraseUniqueQueryNeedleX"  # lives in the query, must not be logged
    env_needle = "env-value-should-never-appear"
    monkeypatch.setenv(SESSION_ID_ENV, raw_session)
    monkeypatch.setenv("UNLIMITED_SKILLS_SECRET_PROBE", env_needle)
    suggest.main(["--root", str(library), f"python {query_needle} code review best practices", "--json"])
    text = (library / ".learning" / EVENT_LOG).read_text(encoding="utf-8")
    assert raw_session not in text          # raw session id never persisted
    assert query_needle not in text         # raw query / task text never persisted
    assert env_needle not in text           # env values never persisted
    assert str(library) not in text         # no local absolute path
    payload = json.loads(text.strip().splitlines()[-1])["payload"]
    assert payload["session_correlation_id"] == hash_session_id(raw_session)  # salted token only
