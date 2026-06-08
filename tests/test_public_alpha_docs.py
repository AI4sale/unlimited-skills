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
