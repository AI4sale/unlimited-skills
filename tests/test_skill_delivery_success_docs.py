from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8").lower()


def test_skill_delivery_success_audit_covers_required_funnel_steps() -> None:
    audit = read("docs/adoption/skill-delivery-success-counters-audit.md")
    funnel = read("docs/adoption/skill-delivery-success-funnel.md")
    gap_map = read("docs/adoption/learning-loop-gap-map.md")
    combined = "\n".join([audit, funnel, gap_map])

    for step in [
        "suggestion generated",
        "suggestion shown to user/model",
        "skill card injected",
        "skill viewed",
        "skill used",
        "use accepted / useful",
        "use rejected / wrong skill",
        "missed-skill report",
        "wrong-skill report",
        "feedback converted to eval case",
        "eval/ranking/router/docs updated",
        "release gate proves improvement",
    ]:
        assert step in combined

    for column in [
        "funnel_step",
        "current_signal_source",
        "current_event_or_command",
        "available_fields",
        "missing_fields",
        "privacy_status",
        "counter_status",
        "owner",
        "action",
        "fallback",
        "implementation_task",
    ]:
        assert column in audit

    for status in ["ready", "partial", "missing", "not_applicable"]:
        assert status in audit


def test_skill_delivery_success_audit_names_existing_local_surfaces() -> None:
    combined = "\n".join(
        [
            read("docs/adoption/skill-delivery-success-counters-audit.md"),
            read("docs/adoption/skill-delivery-success-funnel.md"),
            read("docs/adoption/learning-loop-gap-map.md"),
        ]
    )

    for command_or_event in [
        "unlimited-skills suggest",
        "unlimited-skills view",
        "unlimited-skills use",
        "unlimited-skills feedback record",
        "unlimited-skills feedback prepare",
        "unlimited-skills learning-summary --events --json",
        "unlimited-skills roi receipt --format json",
        "suggest",
        "view",
        "skill_used",
        "feedback.jsonl",
        "events.jsonl",
        "session_correlation_id",
    ]:
        assert command_or_event in combined

    for code_path in [
        "unlimited_skills/search_core.py",
        "unlimited_skills/commands/library.py",
        "unlimited_skills/commands/feedback.py",
        "unlimited_skills/commands/roi.py",
        "unlimited_skills/feedback.py",
        "unlimited_skills/roi_receipt.py",
        "unlimited_skills/server.py",
        "unlimited_skills/quickstart.py",
    ]:
        assert code_path in combined


def test_skill_delivery_success_boundaries_and_handoffs_are_explicit() -> None:
    audit = read("docs/adoption/skill-delivery-success-counters-audit.md")
    funnel = read("docs/adoption/skill-delivery-success-funnel.md")
    gap_map = read("docs/adoption/learning-loop-gap-map.md")
    changelog = read("CHANGELOG.md")
    combined = "\n".join([audit, funnel, gap_map, changelog])

    for privacy_boundary in [
        "no telemetry",
        "no auto-upload",
        "no upload",
        "no hosted calls",
        "tracking pixels",
        "analytics sdk",
        "raw prompts",
        "raw queries",
        "raw tasks",
        "raw notes",
        "tool inputs",
        "tool outputs",
        "skill bodies",
        "mcp schemas",
        "env names or values",
        "tokens, keys, or proofs",
        "local absolute paths",
    ]:
        assert privacy_boundary in combined

    for non_goal in [
        "no runtime behavior",
        "no marketplace submission",
        "no package publishing",
        "no v0.7",
        "no payment",
        "hosted/team/enterprise readiness",
    ]:
        assert non_goal in combined

    for handoff in [
        "w1.1",
        "w2",
        "skills success-report --json",
        "feedback-to-eval candidate",
        "improvement ledger",
        "release-gate evidence",
        "e19 mcp profile bundle publishing is not a skill-delivery success counter",
    ]:
        assert handoff in combined
