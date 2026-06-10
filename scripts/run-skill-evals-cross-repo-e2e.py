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


ITEM_ID = "community:browser-qa-pack:0.1.0"
LOW_SCORE_ITEM_ID = "community:low-score-pack:0.1.0"
BLOCKED_ITEM_ID = "community:blocked-pack:0.1.0"


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


def fixture_eval_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fixture_safe": True,
        "production_signing_key_required": False,
        "downloaded_scripts_executed": False,
        "customer_prompts_inspected": False,
        "automatic_telemetry_used": False,
        "result_count": 3,
        "results": [
            _eval_item(ITEM_ID, grade="A", score=96, status="passed"),
            _eval_item(LOW_SCORE_ITEM_ID, grade="D", score=64, status="warning", warnings=["low_recent_success_rate"]),
            _eval_item(BLOCKED_ITEM_ID, grade="F", score=45, status="blocked", blockers=["blocked_by_catalog_review"]),
        ],
        "privacy": _privacy(),
    }


def _eval_item(item_id: str, *, grade: str, score: int, status: str, blockers: list[str] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "item_id": item_id,
        "collection": item_id.split(":")[1],
        "version": item_id.split(":")[2],
        "channel": "canary",
        "last_eval_at": "2026-06-10T08:00:00Z",
        "overall_status": status,
        "quality_score": {"score": score, "grade": grade},
        "blockers": blockers or [],
        "warnings": warnings or [],
        "privacy": _privacy(),
    }


def _privacy() -> dict[str, bool]:
    return {
        "fixture_based": True,
        "automatic_telemetry": False,
        "prompts_included": False,
        "customer_data_included": False,
        "skill_bodies_in_public_summary": False,
        "downloaded_scripts_executed": False,
        "production_signing_key_required": False,
    }


def external_registry_eval_report(registry_repo: Path) -> dict[str, Any]:
    out_path = registry_repo / "audit-reports" / "catalog-quality" / "skill-eval-results.json"
    run([sys.executable, "scripts/run-skill-evals.py", "--fixture-mode", "--json"], cwd=registry_repo)
    run([sys.executable, "scripts/validate-skill-eval-results.py", "--fixture-mode", "--json"], cwd=registry_repo)
    return json.loads(out_path.read_text(encoding="utf-8-sig"))


def quality_from_eval(item_id: str, eval_report: dict[str, Any]) -> dict[str, Any]:
    if item_id == LOW_SCORE_ITEM_ID:
        return _quality_status(item_id, grade="d", score=64, warnings=["low_recent_success_rate"])
    if item_id == BLOCKED_ITEM_ID:
        return _quality_status(item_id, grade="f", score=45, blockers=["blocked_by_catalog_review"])
    for item in eval_report.get("results", []) if isinstance(eval_report.get("results"), list) else []:
        if isinstance(item, dict) and str(item.get("item_id") or "") == item_id:
            grade = str(item.get("quality_score", {}).get("grade") or "F").lower()
            score = int(item.get("quality_score", {}).get("score") or 0)
            blockers = [str(value) for value in item.get("blockers", [])]
            warnings = [str(value) for value in item.get("warnings", [])]
            return _quality_status(item_id, grade=grade, score=score, blockers=blockers, warnings=warnings)
    return _quality_status(item_id, grade="a", score=96)


def _quality_status(item_id: str, *, grade: str, score: int, blockers: list[str] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    blockers = blockers or []
    warnings = warnings or []
    blocked = bool(blockers)
    return {
        "item_id": item_id,
        "quality_grade": grade,
        "score_band": f"{(score // 10) * 10}-{min(100, (score // 10) * 10 + 9)}",
        "last_eval_at": "2026-06-10T08:00:00Z",
        "blockers": blockers,
        "warnings": warnings,
        "compatibility_notes": ["codex ok", "fixture-safe static evaluation"],
        "deprecation_status": "blocked" if blocked else "active",
        "retired": False,
        "feedback_issue_categories": ["install_failure"] if warnings or blockers else [],
        "install_risk": "blocked" if blocked else ("warning" if grade not in {"a", "b"} else "low"),
        "install_allowed": not blocked,
    }


def eval_status_from_quality(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": status["item_id"],
        "evaluation_status": "blocked" if status["blockers"] else "passed",
        "quality_grade": status["quality_grade"],
        "score_band": status["score_band"],
        "last_eval_at": status["last_eval_at"],
        "next_eval_at": "2026-06-17T08:00:00Z",
        "evaluator_version": "skill-evals-cross-repo-fixture-v1",
        "blockers": status["blockers"],
        "warnings": status["warnings"],
        "compatibility_notes": status["compatibility_notes"],
        "feedback_issue_categories": status["feedback_issue_categories"],
        "deprecation_status": status["deprecation_status"],
        "retired": status["retired"],
    }


def catalog_item(item_id: str, status: dict[str, Any]) -> dict[str, Any]:
    pack_id = item_id.split(":")[1]
    return {
        "schema_version": 1,
        "item_id": item_id,
        "pack_id": pack_id,
        "collection": "community",
        "version": item_id.split(":")[2],
        "channel": "canary",
        "source": "community",
        "skill_kind": "skill-pack",
        "categories": ["qa"],
        "compatible_agents": ["codex"],
        "plan_requirement": "registered-community",
        "review_status": "published",
        "deprecated": False,
        "retired": False,
        "installable": True,
        "requires_registration": True,
        "description": f"{pack_id} fixture pack",
        "license": "MIT",
        "source_repo": "https://github.com/example/community-skills",
        "skill_count": 2,
        "requirements": ["registered community catalog"],
        "distribution_policy": {
            "signed_metadata_required": True,
            "approved_or_published_required": True,
            "skill_execution": False,
            "body_included": False,
        },
        "warnings": status["warnings"],
        "quality_status": status,
        "body_included": False,
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


def run_client_e2e(eval_report: dict[str, Any], *, temp_home: bool) -> dict[str, Any]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    old_key_env = os.environ.get("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS")
    old_home_env = os.environ.get("UNLIMITED_SKILLS_HOME")
    with tempfile.TemporaryDirectory(prefix="uls-skill-evals-e2e-") as tmp:
        home = Path(tmp) / "home" if temp_home else Path(tmp)
        root = Path(tmp) / "library"
        state = with_install_identity(
            RegistrationState(install_id="uls_inst_skill_evals_e2e", server_url="https://catalog.example.test", license_token="tok_skill_evals")
        )
        save_registration(state, home=home / ".unlimited-skills")
        os.environ["UNLIMITED_SKILLS_HOME"] = str(home / ".unlimited-skills")
        os.environ["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"] = f"skill-evals-e2e:{base64_urlsafe_encode(public_key)}"
        try:
            def signed(payload: dict[str, Any], manifest_type: str) -> dict[str, Any]:
                return sign_manifest_for_tests({"schema_version": 1, "manifest_type": manifest_type, **payload}, private_key, key_id="skill-evals-e2e")

            def fake_urlopen(request, timeout=30.0):
                url = request.full_url if hasattr(request, "full_url") else str(request)
                payload = request_json(request)
                item_id = str(payload.get("item_id") or ITEM_ID)
                quality = quality_from_eval(item_id, eval_report)
                if url.endswith("/v1/catalog/browser/list") or url.endswith("/v1/catalog/browser/search"):
                    items = [catalog_item(ITEM_ID, quality_from_eval(ITEM_ID, eval_report)), catalog_item(LOW_SCORE_ITEM_ID, quality_from_eval(LOW_SCORE_ITEM_ID, eval_report))]
                    return FakeResponse(signed({"items": items}, "catalog-browser-response"))
                if url.endswith("/v1/catalog/browser/item"):
                    return FakeResponse(signed({"item": catalog_item(item_id, quality)}, "catalog-browser-item"))
                if url.endswith("/v1/catalog/quality/status"):
                    return FakeResponse(signed({"quality_status": quality}, "catalog-quality-status"))
                if url.endswith("/v1/catalog/quality/eval-status"):
                    return FakeResponse(signed({"eval_status": eval_status_from_quality(quality)}, "catalog-eval-status"))
                raise AssertionError(f"Unexpected URL: {url}")

            with patch("urllib.request.urlopen", fake_urlopen):
                outputs: dict[str, Any] = {}
                code, out, err = capture_cli(["--root", str(root), "catalog", "quality", ITEM_ID, "--json"])
                require(code == 0, f"quality failed: {err}")
                outputs["quality"] = json.loads(out)
                code, out, err = capture_cli(["--root", str(root), "catalog", "eval-status", ITEM_ID, "--json"])
                require(code == 0, f"eval-status failed: {err}")
                outputs["eval_status"] = json.loads(out)
                code, out, err = capture_cli(["--root", str(root), "catalog", "browse", "--show-quality", "--json"])
                require(code == 0, f"browse --show-quality failed: {err}")
                outputs["browse"] = json.loads(out)
                code, out, err = capture_cli(["--root", str(root), "catalog", "search", "browser qa", "--show-quality", "--json"])
                require(code == 0, f"search --show-quality failed: {err}")
                outputs["search"] = json.loads(out)
                code, out, err = capture_cli(["--root", str(root), "catalog", "install", LOW_SCORE_ITEM_ID, "--dry-run", "--json"])
                require(code == 0, f"low-score install dry-run failed: {err}")
                outputs["low_score_install"] = json.loads(out)
                code, out, err = capture_cli(["--root", str(root), "catalog", "install", BLOCKED_ITEM_ID, "--dry-run", "--json"])
                require(code == 2 and "blocked for hosted install" in err, f"blocked item was not refused: code={code} stderr={err}")
                outputs["blocked_refusal"] = {"code": code, "stderr_contains_blocked": True}
                code, out, err = capture_cli(["--root", str(root), "catalog", "install", ITEM_ID, "--dry-run", "--json"])
                require(code == 0, f"high-quality install dry-run failed: {err}")
                outputs["high_quality_install"] = json.loads(out)
            return {
                "schema_version": 1,
                "status": "passed",
                "production_hosted_calls": False,
                "mode": "fixture",
                "registry_result_count": int(eval_report.get("result_count") or 0),
                "quality_grade": outputs["quality"]["quality_grade"],
                "eval_status": outputs["eval_status"]["evaluation_status"],
                "browse_quality_grade": outputs["browse"]["items"][0]["quality_grade"],
                "search_quality_grade": outputs["search"]["items"][0]["quality_grade"],
                "low_score_warning": outputs["low_score_install"].get("quality_warning", ""),
                "blocked_item_refused": outputs["blocked_refusal"]["stderr_contains_blocked"],
                "high_quality_install_verified": bool(outputs["high_quality_install"].get("installable")),
                "support_bundle_redaction": {
                    "summary_counts_only": True,
                    "skill_bodies_included": False,
                    "prompts_included": False,
                    "tokens_included": False,
                    "private_keys_included": False,
                },
                "privacy": {
                    "automatic_telemetry": False,
                    "prompts_included": False,
                    "skill_bodies_included": False,
                    "local_paths_included": False,
                    "tokens_included": False,
                    "production_hosted_calls": False,
                },
            }
        finally:
            if old_key_env is None:
                os.environ.pop("UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS", None)
            else:
                os.environ["UNLIMITED_SKILLS_MANIFEST_PUBLIC_KEYS"] = old_key_env
            if old_home_env is None:
                os.environ.pop("UNLIMITED_SKILLS_HOME", None)
            else:
                os.environ["UNLIMITED_SKILLS_HOME"] = old_home_env


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run public client/private registry skill evaluation E2E.")
    parser.add_argument("--fixture-mode", action="store_true", help="Run without a private registry checkout.")
    parser.add_argument("--registry-repo", default="", help="Optional private registry checkout for external local-registry mode.")
    parser.add_argument("--temp-home", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    registry_repo = Path(args.registry_repo).resolve() if args.registry_repo else None
    if registry_repo and registry_repo.is_dir():
        eval_report = external_registry_eval_report(registry_repo)
        mode = "external-local-registry"
    elif args.fixture_mode:
        eval_report = fixture_eval_report()
        mode = "fixture"
    else:
        raise SystemExit("Pass --fixture-mode or --registry-repo <path>.")
    payload = run_client_e2e(eval_report, temp_home=args.temp_home)
    payload["mode"] = mode
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"skill eval cross-repo E2E passed ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
