from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unlimited_skills.cli import main as cli_main
from unlimited_skills.registration import RegistrationState, base64_urlsafe_encode, save_registration, with_install_identity
from unlimited_skills.signatures import sign_manifest_for_tests
from unlimited_skills.skill_improvements import redacted_skill_improvement_summary


ITEM_ID = "community:browser-qa-pack:0.1.0"
DEPRECATED_ITEM_ID = "community:legacy-browser-qa-pack:0.1.0"


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._stream = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def run(command: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise SystemExit(f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}\n{completed.stderr}")
    return completed.stdout.strip()


def run_json(command: list[str], *, cwd: Path) -> dict[str, Any]:
    stdout = run(command, cwd=cwd)
    return json.loads(stdout) if stdout else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def fixture_registry_outputs() -> dict[str, Any]:
    candidate = {
        "candidate_id": "sic_browser_qa_compatibility",
        "item_id": ITEM_ID,
        "category": "compatibility_issue",
        "severity": "high",
        "status": "fixed_pending_eval",
        "owner": "maintainer-review",
    }
    backlog = {
        "schema_version": 1,
        "candidate_count": 1,
        "summary": {
            "open_improvement_count": 1,
            "counts_by_status": {"fixed_pending_eval": 1},
            "counts_by_category": {"compatibility_issue": 1},
            "counts_by_severity": {"high": 1},
            "top_issue_categories": [{"category": "compatibility_issue", "count": 1}],
        },
        "candidates": [candidate],
        "privacy": privacy_flags(),
        "safety": safety_flags(),
    }
    eval_results = {
        "schema_version": 1,
        "fixture_safe": True,
        "result_count": 1,
        "results": [
            {
                "item_id": ITEM_ID,
                "collection": "browser-qa-pack",
                "version": "0.1.0",
                "overall_status": "warning",
                "quality_score": {"score": 64, "grade": "D"},
                "warnings": ["compatibility metadata missing"],
                "blockers": [],
            }
        ],
        "privacy": privacy_flags(),
    }
    feedback = {
        "schema_version": 1,
        "feedback_count": 1,
        "recent": [
            {
                "feedback_id": "cfb_browser_qa_compatibility",
                "item_id": ITEM_ID,
                "feedback_type": "compatibility_issue",
                "severity": "high",
                "triage_status": "new",
            }
        ],
        "privacy": privacy_flags(),
    }
    quality_report = {
        "schema_version": 1,
        "report_type": "registry-catalog-quality",
        "counts": {"skill_eval_results": 1, "open_improvements": 1},
        "skill_improvements": backlog,
        "privacy": {"skill_bodies_included": False, "private_skill_bodies_included": False, "public_summary_safe": True},
    }
    return {
        "schema_version": 1,
        "mode": "fixture",
        "eval_results": eval_results,
        "feedback_summary": feedback,
        "backlog": backlog,
        "triage": {
            "accepted": {"status": "updated", "candidate": {**candidate, "status": "accepted"}},
            "fixed_pending_eval": {"status": "updated", "candidate": candidate},
        },
        "catalog_quality_report": quality_report,
        "privacy": privacy_flags(),
        "safety": safety_flags(),
    }


def external_registry_outputs(registry_repo: Path) -> dict[str, Any]:
    registry_repo = registry_repo.resolve()
    if not (registry_repo / "scripts" / "generate-skill-improvement-backlog.py").is_file():
        raise SystemExit("registry checkout is missing skill improvement scripts")
    with tempfile.TemporaryDirectory(prefix="uls-skill-improvement-registry-") as tmp_name:
        tmp = Path(tmp_name)
        _write_temp_registry_fixture(tmp)
        eval_rel = "audit-reports/catalog-quality/e2e-skill-eval-results.json"
        backlog_rel = "audit-reports/catalog-quality/e2e-skill-improvement-backlog.json"
        report_rel = "audit-reports/catalog-quality/e2e-registry-catalog-quality.report.json"
        eval_results = run_json(
            [sys.executable, "scripts/run-skill-evals.py", "--repo-root", str(tmp), "--out", eval_rel, "--fixture-mode", "--json"],
            cwd=registry_repo,
        )
        backlog = run_json(
            [
                sys.executable,
                "scripts/generate-skill-improvement-backlog.py",
                "--repo-root",
                str(tmp),
                "--skill-eval-results",
                eval_rel,
                "--out",
                backlog_rel,
                "--fixture-mode",
                "--json",
            ],
            cwd=registry_repo,
        )
        run_json(
            [sys.executable, "scripts/validate-skill-improvement-backlog.py", "--repo-root", str(tmp), "--backlog", backlog_rel, "--json"],
            cwd=registry_repo,
        )
        candidate_id = str(backlog["candidates"][0]["candidate_id"])
        accepted = run_json(
            [
                sys.executable,
                "scripts/skill-improvement-review.py",
                "accept",
                candidate_id,
                "--repo-root",
                str(tmp),
                "--backlog",
                backlog_rel,
                "--reason",
                "fixture maintainer accepted metadata-only candidate",
                "--json",
            ],
            cwd=registry_repo,
        )
        fixed_pending_eval = run_json(
            [
                sys.executable,
                "scripts/skill-improvement-review.py",
                "fixed-pending-eval",
                candidate_id,
                "--repo-root",
                str(tmp),
                "--backlog",
                backlog_rel,
                "--reason",
                "candidate fixed pending next evaluation",
                "--json",
            ],
            cwd=registry_repo,
        )
        run(
            [
                sys.executable,
                "scripts/registry-catalog-quality-report.py",
                "--repo-root",
                str(tmp),
                "--skill-eval-results",
                eval_rel,
                "--skill-improvement-backlog",
                backlog_rel,
                "--out-json",
                report_rel,
                "--json-only",
            ],
            cwd=registry_repo,
        )
        report = json.loads((tmp / report_rel).read_text(encoding="utf-8-sig"))
        final_backlog = json.loads((tmp / backlog_rel).read_text(encoding="utf-8-sig"))
    return {
        "schema_version": 1,
        "mode": "external-local-registry",
        "eval_results": eval_results,
        "feedback_summary": fixture_registry_outputs()["feedback_summary"],
        "backlog": final_backlog,
        "triage": {"accepted": accepted, "fixed_pending_eval": fixed_pending_eval},
        "catalog_quality_report": report,
        "privacy": privacy_flags(),
        "safety": safety_flags(),
    }


def _write_temp_registry_fixture(root: Path) -> None:
    manifest = {
        "schema_version": 1,
        "item_id": ITEM_ID,
        "pack_id": "browser-qa-pack",
        "collection": "browser-qa-pack",
        "version": "0.1.0",
        "channel": "stable",
        "license": "MIT",
        "archive": "browser-qa-pack.zip",
        "format": "skill-collection-zip-v1",
        "skills": ["browser-qa-fixture"],
        "compatible_agents": ["codex"],
        "min_core_version": "0.3.9",
    }
    write_json(root / "catalog" / "browser-qa-pack" / "0.1.0" / "manifest.json", manifest)
    (root / "catalog" / "browser-qa-pack" / "0.1.0" / "browser-qa-pack" / "skills" / "browser-qa-fixture").mkdir(parents=True)
    (root / "catalog" / "browser-qa-pack" / "0.1.0" / "browser-qa-pack" / "skills" / "browser-qa-fixture" / "SKILL.md").write_text(
        "---\nname: browser-qa-fixture\ndescription: Public-safe fixture skill for registry evaluation.\n---\n\n## Procedure\n\nRun fixture checks.\n",
        encoding="utf-8",
    )
    write_json(
        root / "registry" / "generated" / "signed" / "catalog-updates.v1.json",
        {"manifest_signature": {"key_id": "fixture", "signature": "fixture"}, "packs": [{"collection": "browser-qa-pack", "version": "0.1.0", "channel": "stable"}]},
    )


def privacy_flags() -> dict[str, bool]:
    return {
        "automatic_telemetry": False,
        "prompts_included": False,
        "task_text_included": False,
        "skill_bodies_included": False,
        "search_queries_included": False,
        "local_paths_included": False,
        "repo_paths_included": False,
        "customer_data_included": False,
        "tokens_included": False,
        "proofs_included": False,
        "private_keys_included": False,
        "production_hosted_calls": False,
    }


def safety_flags() -> dict[str, bool]:
    return {
        "maintainer_review_required": True,
        "automatic_skill_rewriting": False,
        "auto_publish": False,
        "untrusted_script_execution": False,
        "production_hosted_calls_in_tests": False,
    }


def public_item_id(registry_outputs: dict[str, Any]) -> str:
    candidates = registry_outputs.get("backlog", {}).get("candidates", [])
    if candidates and isinstance(candidates[0], dict) and candidates[0].get("item_id"):
        return str(candidates[0]["item_id"])
    return ITEM_ID


def improvement_status(item_id: str) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "installed_version": "0.1.0",
        "latest_version": "0.1.1",
        "recommended_version": "0.1.1",
        "recommended_channel": "stable",
        "open_issue_count": 1,
        "severity_summary": {"high": 1},
        "fix_status": "fixed_pending_eval",
        "deprecated": False,
        "retired": False,
        "compatibility_notes": ["codex >=0.3.9", "maintainer fix pending eval"],
        "stale_installed_version": True,
        "update_available": True,
        "recommended_action": "update",
    }


def known_issues(item_id: str) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "open_issue_count": 1,
        "severity_summary": {"high": 1},
        "fix_status": "fixed_pending_eval",
        "issues": [
            {
                "issue_id": "SIC-0001",
                "severity": "high",
                "status": "open",
                "fix_status": "fixed_pending_eval",
                "title": "Compatibility remediation candidate accepted",
                "fixed_in_version": "0.1.1",
                "compatibility_notes": ["awaiting next registry eval"],
            }
        ],
    }


def recommendation(item_id: str) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "installed_version": "0.1.0",
        "recommended_version": "0.1.1",
        "recommended_channel": "stable",
        "recommended_action": "update",
        "reason": "Maintainer accepted remediation candidate and marked it fixed pending eval.",
        "open_issue_count": 1,
        "severity_summary": {"high": 1},
        "fix_status": "fixed_pending_eval",
        "deprecated": False,
        "retired": False,
        "stale_installed_version": True,
        "compatibility_notes": ["preview-only recommendation"],
        "preview_only": True,
        "will_install": False,
        "will_update": False,
        "will_remove": False,
    }


def deprecation_status() -> dict[str, Any]:
    return {
        "item_id": DEPRECATED_ITEM_ID,
        "deprecated": True,
        "retired": True,
        "deprecation_reason": "Superseded by browser-qa-pack metadata-only remediation.",
        "retirement_reason": "Retired from hosted recommendations after maintainer review.",
        "replacement_item_id": ITEM_ID,
        "recommended_version": "0.1.1",
        "recommended_channel": "stable",
        "recommended_action": "update",
        "compatibility_notes": ["legacy package should not be newly installed"],
    }


def quality_status(item_id: str) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "quality_grade": "d",
        "score_band": "60-69",
        "last_eval_at": "2026-06-10T00:00:00Z",
        "blockers": [],
        "warnings": ["compatibility issue has maintainer remediation candidate"],
        "compatibility_notes": ["fixed pending eval"],
        "deprecation_status": "active",
        "retired": False,
        "feedback_issue_categories": ["compatibility_issue"],
        "install_risk": "warning",
        "install_allowed": True,
    }


def request_json(request: object) -> dict[str, Any]:
    raw = getattr(request, "data", b"") or b""
    if isinstance(raw, bytes) and raw:
        return json.loads(raw.decode("utf-8"))
    return {}


def capture_cli(args: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main(args)
    return code, out.getvalue(), err.getvalue()


def run_cross_repo_e2e(registry_outputs: dict[str, Any], *, temp_home: bool, mode: str) -> dict[str, Any]:
    item_id = public_item_id(registry_outputs)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    old_key_env = os.environ.get("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS")
    old_home_env = os.environ.get("UNLIMITED_SKILLS_HOME")
    with tempfile.TemporaryDirectory(prefix="uls-skill-improvement-e2e-") as tmp:
        home = Path(tmp) / "home" if temp_home else Path(tmp)
        root = Path(tmp) / "library"
        state = with_install_identity(
            RegistrationState(install_id="uls_inst_skill_improvement_e2e", server_url="https://catalog.example.test", license_token="tok_skill_improvement")
        )
        save_registration(state, home=home / ".unlimited-skills")
        os.environ["UNLIMITED_SKILLS_HOME"] = str(home / ".unlimited-skills")
        os.environ["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"] = f"skill-improvement-e2e:{base64_urlsafe_encode(public_key)}"
        seen_urls: list[str] = []
        try:

            def signed(payload: dict[str, Any], manifest_type: str) -> dict[str, Any]:
                return sign_manifest_for_tests({"schema_version": 1, "manifest_type": manifest_type, **payload}, private_key, key_id="skill-improvement-e2e")

            def fake_urlopen(request, timeout=30.0):
                url = request.full_url if hasattr(request, "full_url") else str(request)
                seen_urls.append(url)
                payload = request_json(request)
                requested_item = str(payload.get("item_id") or item_id)
                if not url.startswith("https://catalog.example.test/"):
                    raise AssertionError(f"Unexpected non-fixture URL: {url}")
                if url.endswith("/v1/catalog/quality/status"):
                    return FakeResponse(signed({"quality_status": quality_status(requested_item)}, "catalog-quality-status"))
                if url.endswith("/v1/catalog/improvements/status"):
                    return FakeResponse(signed({"improvement_status": improvement_status(requested_item)}, "skill-improvement-status"))
                if url.endswith("/v1/catalog/improvements/known-issues"):
                    return FakeResponse(signed({"known_issues": known_issues(requested_item)}, "skill-known-issues"))
                if url.endswith("/v1/catalog/improvements/update-recommendations"):
                    return FakeResponse(signed({"recommendations": [recommendation(item_id)]}, "update-recommendations"))
                if url.endswith("/v1/catalog/improvements/update-preview"):
                    return FakeResponse(signed({"recommendation": recommendation(requested_item)}, "update-preview"))
                if url.endswith("/v1/catalog/improvements/deprecation-status"):
                    return FakeResponse(signed({"deprecation_status": deprecation_status()}, "deprecation-status"))
                raise AssertionError(f"Unexpected URL: {url}")

            with patch("urllib.request.urlopen", fake_urlopen):
                outputs: dict[str, Any] = {}
                for name, args in {
                    "quality": ["--root", str(root), "catalog", "quality", item_id, "--json"],
                    "improvement_status": ["--root", str(root), "catalog", "improvement-status", item_id, "--json"],
                    "known_issues": ["--root", str(root), "catalog", "known-issues", item_id, "--json"],
                    "update_recommendations": ["--root", str(root), "catalog", "update-recommendations", "--json"],
                    "update_preview": ["--root", str(root), "catalog", "update-preview", item_id, "--json"],
                    "deprecation_status": ["--root", str(root), "catalog", "deprecation-status", DEPRECATED_ITEM_ID, "--json"],
                }.items():
                    code, out, err = capture_cli(args)
                    require(code == 0, f"{name} failed: {err}")
                    outputs[name] = json.loads(out)
        finally:
            if old_key_env is None:
                os.environ.pop("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", None)
            else:
                os.environ["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"] = old_key_env
            if old_home_env is None:
                os.environ.pop("UNLIMITED_SKILLS_HOME", None)
            else:
                os.environ["UNLIMITED_SKILLS_HOME"] = old_home_env

    backlog = registry_outputs.get("backlog", {})
    report = registry_outputs.get("catalog_quality_report", {})
    triage = registry_outputs.get("triage", {})
    support_summary = redacted_skill_improvement_summary()
    payload = {
        "schema_version": 1,
        "status": "passed",
        "mode": mode,
        "production_hosted_calls": False,
        "registry": {
            "evals_ran": int(registry_outputs.get("eval_results", {}).get("result_count") or 0) >= 1,
            "feedback_created_issue": int(registry_outputs.get("feedback_summary", {}).get("feedback_count") or 0) >= 1
            or bool(registry_outputs.get("feedback_summary", {}).get("recent")),
            "backlog_generated": int(backlog.get("candidate_count") or len(backlog.get("candidates") or [])) >= 1,
            "maintainer_accepted_candidate": triage.get("accepted", {}).get("candidate", {}).get("status") == "accepted",
            "fixed_pending_eval": triage.get("fixed_pending_eval", {}).get("candidate", {}).get("status") == "fixed_pending_eval",
            "catalog_quality_report_has_improvements": "skill_improvements" in report and int(report.get("skill_improvements", {}).get("candidate_count") or 0) >= 1,
        },
        "public_client": outputs,
        "support_bundle": {
            "summary_counts_only": support_summary["summary_counts_only"],
            "skill_bodies_included": support_summary["skill_bodies_included"],
            "prompts_included": support_summary["prompts_included"],
            "tokens_included": support_summary["tokens_included"],
            "private_keys_included": support_summary["private_keys_included"],
        },
        "privacy": privacy_flags(),
        "network": {"fixture_hosted_calls": len(seen_urls), "production_hosted_calls": False},
    }
    require(all(payload["registry"].values()), f"registry proof incomplete: {payload['registry']}")
    require(outputs["update_recommendations"]["preview_only"] is True, "recommendations must be preview-only")
    require(outputs["update_preview"]["will_update"] is False, "update preview must not apply writes")
    require(outputs["deprecation_status"]["deprecated"] is True or outputs["deprecation_status"]["retired"] is True, "deprecated/retired warning missing")
    return payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run v0.3.9 skill improvement public/private cross-repo E2E.")
    parser.add_argument("--fixture-mode", action="store_true", help="Run without a private registry checkout.")
    parser.add_argument("--registry-repo", default="", help="Optional private registry checkout for external local-registry mode.")
    parser.add_argument("--temp-home", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    registry_repo = Path(args.registry_repo) if args.registry_repo else None
    if registry_repo and registry_repo.is_dir():
        registry_outputs = external_registry_outputs(registry_repo)
        mode = "external-local-registry"
    elif args.fixture_mode:
        registry_outputs = fixture_registry_outputs()
        mode = "fixture"
    else:
        raise SystemExit("Pass --fixture-mode or --registry-repo <path>.")
    payload = run_cross_repo_e2e(registry_outputs, temp_home=args.temp_home, mode=mode)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"skill improvement cross-repo E2E passed ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
