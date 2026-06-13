"""Build and clean-install smoke for the v0.5.2 adoption instrumentation package.

This extends the v0.5.1 package smoke with the adoption instrumentation and
signal-rollup proof paths that must be available before publishing v0.5.2.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.5.2"


def load_v050_smoke():
    path = ROOT / "scripts" / "run-v050-alpha-package-smoke.py"
    spec = importlib.util.spec_from_file_location("run_v050_alpha_package_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package smoke runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.VERSION = VERSION
    return module


def clean_install_adoption_tools_smoke(module, wheel: Path, work: Path) -> dict[str, Any]:
    env_dir = work / "venv-adoption"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    py = module.venv_python(env_dir)
    cli = module.venv_script(env_dir, "unlimited-skills")
    module.run([str(py), "-m", "pip", "install", str(wheel)], cwd=work)

    project_root = work / "project"
    project_root.mkdir()
    claude_config = work / "claude.json"
    library = work / "library"

    mcp_install = module.run(
        [
            str(cli),
            "mcp",
            "install",
            "--claude-code",
            "--dry-run",
            "--json",
            "--project-root",
            str(project_root),
            "--claude-config",
            str(claude_config),
        ],
        cwd=work,
    )
    feedback_prepare = module.run(
        [
            str(cli),
            "--root",
            str(library),
            "feedback",
            "prepare",
            "--format",
            "json",
        ],
        cwd=work,
    )
    mcp_payload = json.loads(mcp_install.stdout)
    feedback_payload = json.loads(feedback_prepare.stdout)
    events_dir = library / ".learning"
    events_dir.mkdir(parents=True, exist_ok=True)
    raw_session = "raw-session-id-not-in-output"
    event_hash = "75df2e31b7c6"
    (events_dir / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "ts": 1.0,
                        "type": "suggest",
                        "payload": {
                            "query": "private task text",
                            "delivery_tier": 3,
                            "injected": True,
                            "score_bucket": "high",
                            "margin_bucket": "clear",
                            "session_correlation_id": event_hash,
                        },
                    }
                ),
                json.dumps({"ts": 2.0, "type": "skill_used", "payload": {"session_correlation_id": event_hash}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    learning_events = module.run([str(cli), "--root", str(library), "learning-summary", "--events"], cwd=work)
    learning_payload = json.loads(learning_events.stdout)
    return {
        "mcp_install_action": mcp_payload.get("action"),
        "mcp_install_dry_run": mcp_payload.get("dry_run"),
        "mcp_install_scope": mcp_payload.get("scope"),
        "mcp_install_has_redacted_diff": bool(mcp_payload.get("redacted_diff")),
        "feedback_schema_version": feedback_payload.get("schema_version"),
        "feedback_report_type": feedback_payload.get("report_type"),
        "feedback_upload_available": feedback_payload.get("upload_available"),
        "feedback_local_only": feedback_payload.get("local_only"),
        "feedback_hosted_calls": feedback_payload.get("hosted_calls"),
        "feedback_issue_templates": sorted(
            item.get("issue_type")
            for item in feedback_payload.get("issue_template_mapping", [])
            if isinstance(item, dict) and item.get("issue_type")
        ),
        "effectiveness_suggest_count": learning_payload.get("effectiveness", {}).get("suggest_count"),
        "effectiveness_post_suggest_use_rate": learning_payload.get("effectiveness", {}).get("post_suggest_use_rate"),
        "effectiveness_output_contains_private_query": "private task text" in learning_events.stdout,
        "effectiveness_output_contains_raw_session": raw_session in learning_events.stdout,
        "effectiveness_output_contains_session_hash": event_hash in learning_events.stdout,
    }


def signal_rollup_fixture_smoke(work: Path) -> dict[str, Any]:
    out = work / "rollup-fixture.md"
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate-public-alpha-signal-rollup.py"), "--fixture-mode", "--out", str(out)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
    return {
        "returncode": run.returncode,
        "created": out.exists(),
        "has_low_signal": "low_signal" in text,
        "has_no_feedback_yet": "no_feedback_yet" in text,
        "has_no_telemetry": "no telemetry" in text.lower(),
        "stdout": run.stdout.strip(),
        "stderr_tail": run.stderr[-600:],
    }


def verify(report: dict[str, Any], module) -> list[str]:
    errors = list(module.verify(report))
    adoption = report.get("clean_install_adoption_tools") or {}
    rollup = report.get("signal_rollup_fixture") or {}
    if adoption.get("mcp_install_action") != "install":
        errors.append("clean install mcp install --claude-code must report install action")
    if adoption.get("mcp_install_dry_run") is not True:
        errors.append("clean install mcp install --claude-code must run as dry-run in smoke")
    if adoption.get("mcp_install_scope") != "project":
        errors.append("clean install mcp install --claude-code must default to project scope")
    if adoption.get("feedback_schema_version") != 1:
        errors.append("clean install feedback prepare must emit schema_version 1")
    if adoption.get("feedback_report_type") != "feedback-prepare-report":
        errors.append("clean install feedback prepare report_type mismatch")
    if adoption.get("feedback_upload_available") is not False:
        errors.append("clean install feedback prepare must not offer upload")
    if adoption.get("feedback_local_only") is not True:
        errors.append("clean install feedback prepare must report local_only true")
    if adoption.get("feedback_hosted_calls") is not False:
        errors.append("clean install feedback prepare must not make hosted calls")
    for template in ("first_value", "install_friction", "skill_not_invoked", "mcp_savings"):
        if template not in adoption.get("feedback_issue_templates", []):
            errors.append(f"clean install feedback prepare missing issue template mapping: {template}")
    if adoption.get("effectiveness_suggest_count") != 1:
        errors.append("clean install learning-summary --events must include one suggest event")
    if adoption.get("effectiveness_post_suggest_use_rate") != 1.0:
        errors.append("clean install learning-summary --events must compute post_suggest_use_rate")
    if adoption.get("effectiveness_output_contains_private_query"):
        errors.append("learning-summary --events must not print query text")
    if adoption.get("effectiveness_output_contains_raw_session"):
        errors.append("learning-summary --events must not print raw session ids")
    if adoption.get("effectiveness_output_contains_session_hash"):
        errors.append("learning-summary --events must not print session hashes")
    if rollup.get("returncode") != 0 or not rollup.get("created"):
        errors.append("signal rollup fixture generator must run and write output")
    for key in ("has_low_signal", "has_no_feedback_yet", "has_no_telemetry"):
        if rollup.get(key) is not True:
            errors.append(f"signal rollup fixture missing required marker: {key}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)

    module = load_v050_smoke()
    tmp = Path(tempfile.mkdtemp(prefix="uls-v052-package-smoke-"))
    try:
        dist_dir = tmp / "dist"
        dist_dir.mkdir()
        wheel, sdist = module.build_dist(dist_dir)
        report = {
            "schema_version": 1,
            "version": VERSION,
            "dist": module.inspect_dist(wheel, sdist),
            "clean_install": module.clean_install_smoke(wheel, tmp / "install"),
            "clean_install_adoption_tools": clean_install_adoption_tools_smoke(module, wheel, tmp / "adoption"),
            "signal_rollup_fixture": signal_rollup_fixture_smoke(tmp / "rollup"),
        }
        report["errors"] = verify(report, module)
        report["ok"] = not report["errors"]
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print("v0.5.2-alpha package smoke: " + ("PASS" if report["ok"] else "FAIL"))
            for error in report["errors"]:
                print(f"- {error}")
        return 0 if report["ok"] else 1
    finally:
        if args.keep_temp:
            print(f"kept temp: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
