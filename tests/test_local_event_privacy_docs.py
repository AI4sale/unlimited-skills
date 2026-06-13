from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs" / "adoption" / "local-event-privacy-audit.md"
POLICY = ROOT / "docs" / "adoption" / "local-event-privacy-policy.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_local_event_privacy_docs_exist_and_define_scope() -> None:
    audit = read(AUDIT).lower()
    policy = read(POLICY).lower()

    for required in [
        "<library>/.learning/events.jsonl",
        "<library>/.learning/feedback.jsonl",
        "team-events.jsonl",
        "hub/logs/audit.jsonl",
        "learning-summary --events",
        "feedback prepare",
        "mcp savings",
        "mcp audit replay",
    ]:
        assert required in audit

    for required in [
        "not telemetry",
        "not uploaded",
        "raw prompts",
        "raw task text",
        "raw query text",
        "tool inputs",
        "tool outputs",
        "skill bodies",
        "local absolute paths",
    ]:
        assert required in policy


def test_local_event_privacy_audit_lists_required_event_types() -> None:
    audit = read(AUDIT)
    required_event_types = [
        "suggest",
        "search",
        "list",
        "view",
        "skill_used",
        "quickstart",
        "mcp_savings",
        "daemon_search",
        "daemon_view",
        "daemon_skill_used",
        "daemon_feedback",
        "feedback.jsonl",
        "team-events.jsonl",
        "managed_policy_remove_refused",
        "Hub audit events",
        "tools_schema",
        "tools_call",
        "profile_loaded",
        "learning-summary --events",
        "feedback prepare",
    ]
    for event_type in required_event_types:
        assert event_type in audit


def test_local_event_privacy_audit_uses_required_classification_vocabulary() -> None:
    audit = read(AUDIT).lower()
    for phrase in [
        "risk_level: safe | caution | unsafe",
        "decision: keep | hash | redact | remove | document-local-only",
        "| field | event_type | current_behavior | risk_level | decision | owner | fallback | implementation_task |",
    ]:
        assert phrase in audit

    for decision in ["keep", "hash", "redact", "remove", "document-local-only"]:
        assert f"| {decision} |" in audit or f"`{decision}`" in audit
    for risk in ["safe", "caution", "unsafe"]:
        assert f"| {risk} |" in audit or f"`{risk}`" in audit


def test_local_event_privacy_audit_identifies_risky_fields_and_a410_handoff() -> None:
    audit = read(AUDIT).lower()
    for required in [
        "payload.query",
        "payload.task",
        "payload.path",
        "payload.filter",
        "payload.notes",
        "payload.hits[].path",
        "payload.hits[].score",
        "raw mcp `tools_schema` / `tools_call` rows",
        "a4.10 handoff",
        "replace raw query/task fields",
        "remove absolute paths",
        "privacy grep tests",
    ]:
        assert required in audit


def test_local_event_privacy_policy_has_owner_action_fallback_and_guardrails() -> None:
    policy = read(POLICY).lower()
    for required in [
        "| risk | owner | action | fallback |",
        "raw query/task text in event rows",
        "local absolute paths in event rows",
        "freeform feedback notes",
        "mcp server names",
        "team/policy operational ids",
        "raw mcp audit rows",
    ]:
        assert required in policy

    for guardrail in [
        "no telemetry",
        "no auto-upload",
        "no hosted calls",
        "no tracking pixels",
        "no analytics sdk",
        "no prompt collection",
        "no tool input collection",
        "no tool output collection",
        "no paid cta",
        "no payment link",
        "no hosted readiness claim",
        "no team readiness claim",
        "no enterprise readiness claim",
        "#119 remains parked",
    ]:
        assert guardrail in policy


def test_changelog_mentions_local_event_privacy_audit() -> None:
    changelog = read(CHANGELOG).lower()
    assert "local event privacy audit" in changelog
    assert "a4.9" in changelog
