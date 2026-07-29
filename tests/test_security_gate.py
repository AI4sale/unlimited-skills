from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from unlimited_skills.security_gate import (
    SkillSecurityGateError,
    assert_skill_source_safe,
    verify_manifest_security_gate,
)


def _attestation(
    *,
    archive_sha256: str = "sha256:" + ("a" * 64),
    recommendation: str = "SAFE",
    decision: str = "safe",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "scanner": "nvidia-skillspector",
        "scanner_version": "2.5.0",
        "mode": "static-no-llm",
        "archive_sha256": archive_sha256,
        "report_sha256": "sha256:" + ("b" * 64),
        "recommendation": recommendation,
        "max_risk_score": 0,
        "max_severity": "LOW",
        "skill_count": 1,
        "finding_count": 0,
        "finding_fingerprints_sha256": (
            "sha256:" + ("c" * 64)
        ),
        "execution_successful": True,
        "static_coverage_complete": True,
        "decision": decision,
        "review_id": "",
        "review_evidence_sha256": "",
    }


def test_verifies_signed_archive_bound_security_attestation() -> None:
    manifest = {
        "sha256": "a" * 64,
        "security_scan_required": True,
        "security_scan": _attestation(),
    }

    result = verify_manifest_security_gate(manifest)

    assert result["verified"] is True
    assert result["legacy_manifest"] is False
    assert result["recommendation"] == "SAFE"


def test_rejects_missing_or_wrong_archive_binding() -> None:
    with pytest.raises(
        SkillSecurityGateError,
        match="no signed security attestation",
    ):
        verify_manifest_security_gate(
            {
                "sha256": "a" * 64,
                "security_scan_required": True,
            }
        )

    with pytest.raises(
        SkillSecurityGateError,
        match="not bound to this archive",
    ):
        verify_manifest_security_gate(
            {
                "sha256": "a" * 64,
                "security_scan_required": True,
                "security_scan": _attestation(
                    archive_sha256="sha256:" + ("d" * 64)
                ),
            }
        )


def test_blocks_unreviewed_caution_and_do_not_install() -> None:
    for recommendation in ("CAUTION", "DO_NOT_INSTALL"):
        with pytest.raises(SkillSecurityGateError):
            verify_manifest_security_gate(
                {
                    "sha256": "a" * 64,
                    "security_scan_required": True,
                    "security_scan": _attestation(
                        recommendation=recommendation,
                        decision="safe",
                    ),
                }
            )


def test_accepts_legacy_manifest_without_attestation() -> None:
    result = verify_manifest_security_gate(
        {"sha256": "a" * 64}
    )

    assert result == {
        "verified": False,
        "legacy_manifest": True,
        "reason": "security_scan_not_required_by_legacy_manifest",
    }


def _local_report(
    *,
    recommendation: str = "SAFE",
    score: int = 0,
    severity: str = "LOW",
) -> str:
    return json.dumps(
        {
            "skill": {"name": "example"},
            "risk_assessment": {
                "score": score,
                "severity": severity,
                "recommendation": recommendation,
            },
            "issues": [],
            "metadata": {
                "skillspector_version": "2.5.0",
            },
            "analysis_completeness": {
                "execution_successful": True,
                "coverage_percent": 100.0,
                "entirely_uninspected_files": 0,
                "ledger_exceptions": {},
            },
        }
    )


def test_local_source_runs_skillspector_before_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = tmp_path / "example"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Example\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "unlimited_skills.security_gate.shutil.which",
        lambda name: "/tools/skillspector",
    )
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=_local_report(),
            stderr="",
        )

    monkeypatch.setattr(
        "unlimited_skills.security_gate.subprocess.run",
        fake_run,
    )

    result = assert_skill_source_safe(tmp_path)

    assert result["recommendation"] == "SAFE"
    assert result["skill_count"] == 1
    assert calls[0][0] == "/tools/skillspector"
    assert "--no-llm" in calls[0]


def test_local_source_blocks_caution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = tmp_path / "example"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Example\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "unlimited_skills.security_gate.shutil.which",
        lambda name: "/tools/skillspector",
    )
    monkeypatch.setattr(
        "unlimited_skills.security_gate.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=_local_report(
                recommendation="CAUTION",
                score=21,
                severity="MEDIUM",
            ),
            stderr="",
        ),
    )

    with pytest.raises(
        SkillSecurityGateError,
        match="blocked installation: CAUTION",
    ):
        assert_skill_source_safe(tmp_path)
