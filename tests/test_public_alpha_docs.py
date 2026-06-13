from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def test_current_public_docs_do_not_use_v0_1_0_as_supported_version() -> None:
    checked = ["README.md", "SECURITY.md", *[str(path.relative_to(ROOT)) for path in (ROOT / "docs").rglob("*.md")]]
    offenders = [path for path in checked if "v0.1.0-alpha" in read(path)]
    assert offenders == []


def test_security_docs_do_not_claim_signature_verification_is_implemented() -> None:
    checked = ["README.md", "SECURITY.md", *[str(path.relative_to(ROOT)) for path in (ROOT / "docs").rglob("*.md")]]
    combined = "\n".join(read(path) for path in checked).lower()
    assert "signed archives" not in combined
    assert "signed archive" not in combined
    assert "hosted remote manifests must include valid signed manifest envelopes" in combined
    assert "sha256 verification is still enforced for hosted collection archives" in combined


def test_public_core_boundary_documents_registration_free_commands() -> None:
    text = read("docs/public-core-boundary.md")
    for command in [
        "search",
        "list",
        "view",
        "where",
        "use",
        "feedback",
        "reindex",
        "vector-reindex",
        "serve",
        "adapt",
        "adapt-one",
        "adapt-next",
        "apply-adaptation",
        "sync-native",
        "self-update check",
        "self-update apply",
    ]:
        assert f"`{command}`" in text


def test_first_week_adoption_measurement_is_manual_and_private() -> None:
    measurement = read("docs/adoption/first-week-adoption-measurement.md").lower()
    signals = read("docs/adoption/adoption-signals.md").lower()
    feedback = read("docs/feedback.md").lower()

    for text in (measurement, signals, feedback):
        assert "no telemetry" in text
        assert "no auto-upload" in text
        assert "no tracking pixel" in text or "no tracking pixels" in text
        assert "no analytics sdk" in text
        assert "no prompt collection" in text
        assert "no tool input collection" in text
        assert "no tool output collection" in text

    for required in [
        "pypi installs",
        "github stars",
        "github issues opened",
        "first-value feedback reports",
        "install-friction reports",
        "skill-not-invoked reports",
        "mcp savings reports",
        "marketplace/listing mentions",
        "linkedin replies/comments",
        "success thresholds",
        "failure thresholds",
        "triage cadence",
        "owner actions and fallback",
    ]:
        assert required in measurement

    assert "not to add telemetry" in measurement
    assert "weekly rollup format" in signals


def test_public_alpha_issue_templates_support_manual_measurement() -> None:
    templates = {
        "first_value": read(".github/ISSUE_TEMPLATE/first-value-feedback.yml").lower(),
        "install": read(".github/ISSUE_TEMPLATE/install-friction.yml").lower(),
        "skill": read(".github/ISSUE_TEMPLATE/skill-not-invoked.yml").lower(),
        "savings": read(".github/ISSUE_TEMPLATE/mcp-savings-report.yml").lower(),
    }

    assert "pip install unlimited-skills" in templates["first_value"]
    assert "pip install unlimited-skills" in templates["install"]
    assert "git+ url" not in templates["first_value"]
    assert "git+ url" not in templates["install"]

    for text in templates.values():
        assert "privacy check" in text
        assert "required: true" in text

    assert "feedback prepare --format markdown" in templates["skill"]
    assert "feedback prepare --include-usage-snapshot --format markdown" in templates["savings"]


def test_public_alpha_feedback_triage_labels_are_defined_and_routed() -> None:
    labels_doc = read("docs/adoption/feedback-labels.md").lower()
    labels_manifest = read(".github/labels.yml").lower()
    workflow = read("docs/adoption/feedback-triage-workflow.md").lower()
    routing = read("docs/adoption/feedback-to-backlog-routing.md").lower()
    feedback = read("docs/feedback.md").lower()
    config = read(".github/ISSUE_TEMPLATE/config.yml").lower()
    templates = {
        "first_value": read(".github/ISSUE_TEMPLATE/first-value-feedback.yml").lower(),
        "install": read(".github/ISSUE_TEMPLATE/install-friction.yml").lower(),
        "skill": read(".github/ISSUE_TEMPLATE/skill-not-invoked.yml").lower(),
        "savings": read(".github/ISSUE_TEMPLATE/mcp-savings-report.yml").lower(),
    }

    required_labels = [
        "feedback:first-value",
        "feedback:install-friction",
        "feedback:skill-invocation",
        "feedback:mcp-savings",
        "feedback:docs",
        "feedback:marketplace",
        "severity:p0-user-blocker",
        "severity:p1-high-friction",
        "severity:p2-improvement",
        "needs:repro",
        "needs:maintainer-review",
    ]
    for label in required_labels:
        assert label in labels_doc
        assert f"name: {label}" in labels_manifest

    for required in [
        "category: feedback",
        "category: severity",
        "category: needs",
        "category: backlog",
        "category: outcome",
        "scripts/verify-feedback-labels.py",
        "scripts/sync-github-labels.py --dry-run",
        "--apply",
        "never mutate github labels",
    ]:
        assert required in "\n".join([labels_doc, workflow, routing, labels_manifest])

    expected_template_labels = {
        "first_value": ["feedback:first-value", "severity:p2-improvement", "needs:maintainer-review"],
        "install": ["feedback:install-friction", "severity:p1-high-friction", "needs:repro"],
        "skill": ["feedback:skill-invocation", "severity:p1-high-friction", "needs:maintainer-review"],
        "savings": ["feedback:mcp-savings", "severity:p2-improvement", "needs:maintainer-review"],
    }
    for template_name, labels in expected_template_labels.items():
        for label in labels:
            assert label in templates[template_name]

    assert "feedback%3amarketplace" in config
    assert "backlog:eval-candidate" in routing
    assert "quickstart/package smoke" in routing
    assert "frozen eval set" in workflow
    assert "24-48 hours" in workflow
    assert "adoption/feedback-triage-workflow.md" in feedback
    assert "adoption/feedback-labels.md" in feedback
    assert "adoption/feedback-to-backlog-routing.md" in feedback

    assert "backlog:code-fix" in labels_manifest
    assert "backlog:docs-fix" in labels_manifest
    assert "backlog:eval-candidate" in labels_manifest
    assert "backlog:listing-copy" in labels_manifest
    assert "backlog:benchmark-docs" in labels_manifest
    assert "answered:no-change" in labels_manifest
    assert "blocked:needs-repro" in labels_manifest

    triage_docs = "\n".join([labels_doc, workflow, routing, feedback])
    forbidden_promises = [
        "payment link",
        "paid cta",
        "hosted service availability",
        "enterprise delivery",
    ]
    for phrase in forbidden_promises:
        assert phrase in triage_docs
    assert "does not promise delivery" not in triage_docs


def test_public_alpha_support_response_pack_is_safe_and_routed() -> None:
    pack = read("docs/adoption/support-response-pack.md")
    pack_lower = pack.lower()
    triage = read("docs/adoption/feedback-triage-workflow.md").lower()
    routing = read("docs/adoption/feedback-to-backlog-routing.md").lower()
    feedback = read("docs/feedback.md").lower()
    changelog = read("CHANGELOG.md").lower()

    for template in [
        "first value succeeded",
        "install failed",
        "quickstart failed",
        "claude code mcp install failed",
        "skill was not invoked",
        "wrong skill suggested",
        "mcp savings confusing or low savings",
        "feedback report attached",
        "privacy concern",
        "marketplace/listing discovery question",
    ]:
        assert template in pack_lower

    for label in [
        "feedback:first-value",
        "feedback:install-friction",
        "feedback:skill-invocation",
        "feedback:mcp-savings",
        "feedback:marketplace",
        "severity:p1-high-friction",
        "severity:p2-improvement",
        "needs:repro",
        "needs:maintainer-review",
    ]:
        assert label in pack_lower

    for required in [
        "unlimited-skills feedback prepare --format markdown",
        "unlimited-skills feedback prepare --include-usage-snapshot --format markdown",
        'pip install "unlimited-skills>=0.5.1"',
        "frozen eval candidate",
        "frozen effectiveness set",
        "please share only names, counts",
    ]:
        assert required in pack_lower

    combined_docs = "\n".join([triage, routing, feedback, changelog])
    assert "support-response-pack.md" in combined_docs
    assert "redacted evidence" in combined_docs
    assert "support" in combined_docs

    unsafe_request_patterns = [
        r"please (share|paste|attach|send).{0,80}prompt",
        r"please (share|paste|attach|send).{0,80}tool input",
        r"please (share|paste|attach|send).{0,80}tool output",
        r"please (share|paste|attach|send).{0,80}raw \\.mcp\\.json",
        r"please (share|paste|attach|send).{0,80}raw \\.claude\\.json",
        r"please (share|paste|attach|send).{0,80}env dump",
        r"please (share|paste|attach|send).{0,80}unredacted",
    ]
    for pattern in unsafe_request_patterns:
        assert re.search(pattern, pack_lower, flags=re.DOTALL) is None

    forbidden_promises = [
        "we will fix",
        "we will deliver",
        "guaranteed support",
        "sla",
        "paid plan is ready",
        "hosted service is ready",
        "team mode is ready",
        "enterprise is ready",
    ]
    for phrase in forbidden_promises:
        assert phrase not in pack_lower


def test_marketplace_submission_tracker_requires_evidence_and_fresh_rule_checks() -> None:
    tracker = read("docs/adoption/marketplace-submission-tracker.md").lower()
    runbook = read("docs/adoption/marketplace-submission-runbook.md").lower()
    launch_pack = read("docs/adoption/marketplace-listing-launch-pack.md").lower()
    listing_copy = read("docs/adoption/marketplace-listing-copy.md").lower()

    for field in [
        "surface",
        "submission_url",
        "submission_owner",
        "date_checked",
        "date_submitted",
        "status",
        "blocker",
        "next_action",
        "evidence_link",
        "notes",
    ]:
        assert field in tracker

    for status in ["not_submitted", "submitted", "accepted", "rejected", "blocked"]:
        assert status in tracker

    for surface in [
        "claude code plugin marketplace",
        "mcp registry",
        "github repository discovery",
    ]:
        assert surface in tracker

    combined = "\n".join([tracker, runbook, launch_pack, listing_copy])
    for required in [
        "re-check",
        "current rules",
        "evidence link",
        "owner action",
        "no paid cta",
        "no payment link",
        "no hosted/team/enterprise readiness claim",
        "no delivery promise",
        "guaranteed marketplace acceptance",
        "do not mark",
    ]:
        assert required in combined

    assert "marketplace-submission-tracker.md" in launch_pack
    assert "marketplace-submission-runbook.md" in launch_pack
    assert "marketplace-submission-tracker.md" in listing_copy
    assert "marketplace-submission-runbook.md" in listing_copy


def test_roadmap_reset_prioritizes_adoption_and_keeps_trust_layer_behind_demand() -> None:
    roadmap = read("docs/roadmap.md").lower()
    adoption = read("docs/adoption-roadmap.md").lower()
    trust = read("docs/enterprise-trust-stack-status.md").lower()
    strategy = read("docs/product-strategy.md").lower()
    template = read(".github/ISSUE_TEMPLATE/trust-layer-proposal.yml").lower()
    changelog = read("CHANGELOG.md").lower()

    combined = "\n".join([roadmap, adoption, trust, strategy, template, changelog])

    for required in [
        "public-alpha adoption first",
        "first value",
        "no new e28+ hosted/team/trust implementation",
        "real user feedback demands it",
        "team or customer asks for it",
        "adoption data shows trust is blocking use",
        "owner explicitly reopens",
        "#119 remains background",
        "blocked_pending_owner_approval",
        "a3.4 actual submission evidence",
        "exact destinations",
        "exact submission owner",
        "exact listing copy",
    ]:
        assert required in combined

    for path in [
        "docs/roadmap.md",
        "docs/adoption-roadmap.md",
        "docs/enterprise-trust-stack-status.md",
        "docs/product-strategy.md",
        ".github/issue_template/trust-layer-proposal.yml",
    ]:
        assert path in combined

    forbidden_claims = [
        "no hosted readiness claim",
        "no team readiness claim",
        "no enterprise readiness claim",
        "no paid product claim",
        "no payment link",
        "no sales promise",
    ]
    for phrase in forbidden_claims:
        assert phrase in combined

    assert "existing trust stack is not deleted" in combined or "not deleted" in combined


def test_public_alpha_signal_rollup_records_low_signal_without_tracking() -> None:
    rollup = read("docs/adoption/public-alpha-signal-rollup-001.md").lower()
    signals = read("docs/adoption/adoption-signals.md").lower()
    measurement = read("docs/adoption/first-week-adoption-measurement.md").lower()
    tracker = read("docs/adoption/marketplace-submission-tracker.md").lower()
    changelog = read("CHANGELOG.md").lower()

    for required_section in [
        "## rollup summary",
        "## data sources checked",
        "## installation/discovery signals",
        "## first-value signals",
        "## feedback/issues",
        "## marketplace/listing status",
        "## social/linkedin launch signal",
        "## signal quality assessment",
        "## blockers",
        "## next actions",
    ]:
        assert required_section in rollup

    for required_fact in [
        "unlimited-skills==0.5.1",
        "v0.5.1-alpha",
        "5 stars",
        "0 forks",
        "no issues returned",
        "only parked pr #119 is open",
        "not_submitted",
        "blocked_pending_owner_approval",
        "low_signal",
        "no_feedback_yet",
    ]:
        assert required_fact in rollup

    for privacy_boundary in [
        "no telemetry",
        "tracking pixels",
        "analytics sdk",
        "private user data",
        "prompt collection",
        "tool input collection",
        "tool output collection",
        "hosted query forwarding",
    ]:
        assert privacy_boundary in rollup

    for blocked_claim in [
        "marketplace submission",
        "paid outreach",
        "payment links",
        "hosted/team/enterprise readiness claims",
        "external acceptance claims",
    ]:
        assert blocked_claim in rollup

    for owner_action_fallback in [
        "| blocker | owner | action | fallback |",
        "release owner",
        "project owner",
        "ask for three redacted first-value or install-friction reports",
        "keep all marketplace rows `not_submitted`",
    ]:
        assert owner_action_fallback in rollup

    combined = "\n".join([signals, measurement, tracker, changelog])
    assert "public-alpha-signal-rollup-001.md" in combined
    assert "low_signal" in combined
    assert "no_feedback_yet" in combined
