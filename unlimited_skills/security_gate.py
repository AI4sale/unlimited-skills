from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Mapping
from pathlib import Path


SCANNER_ID = "nvidia-skillspector"
SCANNER_MODE = "static-no-llm"
SECURITY_SCAN_SCHEMA_VERSION = 1
SUPPORTED_SCANNER_VERSIONS = {"2.5.0"}
RECOMMENDATIONS = {"SAFE", "CAUTION", "DO_NOT_INSTALL"}
REVIEW_DECISIONS = {
    "approved_after_review",
    "risk_accepted",
}


class SkillSecurityGateError(RuntimeError):
    """Raised when a skill package has no valid security approval."""


def _skillspector_executable() -> str:
    configured = str(
        os.environ.get("UNLIMITED_SKILLS_SKILLSPECTOR") or ""
    ).strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return str(candidate)
        raise SkillSecurityGateError(
            "configured NVIDIA SkillSpector executable is missing"
        )
    executable = shutil.which("skillspector")
    if executable:
        return executable
    raise SkillSecurityGateError(
        "NVIDIA SkillSpector is required before installing skills"
    )


def _skill_directories(source: Path) -> list[Path]:
    source = source.expanduser().resolve()
    if source.is_file() and source.name.casefold() == "skill.md":
        return [source.parent]
    if not source.is_dir():
        raise SkillSecurityGateError(
            f"skill source does not exist: {source}"
        )
    candidates = sorted(
        {
            path.parent.resolve()
            for path in source.rglob("SKILL.md")
            if path.is_file()
        },
        key=lambda path: str(path).casefold(),
    )
    if not candidates:
        raise SkillSecurityGateError(
            "skill source contains no SKILL.md files"
        )
    return candidates


def _scan_one_skill(
    executable: str,
    skill_dir: Path,
) -> dict[str, Any]:
    completed = subprocess.run(
        [
            executable,
            "scan",
            str(skill_dir),
            "--no-llm",
            "--format",
            "json",
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SkillSecurityGateError(
            f"NVIDIA SkillSpector produced invalid JSON for "
            f"{skill_dir.name}"
        ) from exc
    if not isinstance(report, Mapping):
        raise SkillSecurityGateError(
            "NVIDIA SkillSpector report must be a JSON object"
        )
    if completed.returncode not in {0, 1}:
        raise SkillSecurityGateError(
            f"NVIDIA SkillSpector failed for {skill_dir.name}"
        )
    risk = (
        report.get("risk_assessment")
        if isinstance(report.get("risk_assessment"), Mapping)
        else {}
    )
    completeness = (
        report.get("analysis_completeness")
        if isinstance(
            report.get("analysis_completeness"),
            Mapping,
        )
        else {}
    )
    metadata = (
        report.get("metadata")
        if isinstance(report.get("metadata"), Mapping)
        else {}
    )
    skill = (
        report.get("skill")
        if isinstance(report.get("skill"), Mapping)
        else {}
    )
    recommendation = str(
        risk.get("recommendation") or ""
    )
    if recommendation not in RECOMMENDATIONS:
        raise SkillSecurityGateError(
            "NVIDIA SkillSpector returned an invalid recommendation"
        )
    if (
        completeness.get("execution_successful") is not True
        or float(completeness.get("coverage_percent") or 0) < 100
        or int(
            completeness.get("entirely_uninspected_files") or 0
        )
        != 0
        or completeness.get("ledger_exceptions")
    ):
        raise SkillSecurityGateError(
            f"NVIDIA SkillSpector did not fully inspect "
            f"{skill_dir.name}"
        )
    scanner_version = str(
        metadata.get("skillspector_version") or ""
    )
    if scanner_version not in SUPPORTED_SCANNER_VERSIONS:
        raise SkillSecurityGateError(
            "NVIDIA SkillSpector version is not approved by this "
            "Unlimited Skills release"
        )
    return {
        "skill": str(skill.get("name") or skill_dir.name),
        "scanner": SCANNER_ID,
        "scanner_version": scanner_version,
        "mode": SCANNER_MODE,
        "score": int(risk.get("score") or 0),
        "severity": str(risk.get("severity") or ""),
        "recommendation": recommendation,
        "finding_count": len(
            [
                item
                for item in report.get("issues") or []
                if isinstance(item, Mapping)
            ]
        ),
        "static_coverage_complete": True,
    }


def scan_skill_source(source: Path) -> dict[str, Any]:
    """Run the local NVIDIA gate without executing skill contents."""

    executable = _skillspector_executable()
    results = [
        _scan_one_skill(executable, skill_dir)
        for skill_dir in _skill_directories(source)
    ]
    versions = {
        item["scanner_version"]
        for item in results
    }
    if len(versions) != 1:
        raise SkillSecurityGateError(
            "NVIDIA SkillSpector version changed during the scan"
        )
    rank = {
        "SAFE": 0,
        "CAUTION": 1,
        "DO_NOT_INSTALL": 2,
    }
    worst = max(
        results,
        key=lambda item: (
            rank[item["recommendation"]],
            item["score"],
        ),
    )
    return {
        "schema_version": 1,
        "scanner": SCANNER_ID,
        "scanner_version": next(iter(versions)),
        "mode": SCANNER_MODE,
        "skill_count": len(results),
        "finding_count": sum(
            item["finding_count"]
            for item in results
        ),
        "max_risk_score": max(
            item["score"]
            for item in results
        ),
        "max_severity": worst["severity"],
        "recommendation": worst["recommendation"],
        "blocked_skills": [
            {
                "skill": item["skill"],
                "score": item["score"],
                "severity": item["severity"],
                "recommendation": item["recommendation"],
            }
            for item in results
            if item["recommendation"] != "SAFE"
        ],
        "static_coverage_complete": True,
    }


def assert_skill_source_safe(source: Path) -> dict[str, Any]:
    """Fail closed unless every discovered skill receives SAFE."""

    summary = scan_skill_source(source)
    if summary["recommendation"] != "SAFE":
        names = ", ".join(
            str(item["skill"])
            for item in summary["blocked_skills"]
        )
        raise SkillSecurityGateError(
            "NVIDIA SkillSpector blocked installation: "
            f"{summary['recommendation']} ({names})"
        )
    return summary


def _normalized_sha256(value: str) -> str:
    digest = str(value or "").removeprefix("sha256:")
    if (
        len(digest) != 64
        or any(
            character not in "0123456789abcdef"
            for character in digest.lower()
        )
    ):
        raise SkillSecurityGateError(
            "security attestation contains an invalid SHA-256 value"
        )
    return "sha256:" + digest.lower()


def validate_security_attestation(
    attestation: Mapping[str, Any],
    *,
    archive_sha256: str,
) -> dict[str, Any]:
    required = {
        "schema_version",
        "scanner",
        "scanner_version",
        "mode",
        "archive_sha256",
        "report_sha256",
        "recommendation",
        "max_risk_score",
        "max_severity",
        "skill_count",
        "finding_count",
        "finding_fingerprints_sha256",
        "execution_successful",
        "static_coverage_complete",
        "decision",
        "review_id",
        "review_evidence_sha256",
    }
    if set(attestation) != required:
        raise SkillSecurityGateError(
            "security attestation fields are incomplete"
        )
    if (
        attestation.get("schema_version")
        != SECURITY_SCAN_SCHEMA_VERSION
        or attestation.get("scanner") != SCANNER_ID
        or attestation.get("mode") != SCANNER_MODE
        or attestation.get("execution_successful") is not True
        or attestation.get("static_coverage_complete") is not True
        or str(attestation.get("scanner_version") or "")
        not in SUPPORTED_SCANNER_VERSIONS
    ):
        raise SkillSecurityGateError(
            "security attestation contract is invalid"
        )
    if _normalized_sha256(
        str(attestation.get("archive_sha256") or "")
    ) != _normalized_sha256(archive_sha256):
        raise SkillSecurityGateError(
            "security attestation is not bound to this archive"
        )
    _normalized_sha256(
        str(attestation.get("report_sha256") or "")
    )
    _normalized_sha256(
        str(
            attestation.get(
                "finding_fingerprints_sha256"
            )
            or ""
        )
    )
    recommendation = str(
        attestation.get("recommendation") or ""
    )
    decision = str(attestation.get("decision") or "")
    if recommendation not in RECOMMENDATIONS:
        raise SkillSecurityGateError(
            "security attestation recommendation is invalid"
        )
    if recommendation == "SAFE" and decision != "safe":
        raise SkillSecurityGateError(
            "SAFE security attestation has an invalid decision"
        )
    if (
        recommendation == "CAUTION"
        and decision not in REVIEW_DECISIONS
    ):
        raise SkillSecurityGateError(
            "CAUTION security attestation has no approved review"
        )
    if (
        recommendation == "DO_NOT_INSTALL"
        and decision != "risk_accepted"
    ):
        raise SkillSecurityGateError(
            "DO_NOT_INSTALL security attestation has no explicit "
            "risk acceptance"
        )
    return {
        "verified": True,
        "scanner": SCANNER_ID,
        "scanner_version": str(attestation["scanner_version"]),
        "mode": SCANNER_MODE,
        "recommendation": recommendation,
        "decision": decision,
        "report_sha256": str(attestation["report_sha256"]),
    }


def verify_manifest_security_gate(
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    required = manifest.get("security_scan_required", False)
    if not isinstance(required, bool):
        raise SkillSecurityGateError(
            "security_scan_required must be a boolean"
        )
    attestation = manifest.get("security_scan")
    if not required:
        if attestation is not None:
            raise SkillSecurityGateError(
                "security_scan requires security_scan_required=true"
            )
        return {
            "verified": False,
            "legacy_manifest": True,
            "reason": "security_scan_not_required_by_legacy_manifest",
        }
    if not isinstance(attestation, Mapping):
        raise SkillSecurityGateError(
            "security-gated package has no signed security attestation"
        )
    result = validate_security_attestation(
        attestation,
        archive_sha256=str(manifest.get("sha256") or ""),
    )
    result["legacy_manifest"] = False
    return result
