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


def test_readme_positions_skills_before_tool_schema_savings() -> None:
    readme = read("README.md")
    lower = readme.lower()

    assert "# Stop flooding your agent's context with skills and tool schemas" in readme
    assert "Search first. Load one skill, tool, or procedure only when needed." in readme
    assert "local-first capability router for coding agents" in readme
    assert "Skill pre-load context cost" in readme
    assert "Measure before and after install" in readme
    assert "install-hermes.sh --mode evacuate-visible-skills --apply" in readme
    assert lower.index("skill pre-load context cost") < lower.index("mcp standing context cost")
    assert "docs/context-reduction-model.md" in readme


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
    privacy_policy = read("docs/adoption/local-event-privacy-policy.md").lower()
    event_runbook = read("docs/adoption/local-event-privacy-support-runbook.md").lower()
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
        "local event privacy question",
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
        "local-event-privacy-support-runbook.md",
        "unlimited-skills learning-summary --events",
        "raw `.learning/events.jsonl`",
        "raw `.learning/feedback.jsonl`",
        "raw `.learning/team-events.jsonl`",
        "raw mcp audit logs",
        "v0.5.3-alpha",
        "does not rewrite old local logs",
    ]:
        assert required in pack_lower

    combined_docs = "\n".join([triage, routing, feedback, privacy_policy, event_runbook, changelog])
    assert "support-response-pack.md" in combined_docs
    assert "local-event-privacy-support-runbook.md" in combined_docs
    assert "local-event-privacy-policy.md" in combined_docs
    assert "redacted evidence" in combined_docs
    assert "support" in combined_docs
    assert "legacy pre-v0.5.3" in combined_docs
    assert "delete or rename only the selected diagnostic files" in combined_docs

    unsafe_request_patterns = [
        r"please (share|paste|attach|send).{0,80}prompt",
        r"please (share|paste|attach|send).{0,80}tool input",
        r"please (share|paste|attach|send).{0,80}tool output",
        r"please (share|paste|attach|send).{0,80}raw events\\.jsonl",
        r"please (share|paste|attach|send).{0,80}raw feedback\\.jsonl",
        r"please (share|paste|attach|send).{0,80}raw team-events\\.jsonl",
        r"please (share|paste|attach|send).{0,80}raw \\.learning/events\\.jsonl",
        r"please (share|paste|attach|send).{0,80}raw \\.learning/feedback\\.jsonl",
        r"please (share|paste|attach|send).{0,80}raw \\.learning/team-events\\.jsonl",
        r"please (share|paste|attach|send).{0,80}raw mcp audit",
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
        assert phrase not in event_runbook


def test_local_event_privacy_support_runbook_blocks_raw_log_requests() -> None:
    runbook = read("docs/adoption/local-event-privacy-support-runbook.md").lower()
    support = read("docs/adoption/support-response-pack.md").lower()
    feedback = read("docs/feedback.md").lower()
    policy = read("docs/adoption/local-event-privacy-policy.md").lower()
    combined = "\n".join([runbook, support, feedback, policy])

    for required in [
        "feedback prepare --format markdown",
        "learning-summary --events",
        "v0.5.3-alpha",
        "does not magically rewrite old local logs",
        "legacy pre-v0.5.3",
        "delete or rename only the selected diagnostic files",
        "do not ask users to paste, attach, send, or upload raw local event logs",
        "raw `.learning/events.jsonl`",
        "raw `.learning/feedback.jsonl`",
        "raw `.learning/team-events.jsonl`",
        "raw mcp audit jsonl logs",
        "not telemetry",
        "does not upload",
    ]:
        assert required in combined

    for unsafe_surface in [
        "raw `events.jsonl`",
        "raw `feedback.jsonl`",
        "raw `team-events.jsonl`",
        "raw `.mcp.json`",
        "raw `.claude.json`",
        "env dumps",
        "tokens, keys",
        "local absolute paths",
        "prompts, tool inputs, tool outputs, skill bodies, or mcp schemas",
    ]:
        assert unsafe_surface in combined

    blocked_claims = [
        "telemetry exists",
        "uploads exist",
        "hosted support is available",
        "team or enterprise privacy controls are ready",
        "paid support",
        "payment paths exist",
        "all legacy local logs were rewritten",
    ]
    assert "do not claim:" in runbook
    for phrase in blocked_claims:
        assert phrase in runbook

    for phrase in [
        "hosted service is ready",
        "team mode is ready",
        "enterprise is ready",
    ]:
        assert phrase not in support


def test_v06_contract_freeze_documents_public_alpha_contracts() -> None:
    spec = read("docs/releases/v0.6-contract-freeze-spec.md").lower()
    compatibility = read("docs/compatibility.md").lower()
    cli_contracts = read("docs/cli-contracts.md").lower()
    local_privacy = read("docs/local-event-privacy.md").lower()
    feedback = read("docs/feedback.md").lower()
    runbook = read("docs/adoption/local-event-privacy-support-runbook.md").lower()
    changelog = read("CHANGELOG.md").lower()
    combined = "\n".join([spec, compatibility, cli_contracts, local_privacy, feedback, runbook, changelog])

    for path in [
        "docs/releases/v0.6-contract-freeze-spec.md",
        "docs/compatibility.md",
        "docs/cli-contracts.md",
        "docs/local-event-privacy.md",
    ]:
        assert path in combined

    for command in [
        "unlimited-skills quickstart",
        "unlimited-skills suggest",
        "unlimited-skills mcp savings",
        "unlimited-skills mcp install --claude-code",
        "unlimited-skills feedback prepare",
        "unlimited-skills learning-summary --events",
        "scripts/generate-public-alpha-signal-rollup.py",
    ]:
        assert command in combined

    for required in [
        "compatibility promise through the v0.7 adoption cycle",
        "stdout json stability",
        "feedback report schema",
        "pypi trusted publishing",
        "local event privacy behavior after `v0.5.3-alpha`",
        "legacy pre-v0.5.3 local logs are not automatically rewritten",
        "#119/e19",
        "#119 remains parked",
        "frozen contracts",
        "still alpha before 1.0",
        "optional fields may be added",
        "documented fields must not be removed or repurposed",
    ]:
        assert required in combined

    for privacy_boundary in [
        "no telemetry",
        "no analytics",
        "tracking pixels",
        "hosted query forwarding",
        "prompts, tool inputs, tool outputs, skill bodies, or mcp schemas",
        "raw `.learning/events.jsonl`",
        "raw `.learning/feedback.jsonl`",
        "raw `.learning/team-events.jsonl`",
        "raw mcp audit jsonl logs",
    ]:
        assert privacy_boundary in combined

    for forbidden_claim in [
        "paid plan is ready",
        "hosted service is ready",
        "team mode is ready",
        "enterprise is ready",
        "marketplace acceptance is guaranteed",
        "we will deliver",
        "guaranteed support",
        "payment link",
        "checkout path",
    ]:
        assert forbidden_claim not in combined


def test_v06_local_roi_receipt_spec_is_privacy_safe_and_measured_not_promised() -> None:
    spec = read("docs/releases/v0.6-local-roi-receipt-spec.md").lower()
    receipt = read("docs/roi-receipt.md").lower()
    cli_contracts = read("docs/cli-contracts.md").lower()
    local_privacy = read("docs/local-event-privacy.md").lower()
    feedback = read("docs/feedback.md").lower()
    changelog = read("CHANGELOG.md").lower()
    combined = "\n".join([spec, receipt, cli_contracts, local_privacy, feedback, changelog])

    for path in [
        "docs/releases/v0.6-local-roi-receipt-spec.md",
        "docs/roi-receipt.md",
        "docs/cli-contracts.md",
        "docs/local-event-privacy.md",
    ]:
        assert path in combined

    for command in [
        "unlimited-skills roi receipt",
        "unlimited-skills roi receipt --format markdown",
        "unlimited-skills roi receipt --format json",
        "unlimited-skills roi receipt --since 7d",
        "unlimited-skills roi receipt --out roi-receipt.md",
    ]:
        assert command in combined

    for allowed in [
        "installed unlimited skills version",
        "local library skill count",
        "quickstart status",
        "mcp savings summary",
        "suggest count",
        "skill view/use count",
        "suggest-to-view/use aggregate conversion",
        "learning-summary --events",
        "feedback prepare",
        "generated timestamp",
        "local-only/no-upload notice",
        "safe aggregate",
        "derived",
    ]:
        assert allowed in combined

    for forbidden in [
        "prompts",
        "raw queries",
        "raw tasks",
        "tool inputs",
        "tool outputs",
        "skill bodies",
        "mcp schemas",
        "raw `events.jsonl`",
        "raw `feedback.jsonl`",
        "raw `.mcp.json` or `.claude.json`",
        "environment names or values",
        "tokens, keys, or proofs",
        "local absolute paths",
        "user identifiers",
        "tracking identifiers",
    ]:
        assert forbidden in combined

    for required in [
        "this receipt is a local estimate from your own machine. it is not telemetry, not a benchmark guarantee, and not a paid roi promise.",
        "specification only",
        "not implemented yet",
        "screenshot-friendly",
        "legacy pre-v0.5.3",
        "unavailable_legacy_logs",
        "#119/e19",
        "#119 remains parked",
        "no runtime implementation",
        "no package release",
        "no marketplace submission",
        "no external analytics",
        "no telemetry",
        "no upload path",
        "no hosted/team/enterprise readiness claim",
        "no universal savings promise",
        "no guarantee of return",
    ]:
        assert required in combined

    for forbidden_claim in [
        "roi is guaranteed",
        "guaranteed roi",
        "guaranteed savings",
        "universal savings guarantee",
        "paid plan is ready",
        "hosted service is ready",
        "team mode is ready",
        "enterprise is ready",
        "marketplace acceptance is guaranteed",
        "we will deliver",
        "guaranteed support",
    ]:
        assert forbidden_claim not in combined


def test_v06_local_roi_receipt_runtime_docs_keep_privacy_boundary() -> None:
    receipt = read("docs/roi-receipt.md").lower()
    cli_contracts = read("docs/cli-contracts.md").lower()
    local_privacy = read("docs/local-event-privacy.md").lower()
    feedback = read("docs/feedback.md").lower()
    changelog = read("CHANGELOG.md").lower()
    schema = read("schemas/roi-receipt.schema.json").lower()
    verifier = read("scripts/verify-roi-receipt-boundaries.py").lower()
    combined = "\n".join([receipt, cli_contracts, local_privacy, feedback, changelog, schema, verifier])

    for required in [
        "unlimited-skills roi receipt",
        "stable public-alpha",
        "schemas/roi-receipt.schema.json",
        "examples/roi-receipt.example.json",
        "scripts/verify-roi-receipt-boundaries.py",
        "screenshot-friendly markdown",
        "unavailable_legacy_logs",
        "does not upload",
        "does not add upload",
        "telemetry: no",
        "not telemetry, not a benchmark guarantee, and not a paid roi promise",
    ]:
        assert required in combined

    for forbidden in [
        "prompts",
        "raw queries",
        "raw tasks",
        "tool inputs",
        "tool outputs",
        "skill bodies",
        "mcp schemas",
        "raw `events.jsonl`",
        "raw `feedback.jsonl`",
        "raw `.mcp.json` or `.claude.json`",
        "environment names or values",
        "tokens, keys, or proofs",
        "local absolute paths",
        "user identifiers",
        "tracking identifiers",
    ]:
        assert forbidden in combined

    for forbidden_claim in [
        "guaranteed roi",
        "guaranteed savings",
        "universal savings guarantee",
        "payment link",
        "checkout path",
        "paid plan is ready",
        "hosted service is ready",
        "team mode is ready",
        "enterprise is ready",
        "marketplace acceptance is guaranteed",
    ]:
        assert forbidden_claim not in combined


def test_v06_contract_compliance_audit_records_actual_v061_behavior() -> None:
    audit = read("docs/releases/v0.6-contract-compliance-audit.md").lower()
    compatibility = read("docs/compatibility.md").lower()
    cli_contracts = read("docs/cli-contracts.md").lower()
    local_privacy = read("docs/local-event-privacy.md").lower()
    feedback = read("docs/feedback.md").lower()
    receipt = read("docs/roi-receipt.md").lower()
    changelog = read("CHANGELOG.md").lower()
    combined = "\n".join([audit, compatibility, cli_contracts, local_privacy, feedback, receipt, changelog])

    for path in [
        "docs/releases/v0.6-contract-compliance-audit.md",
        "docs/compatibility.md",
        "docs/cli-contracts.md",
        "docs/local-event-privacy.md",
        "docs/feedback.md",
        "docs/roi-receipt.md",
    ]:
        assert path in combined

    for command in [
        "unlimited-skills --version",
        "unlimited-skills quickstart --json",
        "unlimited-skills suggest \"design a rest api for a service\" --json",
        "unlimited-skills mcp savings --json",
        "unlimited-skills mcp install --claude-code --dry-run",
        "unlimited-skills feedback prepare --json",
        "unlimited-skills learning-summary --events --json",
        "unlimited-skills roi receipt",
        "unlimited-skills roi receipt --format json",
        "unlimited-skills roi receipt --since 7d",
        "scripts/generate-public-alpha-signal-rollup.py",
    ]:
        assert command in combined

    for required in [
        "v0.6.1-alpha is the valid v0.6 alpha release",
        "unlimited-skills==0.6.1",
        "unlimited-skills 0.6.1",
        "3b30b41f751451331de231c352eff2bce3d4fddc",
        "https://github.com/ai4sale/unlimited-skills/releases/tag/v0.6.1-alpha",
        "verify-v060-alpha-publication.py --package-availability published",
        "0.6.0 package was uploaded to pypi but was not tagged or released",
        "learning-summary --events --json",
        "failed published verifier",
        "no runtime drift requiring a `v0.6.2` blocker was found",
        "only #119, parked e19",
        "#119/e19 remains parked",
        "feedback report schema",
        "roi receipt schema",
        "stdout json stability",
        "pypi trusted publishing",
        "post-publish verifier",
        "local event privacy after `v0.5.3-alpha`",
    ]:
        assert required in combined

    for blocked_claim in [
        "no runtime behavior changes",
        "no package release",
        "no marketplace submission",
        "no hosted, team, or enterprise readiness claim",
        "no paid cta",
        "payment flow",
        "no telemetry",
        "no telemetry, upload, analytics sdk, tracking pixel",
        "no hosted query forwarding",
        "prompt collection",
        "tool input collection",
        "tool output collection",
    ]:
        assert blocked_claim in combined

    for forbidden_claim in [
        "paid plan is ready",
        "hosted service is ready",
        "team mode is ready",
        "enterprise is ready",
        "guaranteed roi",
        "guaranteed savings",
        "we will deliver",
        "marketplace acceptance is guaranteed",
    ]:
        assert forbidden_claim not in combined


def test_marketplace_submission_tracker_requires_evidence_and_fresh_rule_checks() -> None:
    tracker = read("docs/adoption/marketplace-submission-tracker.md").lower()
    runbook = read("docs/adoption/marketplace-submission-runbook.md").lower()
    launch_pack = read("docs/adoption/marketplace-listing-launch-pack.md").lower()
    listing_copy = read("docs/adoption/marketplace-listing-copy.md").lower()
    approval_packet = read("docs/adoption/submission-owner-approval-packet.md").lower()

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

    combined = "\n".join([tracker, runbook, launch_pack, listing_copy, approval_packet])
    for required in [
        "re-check",
        "current rules",
        "evidence link",
        "owner action",
        "blocked_pending_owner_approval",
        "submission-owner-approval-packet.md",
        "current_rule_check_date",
        "submission_owner",
        "exact_listing_copy_reference",
        "submitter: owner | codex | human_delegate",
        "permission_to_submit: no",
        "permission_to_submit: yes",
        "evidence_required_after_submission",
        "blocked_claims_acknowledged",
        "fallback_if_rejected",
        "no paid cta",
        "no payment link",
        "no checkout path",
        "no hosted/team/enterprise readiness claim",
        "no delivery promise",
        "guaranteed marketplace acceptance",
        "does not submit anywhere",
        "do not mark",
    ]:
        assert required in combined

    assert "marketplace-submission-tracker.md" in launch_pack
    assert "marketplace-submission-runbook.md" in launch_pack
    assert "submission-owner-approval-packet.md" in launch_pack
    assert "marketplace-submission-tracker.md" in listing_copy
    assert "marketplace-submission-runbook.md" in listing_copy
    assert "submission-owner-approval-packet.md" in listing_copy
    assert "submission-owner-approval-packet.md" in tracker
    assert "submission-owner-approval-packet.md" in runbook


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
    rollup_002 = read("docs/adoption/public-alpha-signal-rollup-002.md").lower()
    signals = read("docs/adoption/adoption-signals.md").lower()
    measurement = read("docs/adoption/first-week-adoption-measurement.md").lower()
    tracker = read("docs/adoption/marketplace-submission-tracker.md").lower()
    changelog = read("CHANGELOG.md").lower()
    template = read("docs/adoption/public-alpha-signal-rollup-template.md").lower()
    generator = read("scripts/generate-public-alpha-signal-rollup.py").lower()

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
        assert required_section in rollup_002

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

    for required_fact in [
        "unlimited-skills==0.5.3",
        "v0.5.3-alpha",
        "5 stars",
        "0 forks",
        "0 non-pr issues returned",
        "open prs observed: #119",
        "not_submitted=3",
        "blocked_pending_owner_approval",
        "permission_to_submit: yes",
        "low_signal",
        "no_feedback_yet",
    ]:
        assert required_fact in rollup_002

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
        assert privacy_boundary in rollup_002

    for blocked_claim in [
        "marketplace submission",
        "paid outreach",
        "payment links",
        "hosted/team/enterprise readiness claims",
        "external acceptance claims",
    ]:
        assert blocked_claim in rollup
        assert blocked_claim in rollup_002

    for owner_action_fallback in [
        "| blocker | owner | action | fallback |",
        "release owner",
        "project owner",
        "ask for three redacted first-value or install-friction reports",
        "keep all marketplace rows `not_submitted`",
    ]:
        assert owner_action_fallback in rollup
        assert owner_action_fallback in rollup_002

    assert "unknown=19" not in rollup_002
    assert "public-alpha-signal-rollup-003.md" in rollup_002

    combined = "\n".join([signals, measurement, tracker, changelog, template, generator])
    assert "public-alpha-signal-rollup-001.md" in combined
    assert "public-alpha-signal-rollup-002.md" in combined
    assert "public-alpha-signal-rollup-template.md" in combined
    assert "scripts/generate-public-alpha-signal-rollup.py" in combined
    assert "--fixture-mode" in combined
    assert "--social-json" in combined
    assert "owner-provided" in combined
    assert "public aggregate sources" in combined
    assert "low_signal" in combined
    assert "no_feedback_yet" in combined
