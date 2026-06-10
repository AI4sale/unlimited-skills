from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = "v0.4-readiness-rfc"

REQUIRED_DOCS = [
    ROOT / "docs" / "releases" / "v0.4-readiness-audit.md",
    ROOT / "docs" / "rfcs" / "v0.4-skillops-platform-rfc.md",
    ROOT / "docs" / "rfcs" / "v0.4-risk-register.md",
    ROOT / "docs" / "rfcs" / "v0.4-implementation-epics.md",
    ROOT / "docs" / "known-limitations.md",
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
]

REQUIRED_PHRASES = [
    "public core",
    "private registry",
    "signed manifests",
    "catalog browser",
    "feedback",
    "evals",
    "improvement workflow",
    "private packs",
    "org/team governance",
    "plan/entitlement/sandbox billing",
    "support diagnostics",
    "security/privacy boundaries",
    "PR hygiene/release train health",
    "policy-aware skill recommendation",
    "eval-driven catalog release gates",
    "maintainer improvement queues",
    "agent/runtime usage summaries",
    "governance dashboard",
    "optional self-hosted registry mode",
    "future automatic improvement proposals",
    "human-reviewed",
    "no automatic skill rewriting",
    "no auto-publish",
    "no automatic telemetry",
    "no live billing",
    "no PyPI publication",
    "no full catalog distribution",
    "no-prompt",
    "no-skill-body",
    "no-private-data",
    "must not gate the MIT local core behind registration",
    "must not weaken signed hosted manifest requirements",
    "automatic hosted query forwarding",
    "NO-GO",
]

FORBIDDEN_PHRASES = [
    "v0.4 is ready",
    "v0.4 is approved for implementation",
    "automatic skill rewriting is enabled",
    "auto-publish is enabled",
    "live billing is enabled",
    "full catalog distribution is enabled",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def fail(message: str) -> None:
    raise SystemExit(f"{RELEASE} verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def assert_required_docs() -> str:
    for path in REQUIRED_DOCS:
        require(path.is_file(), f"missing required file: {path.relative_to(ROOT)}")
    return "\n".join(read(path) for path in REQUIRED_DOCS)


def assert_required_content(text: str) -> None:
    lowered = text.lower()
    for phrase in REQUIRED_PHRASES:
        require(phrase.lower() in lowered, f"missing required phrase: {phrase}")
    for phrase in FORBIDDEN_PHRASES:
        require(phrase.lower() not in lowered, f"forbidden readiness claim found: {phrase}")


def assert_blocker_table() -> None:
    audit = read(ROOT / "docs" / "releases" / "v0.4-readiness-audit.md")
    for blocker in ("B-01", "B-02", "B-03", "B-04", "B-05", "B-06", "B-07", "B-08"):
        require(blocker in audit, f"missing blocker {blocker}")
    for heading in ("Owner", "Required action", "Fallback"):
        require(heading in audit, f"blocker table missing {heading}")


def assert_mermaid_architecture() -> None:
    rfc = read(ROOT / "docs" / "rfcs" / "v0.4-skillops-platform-rfc.md")
    require("```mermaid" in rfc, "RFC must include a Mermaid architecture diagram")
    require("flowchart" in rfc, "Mermaid diagram must define a flowchart")


def main() -> int:
    text = assert_required_docs()
    assert_required_content(text)
    assert_blocker_table()
    assert_mermaid_architecture()
    print("v0.4 readiness RFC verification passed")
    print("go/no-go recommendation: NO-GO until P0 blockers are closed")
    print("runtime implementation authorized: false")
    print("automatic rewriting authorized: false")
    print("auto-publish authorized: false")
    print("live billing authorized: false")
    print("full catalog distribution authorized: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
