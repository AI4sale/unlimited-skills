from __future__ import annotations

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
