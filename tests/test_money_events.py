"""Tests for event/cache accounting + compact storage (O064-R2-04)."""

from __future__ import annotations

import json
from pathlib import Path

from unlimited_skills import money_events as me


def _event(event_type="compaction", *, model="claude-opus-4.8", price_class=None,
           gen="2026-06-17T00:00:01Z", eid="e1", skills_base=1000, skills_actual=60,
           mcp_base=500, mcp_actual=50):
    return me.build_event(
        agent="claude-code", event_type=event_type,
        provider="anthropic", model=model, model_source="detected_runtime",
        currency="USD", price_source_date="2026-06-17",
        token_counter_method="anthropic_count_tokens",
        skills={"visible_skill_count": 372, "baseline_tokens": skills_base, "actual_router_tokens": skills_actual},
        mcp={"baseline_tokens": mcp_base, "actual_gateway_tokens": mcp_actual},
        price_class=price_class, event_id=eid, generated_at=gen,
    )


def test_build_event_shape_and_default_price_class():
    ev = _event("compaction")
    assert ev["schema_version"] == "money-saved-event-v1"
    assert ev["cache"]["price_class"] == "cache_write_5m"
    assert ev["cache"]["source"] == "default_for_event_type"
    first = me.build_event(
        agent="claude-code", event_type="session_start", provider="anthropic",
        model="claude-opus-4.8", model_source="detected_runtime", currency="USD",
        price_source_date="2026-06-17", token_counter_method="anthropic_count_tokens",
        skills={"baseline_tokens": 10, "actual_router_tokens": 1}, mcp={"baseline_tokens": 0, "actual_gateway_tokens": 0},
    )
    assert first["cache"]["price_class"] == "base_input"  # first session: no warm cache


def test_record_event_same_basis_aggregates(tmp_path: Path):
    d = tmp_path
    me.record_event(_event("session_start", price_class="base_input", gen="2026-06-17T00:00:01Z", eid="a"), d)
    summary = me.record_event(_event("compaction", price_class="base_input", gen="2026-06-17T00:00:09Z", eid="b"), d)
    # Same 8-field basis (we pinned price_class) -> ONE bucket, count 2.
    assert len(summary["buckets"]) == 1
    bucket = next(iter(summary["buckets"].values()))
    assert bucket["event_count"] == 2
    assert bucket["event_types"] == {"session_start": 1, "compaction": 1}
    assert bucket["skills_total_tokens_saved"] == (1000 - 60) * 2
    assert bucket["mcp_total_tokens_saved"] == (500 - 50) * 2
    assert bucket["total_tokens_saved"] == bucket["skills_total_tokens_saved"] + bucket["mcp_total_tokens_saved"]
    assert bucket["first_event_at"] == "2026-06-17T00:00:01Z"
    assert bucket["last_event_at"] == "2026-06-17T00:00:09Z"


def test_record_event_different_basis_separate_buckets_but_bounded(tmp_path: Path):
    d = tmp_path
    # Different price_class and different model => distinct basis => distinct buckets.
    me.record_event(_event("compaction", price_class="cache_write_5m", eid="x"), d)
    me.record_event(_event("compaction", price_class="base_input", eid="y"), d)
    summary = me.record_event(_event("compaction", model="claude-sonnet-4.6", price_class="cache_write_5m", eid="z"), d)
    assert len(summary["buckets"]) == 3  # O(distinct model x price_class), not session count


def test_recent_events_tail_is_capped(tmp_path: Path):
    d = tmp_path
    for i in range(10):
        me.append_recent(_event(eid=f"e{i}", gen="2026-06-17T00:00:01Z"), d, cap=4)
    rows = me.read_recent(d)
    assert len(rows) == 4
    assert [r["event_id"] for r in rows] == ["e6", "e7", "e8", "e9"]  # oldest dropped


def test_summary_file_is_compact_json(tmp_path: Path):
    d = tmp_path
    me.record_event(_event(eid="only"), d)
    raw = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == "money-saved-summary-v1"
    assert raw["money_model_version"] == "money-saved-v2"
    assert len(raw["buckets"]) == 1


def test_events_inspect_reports_aggregate_and_tail(tmp_path: Path):
    d = tmp_path
    me.record_event(_event("session_start", price_class="base_input", eid="i1"), d)
    me.record_event(_event("compaction", price_class="base_input", eid="i2"), d)
    report = me.events_inspect(d)
    assert report["schema_version"] == "money-saved-events-inspect-v1"
    assert report["storage"] == "compact_summary_plus_capped_tail"
    assert report["total_event_count"] == 2
    assert report["bucket_count"] == 1
    assert len(report["recent_events"]) == 2
